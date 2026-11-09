"""Số đo model/node không chứa nội dung; không có prompt, completion hay thông tin xác thực."""

import math
from contextvars import ContextVar
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler

from agentic.core import roster
from agentic.observability import graph_config

active_metrics = ContextVar("agent_node_metrics", default=None)


def record_jev_result(result):
    """Đo mọi lần thử qua gateway mà không giữ đầu vào hay câu trả lời."""
    metrics = active_metrics.get()
    if metrics is None:
        return
    keys = (
        "evaluation_id",
        "phase",
        "status",
        "reason",
        "model",
        "usage",
        "cost",
        "duration_ms",
        "policy_version",
        "cached",
        "mode",
        "enforced",
        "attempted",
    )
    metrics.setdefault("jev_events", []).append({k: result[k] for k in keys if k in result})
    from agentic.observability import annotate

    annotate(
        jev_mode=result.get("mode"),
        jev_phase=result.get("phase"),
        jev_status=result.get("status"),
        jev_fallback=result.get("reason"),
        jev_model=result.get("model"),
        jev_policy_version=result.get("policy_version"),
        jev_attempted=result.get("attempted", False),
        jev_cost=result.get("cost"),
        jev_input_tokens=(result.get("usage") or {}).get("input_tokens"),
        jev_output_tokens=(result.get("usage") or {}).get("output_tokens"),
        jev_confidence={
            k: v["confidence"] for k, v in result.get("answers", {}).items() if "confidence" in v
        },
        jev_probabilities={
            k: v["noul"] for k, v in result.get("answers", {}).items() if "noul" in v
        },
    )


def merge_retrieval(previous, current):
    """Mỗi lượt chạy một bản tóm tắt knowledge graph: trạng thái và miền mới nhất, đếm mọi lần thử.

    `status` và `duration_ms` giữ nghĩa một lần thử cho lần đọc mới nhất và
    tổng thời gian; `statuses` liệt kê từng lần thử theo thứ tự (có giới hạn)."""
    if not previous:
        return {
            **current,
            "attempts": current.get("attempts", 1),
            "statuses": list(current.get("statuses") or [current.get("status")]),
        }
    return {
        **previous,
        **current,
        "attempts": previous.get("attempts", 1) + current.get("attempts", 1),
        "duration_ms": round(previous.get("duration_ms", 0) + current.get("duration_ms", 0), 3),
        "statuses": [
            *(previous.get("statuses") or [previous.get("status")]),
            *(current.get("statuses") or [current.get("status")]),
        ][-6:],
    }


def merge_jev_metrics(telemetry, events):
    """Giữ chi phí shadow riêng biệt và không bao giờ tính số liệu cache hai lần."""
    for event in events:
        if event.get("cached"):
            telemetry["jev_cache_hits"] = telemetry.get("jev_cache_hits", 0) + 1
        if not event.get("attempted") or event.get("cached"):
            continue
        prefix = "jev_shadow_" if event.get("mode") == "shadow" else "jev_"
        telemetry[prefix + "calls"] = telemetry.get(prefix + "calls", 0) + 1
        telemetry[prefix + "ms"] = telemetry.get(prefix + "ms", 0) + event.get("duration_ms", 0)
        usage = event.get("usage")
        if usage is None:
            telemetry[prefix + "usage_unknown_calls"] = (
                telemetry.get(prefix + "usage_unknown_calls", 0) + 1
            )
        else:
            for key in ("input_tokens", "output_tokens"):
                telemetry[prefix + key] = telemetry.get(prefix + key, 0) + usage.get(key, 0)
        cost = event.get("cost")
        if cost is None:
            telemetry[prefix + "cost_unknown_calls"] = (
                telemetry.get(prefix + "cost_unknown_calls", 0) + 1
            )
        else:
            telemetry[prefix + "cost"] = telemetry.get(prefix + "cost", 0) + cost
    telemetry["total_input_tokens"] = telemetry.get("input_tokens", 0) + telemetry.get(
        "jev_input_tokens", 0
    )
    telemetry["total_output_tokens"] = telemetry.get("output_tokens", 0) + telemetry.get(
        "jev_output_tokens", 0
    )
    unknown = telemetry.get("llm_cost_unknown_calls", 0) + telemetry.get(
        "jev_cost_unknown_calls", 0
    )
    usage_unknown = telemetry.get("llm_usage_unknown_calls", 0) + telemetry.get(
        "jev_usage_unknown_calls", 0
    )
    telemetry["model_cost_status"] = "unknown" if unknown else "configured"
    telemetry["model_usage_status"] = "unknown" if usage_unknown else "reported"
    telemetry["total_model_cost"] = (
        None if unknown else telemetry.get("llm_cost", 0) + telemetry.get("jev_cost", 0)
    )


def merge_agents(previous, current):
    """Số đo theo agent của lượt chạy: lời gọi, token, thời gian model và số lần mỗi model thật sự trả lời."""
    merged = {
        name: {**entry, "models": dict(entry.get("models") or {})}
        for name, entry in (previous or {}).items()
    }
    for name, entry in (current or {}).items():
        total = merged.setdefault(name, {"models": {}})
        for key in ("llm_calls", "input_tokens", "output_tokens"):
            total[key] = total.get(key, 0) + entry.get(key, 0)
        total["model_ms"] = round(total.get("model_ms", 0) + entry.get("model_ms", 0), 3)
        for model, calls in (entry.get("models") or {}).items():
            total["models"][model] = total["models"].get(model, 0) + calls
    return merged


BRANCH_COUNTERS = (
    "llm_calls",
    "input_tokens",
    "output_tokens",
    "model_ms",
    "llm_cost",
    "llm_cost_unknown_calls",
    "llm_usage_unknown_calls",
)


def merge_branches(telemetry, branches, limit=60):
    """Gộp số đo của các nhánh agent chạy song song vào lượt chạy. `parallel` giữ thời gian thật (nhánh dài nhất)
    và tổng thời gian các nhánh, để thấy mức tăng tốc so với chạy tuần tự."""
    merged = dict(telemetry or {})
    durations = []
    for branch in branches:
        for key in BRANCH_COUNTERS:
            if key in branch:
                merged[key] = merged.get(key, 0) + branch[key]
        if branch.get("agents"):
            merged["agents"] = merge_agents(merged.get("agents"), branch["agents"])
        nodes = branch.get("nodes") or []
        merged["nodes"] = [
            *merged.get("nodes", []),
            *({**node, "parallel": True} for node in nodes),
        ][-limit:]
        durations.append(round(sum(node.get("duration_ms", 0) for node in nodes), 3))
    if durations:
        merged["parallel"] = {
            "tasks": len(durations),
            "wall_ms": max(durations),
            "sum_ms": round(sum(durations), 3),
        }
    merge_jev_metrics(merged, [])
    return merged


class _Usage(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.available = False
        # (provider, model) của lần gọi chat cuối: model thật sự trả lời khi model chính lỗi và dự phòng chạy.
        self.served = None

    def on_chat_model_start(self, serialized, messages, *, metadata=None, **kwargs):
        metadata = metadata or {}
        if metadata.get("hercfit_model"):
            self.served = (metadata.get("hercfit_provider"), metadata["hercfit_model"])

    def on_llm_end(self, response, **kwargs):
        usage = (response.llm_output or {}).get("token_usage", {})
        if not usage:
            for group in response.generations:
                for generation in group:
                    usage = (
                        getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                    )
                    if usage:
                        break
                if usage:
                    break
        if ("input_tokens" in usage or "prompt_tokens" in usage) and (
            "output_tokens" in usage or "completion_tokens" in usage
        ):
            self.available = True
        self.input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        self.output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0


class _MeasuredModel:
    def __init__(self, model, price=None, *, agent=None, prices=None):
        self.model = model
        self.price = price
        # Agent sở hữu lời gọi (core/roster.py) và bảng giá để tính phí theo model thật sự trả lời.
        self.agent, self.prices = agent, prices

    def _wrap(self, model):
        return _MeasuredModel(model, self.price, agent=self.agent, prices=self.prices)

    def with_structured_output(self, *args, **kwargs):
        return self._wrap(self.model.with_structured_output(*args, **kwargs))

    def bind_tools(self, *args, **kwargs):
        return self._wrap(self.model.bind_tools(*args, **kwargs))

    async def ainvoke(self, messages, **kwargs):
        metrics = active_metrics.get()
        if metrics is None:
            return await self.model.ainvoke(messages, **kwargs)
        usage = _Usage()
        from langchain_core.runnables.config import ensure_config

        config = ensure_config(kwargs.pop("config", None))
        callbacks = config.get("callbacks")
        if callbacks is not None and not isinstance(callbacks, list):
            callbacks = callbacks.copy()
            # RunnableSequence đầu ra có cấu trúc gọi LLM như một node con;
            # callback số liệu sử dụng của nó phải sống sót qua việc tạo callback manager con.
            callbacks.add_handler(usage, inherit=True)
        else:
            callbacks = [*(callbacks or []), usage]
        config["callbacks"] = callbacks
        if self.agent:
            config["metadata"] = {**(config.get("metadata") or {}), "agent": self.agent}
        started = perf_counter()
        metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
        result = None
        try:
            result = await self.model.ainvoke(messages, config=graph_config(config), **kwargs)
            return result
        finally:
            metadata = getattr(result, "usage_metadata", None) or {}
            available = usage.available or {"input_tokens", "output_tokens"} <= metadata.keys()
            input_tokens = usage.input_tokens or metadata.get("input_tokens", 0) or 0
            output_tokens = usage.output_tokens or metadata.get("output_tokens", 0) or 0
            elapsed = round((perf_counter() - started) * 1000, 3)
            metrics["input_tokens"] = metrics.get("input_tokens", 0) + input_tokens
            metrics["output_tokens"] = metrics.get("output_tokens", 0) + output_tokens
            metrics["model_ms"] = metrics.get("model_ms", 0) + elapsed
            if not available:
                metrics["llm_usage_unknown_calls"] = metrics.get("llm_usage_unknown_calls", 0) + 1
            if self.agent:
                entry = {
                    "llm_calls": 1,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model_ms": elapsed,
                    "models": {usage.served[1]: 1} if usage.served else {},
                }
                metrics["agents"] = merge_agents(metrics.get("agents"), {self.agent: entry})
            price = self.price
            if usage.served and self.prices is not None:
                # Model dự phòng (nâng cấp) trả lời thì tính theo giá của chính nó; chưa cấu hình giá là chưa biết.
                price = self.prices.get(f"{usage.served[0]}/{usage.served[1]}")
            if (
                available
                and isinstance(price, dict)
                and all(
                    type(price.get(k)) in (int, float) and math.isfinite(price[k]) and price[k] >= 0
                    for k in ("input_per_million", "output_per_million")
                )
            ):
                cost = (
                    (usage.input_tokens if usage.available else metadata["input_tokens"])
                    * price["input_per_million"]
                    + (usage.output_tokens if usage.available else metadata["output_tokens"])
                    * price["output_per_million"]
                ) / 1e6
                metrics["llm_cost"] = metrics.get("llm_cost", 0) + cost
            else:
                metrics["llm_cost_unknown_calls"] = metrics.get("llm_cost_unknown_calls", 0) + 1


class MeasuredModels:
    def __init__(self, models):
        self.models = models
        from agentic.observability.settings import ObservabilitySettings

        self.prices = ObservabilitySettings().MODEL_PRICES

    def get(self, role):
        model = self.models.get(role)
        metadata = getattr(model, "metadata", None) or {}
        price = self.prices.get(
            f"{metadata.get('hercfit_provider')}/{metadata.get('hercfit_model')}"
        )
        return _MeasuredModel(model, price, agent=roster.agent_for(role), prices=self.prices)
