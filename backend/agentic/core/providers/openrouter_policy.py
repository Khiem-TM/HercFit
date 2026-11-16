"""OpenRouter model contract shared by runtime, catalog and isolated evaluation.

Only standard-library imports: the Ragas environment must not import LangChain.
Endpoint tags and price snapshots were checked on 2026-11-16. Prices are estimates,
never a substitute for the billed usage.cost returned by OpenRouter.
"""

from copy import deepcopy

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
SMALL_MODEL = "google/gemma-4-26b-a4b-it"
VISION_MODEL = "google/gemma-4-31b-it"
JUDGE_MODEL = "meta-llama/llama-3.3-70b-instruct"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
RERANK_MODEL = "cohere/rerank-v3.5"
AGENT_MODELS = {
    "nutrition": SMALL_MODEL,
    "memory": SMALL_MODEL,
    "body_health": VISION_MODEL,
    "clarify": VISION_MODEL,
    "context": VISION_MODEL,
}
ENDPOINTS = {
    # DeepInfra dropped 2026-11-16: 23/64 forced RouteDecision calls came back with empty tool arguments
    # (Fireworks 47/48, Azure 23/24). Hosts without forced tool_choice (Parasail, GMI, SiliconFlow) 404.
    DEFAULT_MODEL: ["fireworks", "azure/us"],
    SMALL_MODEL: ["primeintellect/bf16", "deepinfra/fp8"],
    VISION_MODEL: ["novita/bf16", "deepinfra/fp8"],
    JUDGE_MODEL: ["akashml/fp8"],
    EMBEDDING_MODEL: ["deepinfra/fp32"],
    RERANK_MODEL: ["cohere"],
}


def provider_options(model):
    """Fail explicitly for an unreviewed model; never silently select a new host."""
    if model not in ENDPOINTS:
        raise ValueError("Model has no reviewed OpenRouter endpoint policy")
    endpoints = list(ENDPOINTS[model])
    return {
        "order": endpoints,
        "only": endpoints,
        "allow_fallbacks": len(endpoints) > 1,
        "require_parameters": True,
    }


def chat_options(model, *, catalog=False):
    body = {"provider": provider_options(model)}
    if model == DEFAULT_MODEL:
        body["reasoning"] = {"effort": "none" if catalog else "high"}
    elif model in {SMALL_MODEL, VISION_MODEL}:
        body["reasoning"] = {"enabled": False}
    return deepcopy(body)


def response_metadata(data):
    """Keep only billing/routing metadata, never response content or credentials."""
    usage = data.get("usage") or {}
    return {
        key: value
        for key, value in {
            "openrouter_generation_id": data.get("id"),
            "openrouter_model": data.get("model"),
            "openrouter_provider": data.get("provider"),
            "openrouter_cost": usage.get("cost"),
        }.items()
        if value is not None
    }
