"""Content-free model/node measurements; no prompts, completions, or credentials."""
from contextvars import ContextVar
from time import perf_counter
from langchain_core.callbacks import BaseCallbackHandler

active_metrics = ContextVar('agent_node_metrics', default=None)


class _Usage(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

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
        self.input_tokens += usage.get('input_tokens', usage.get('prompt_tokens', 0)) or 0
        self.output_tokens += usage.get('output_tokens', usage.get('completion_tokens', 0)) or 0


class _MeasuredModel:
    def __init__(self, model):
        self.model = model

    def with_structured_output(self, *args, **kwargs):
        return _MeasuredModel(self.model.with_structured_output(*args, **kwargs))

    def bind_tools(self, *args, **kwargs):
        return _MeasuredModel(self.model.bind_tools(*args, **kwargs))

    async def ainvoke(self, messages, **kwargs):
        metrics = active_metrics.get()
        if metrics is None:
            return await self.model.ainvoke(messages, **kwargs)
        usage = _Usage()
        config = dict(kwargs.pop('config', {}) or {})
        config['callbacks'] = [*(config.get('callbacks') or []), usage]
        started = perf_counter()
        metrics['llm_calls'] = metrics.get('llm_calls', 0) + 1
        result = None
        try:
            result = await self.model.ainvoke(messages, config=config, **kwargs)
            return result
        finally:
            metadata = getattr(result, 'usage_metadata', None) or {}
            metrics['input_tokens'] = metrics.get('input_tokens', 0) + (usage.input_tokens or metadata.get('input_tokens', 0) or 0)
            metrics['output_tokens'] = metrics.get('output_tokens', 0) + (usage.output_tokens or metadata.get('output_tokens', 0) or 0)
            metrics['model_ms'] = metrics.get('model_ms', 0) + round((perf_counter() - started) * 1000, 3)


class MeasuredModels:
    def __init__(self, models):
        self.models = models

    def get(self, role):
        return _MeasuredModel(self.models.get(role))
