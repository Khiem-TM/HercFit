"""Content-free model/node measurements; no prompts, completions, or credentials."""
from agentic.observability import graph_config
from contextvars import ContextVar
from time import perf_counter
import math
from langchain_core.callbacks import BaseCallbackHandler

active_metrics = ContextVar('agent_node_metrics', default=None)


def record_jev_result(result):
    """Measure every gateway attempt without retaining inputs or answers."""
    metrics = active_metrics.get()
    if metrics is None:
        return
    keys = ('evaluation_id', 'phase', 'status', 'reason', 'model', 'usage', 'cost',
            'duration_ms', 'policy_version', 'cached', 'mode', 'enforced', 'attempted')
    metrics.setdefault('jev_events', []).append({k: result[k] for k in keys if k in result})
    from agentic.observability import annotate
    annotate(jev_mode=result.get('mode'), jev_phase=result.get('phase'),
             jev_status=result.get('status'), jev_fallback=result.get('reason'),
             jev_model=result.get('model'), jev_policy_version=result.get('policy_version'),
             jev_attempted=result.get('attempted', False), jev_cost=result.get('cost'),
             jev_input_tokens=(result.get('usage') or {}).get('input_tokens'),
             jev_output_tokens=(result.get('usage') or {}).get('output_tokens'),
             jev_confidence={k: v['confidence'] for k, v in result.get('answers', {}).items() if 'confidence' in v},
             jev_probabilities={k: v['noul'] for k, v in result.get('answers', {}).items() if 'noul' in v})


def merge_jev_metrics(telemetry, events):
    """Keep shadow spend distinct and never charge cached usage twice."""
    for event in events:
        if event.get('cached'):
            telemetry['jev_cache_hits'] = telemetry.get('jev_cache_hits', 0) + 1
        if not event.get('attempted') or event.get('cached'):
            continue
        prefix = 'jev_shadow_' if event.get('mode') == 'shadow' else 'jev_'
        telemetry[prefix+'calls'] = telemetry.get(prefix+'calls', 0) + 1
        telemetry[prefix+'ms'] = telemetry.get(prefix+'ms', 0) + event.get('duration_ms', 0)
        usage = event.get('usage')
        if usage is None:
            telemetry[prefix+'usage_unknown_calls'] = telemetry.get(prefix+'usage_unknown_calls', 0) + 1
        else:
            for key in ('input_tokens', 'output_tokens'):
                telemetry[prefix+key] = telemetry.get(prefix+key, 0) + usage.get(key, 0)
        cost = event.get('cost')
        if cost is None:
            telemetry[prefix+'cost_unknown_calls'] = telemetry.get(prefix+'cost_unknown_calls', 0) + 1
        else:
            telemetry[prefix+'cost'] = telemetry.get(prefix+'cost', 0) + cost
    telemetry['total_input_tokens'] = telemetry.get('input_tokens', 0) + telemetry.get('jev_input_tokens', 0)
    telemetry['total_output_tokens'] = telemetry.get('output_tokens', 0) + telemetry.get('jev_output_tokens', 0)
    unknown = telemetry.get('llm_cost_unknown_calls', 0) + telemetry.get('jev_cost_unknown_calls', 0)
    usage_unknown = telemetry.get('llm_usage_unknown_calls', 0) + telemetry.get('jev_usage_unknown_calls', 0)
    telemetry['model_cost_status'] = 'unknown' if unknown else 'configured'
    telemetry['model_usage_status'] = 'unknown' if usage_unknown else 'reported'
    telemetry['total_model_cost'] = None if unknown else telemetry.get('llm_cost', 0) + telemetry.get('jev_cost', 0)


class _Usage(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.available = False

    def on_llm_end(self, response, **kwargs):
        usage = (response.llm_output or {}).get('token_usage', {})
        if not usage:
            for group in response.generations:
                for generation in group:
                    usage = getattr(getattr(generation, 'message', None), 'usage_metadata', None) or {}
                    if usage:
                        break
                if usage:
                    break
        if ('input_tokens' in usage or 'prompt_tokens' in usage) and ('output_tokens' in usage or 'completion_tokens' in usage):
            self.available = True
        self.input_tokens += usage.get('input_tokens', usage.get('prompt_tokens', 0)) or 0
        self.output_tokens += usage.get('output_tokens', usage.get('completion_tokens', 0)) or 0


class _MeasuredModel:
    def __init__(self, model, price=None):
        self.model = model
        self.price = price

    def with_structured_output(self, *args, **kwargs):
        return _MeasuredModel(self.model.with_structured_output(*args, **kwargs), self.price)

    def bind_tools(self, *args, **kwargs):
        return _MeasuredModel(self.model.bind_tools(*args, **kwargs), self.price)

    async def ainvoke(self, messages, **kwargs):
        metrics = active_metrics.get()
        if metrics is None:
            return await self.model.ainvoke(messages, **kwargs)
        usage = _Usage()
        from langchain_core.runnables.config import ensure_config
        config = ensure_config(kwargs.pop('config', None))
        callbacks = config.get('callbacks')
        if callbacks is not None and not isinstance(callbacks, list):
            callbacks = callbacks.copy()
            # Structured-output RunnableSequences invoke the LLM as a child;
            # its usage callback must survive child callback-manager creation.
            callbacks.add_handler(usage, inherit=True)
        else:
            callbacks = [*(callbacks or []), usage]
        config['callbacks'] = callbacks
        started = perf_counter()
        metrics['llm_calls'] = metrics.get('llm_calls', 0) + 1
        result = None
        try:
            result = await self.model.ainvoke(messages, config=graph_config(config), **kwargs)
            return result
        finally:
            metadata = getattr(result, 'usage_metadata', None) or {}
            available = usage.available or {'input_tokens', 'output_tokens'} <= metadata.keys()
            metrics['input_tokens'] = metrics.get('input_tokens', 0) + (usage.input_tokens or metadata.get('input_tokens', 0) or 0)
            metrics['output_tokens'] = metrics.get('output_tokens', 0) + (usage.output_tokens or metadata.get('output_tokens', 0) or 0)
            metrics['model_ms'] = metrics.get('model_ms', 0) + round((perf_counter() - started) * 1000, 3)
            if not available:
                metrics['llm_usage_unknown_calls'] = metrics.get('llm_usage_unknown_calls', 0) + 1
            price = self.price
            if available and isinstance(price, dict) and all(type(price.get(k)) in (int, float) and math.isfinite(price[k]) and price[k] >= 0 for k in ('input_per_million', 'output_per_million')):
                cost = ((usage.input_tokens if usage.available else metadata['input_tokens']) * price['input_per_million']
                        + (usage.output_tokens if usage.available else metadata['output_tokens']) * price['output_per_million']) / 1e6
                metrics['llm_cost'] = metrics.get('llm_cost', 0) + cost
            else:
                metrics['llm_cost_unknown_calls'] = metrics.get('llm_cost_unknown_calls', 0) + 1


class MeasuredModels:
    def __init__(self, models):
        self.models = models
        from agentic.observability.settings import ObservabilitySettings
        self.prices = ObservabilitySettings().LANGSMITH_MODEL_PRICES

    def get(self, role):
        model = self.models.get(role)
        metadata = getattr(model, 'metadata', None) or {}
        price = self.prices.get(f"{metadata.get('hercfit_provider')}/{metadata.get('ls_model_name')}")
        return _MeasuredModel(model, price)
