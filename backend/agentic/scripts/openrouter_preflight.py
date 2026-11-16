"""Read-only endpoint validation and opt-in paid probes on synthetic data.

python -m agentic.scripts.openrouter_preflight --env-file .cache/openrouter-migration/candidate.env
Add --live --allow-paid for small chat/tool/stream/image/embedding/rerank probes.
Only metadata is saved; no credentials, prompts, completions or raw errors.
"""

import argparse
import asyncio
import base64
import io
import json
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv

from agentic.core.providers.openrouter_policy import (
    DEFAULT_MODEL,
    EMBEDDING_MODEL,
    ENDPOINTS,
    JUDGE_MODEL,
    RERANK_MODEL,
    SMALL_MODEL,
    VISION_MODEL,
)


async def preflight(args):
    # Load the candidate overlay before any module creates runtime settings.
    if args.env_file:
        load_dotenv(args.env_file, override=True)
    from agentic.core.app.config import AgentSettings
    from agentic.core.providers.settings import OpenRouterSettings

    connection = OpenRouterSettings()
    key = connection.OPENROUTER_API_KEY
    if not key:
        raise ValueError("OPENROUTER_API_KEY is required")
    rows = []
    async with httpx.AsyncClient(base_url=connection.OPENROUTER_BASE_URL.rstrip("/") + "/",
                                headers={"Authorization": "Bearer " + key.get_secret_value()}, timeout=30) as http:
        response = await http.get("key")
        rows.append({"probe": "authentication", "ok": response.is_success, "http_status": response.status_code})
        response.raise_for_status()
        for model, allowed in ENDPOINTS.items():
            response = await http.get("models/" + model + "/endpoints")
            response.raise_for_status()
            endpoints = {e["tag"]: e for e in response.json()["data"]["endpoints"]}
            for tag in allowed:
                endpoint = endpoints.get(tag)
                tools = model not in {EMBEDDING_MODEL, RERANK_MODEL}
                supported = (endpoint or {}).get("supported_parameters") or []
                ok = endpoint is not None and (not tools or (
                    "tools" in supported and "tool_choice" in supported
                    and (endpoint.get("supports_tool_choice") or {}).get("function") is True
                ))
                rows.append({"probe": "endpoint", "model": model, "endpoint": tag, "ok": ok,
                             "pricing": (endpoint or {}).get("pricing"),
                             "context_length": (endpoint or {}).get("context_length")})
    if args.live:
        if not args.allow_paid:
            raise ValueError("Live probes require --allow-paid")
        from langchain_core.messages import HumanMessage
        from PIL import Image, ImageDraw
        from pydantic import BaseModel

        from agentic.core.llm import Models
        from agentic.embedding.core import EmbeddingClient, EmbeddingSettings, RerankClient

        class Number(BaseModel):
            number: int

        async def probe(name, action):
            started = perf_counter()
            try:
                result = await action()
                rows.append({"probe": name, "ok": bool(result), "duration_ms": round((perf_counter()-started)*1000)})
            except Exception as exc:
                rows.append({"probe": name, "ok": False, "error_type": type(exc).__name__,
                             "http_status": getattr(exc, "status_code", None),
                             "duration_ms": round((perf_counter()-started)*1000)})

        for model in (DEFAULT_MODEL, SMALL_MODEL, VISION_MODEL, JUDGE_MODEL):
            settings = AgentSettings(DEFAULT_MODEL=model, AGENT_MODELS={}, MODEL_MAX_RETRIES=0)
            models = Models(settings)
            async def tool_probe(models=models):
                output = await models.get("decision").with_structured_output(Number).ainvoke(
                    "Return the integer 7 using the Number tool."
                )
                return output.number == 7
            await probe("tool:" + model, tool_probe)
        models = Models(AgentSettings(AGENT_MODELS={}, MODEL_MAX_RETRIES=0))
        async def streaming():
            output = await models.get("response").ainvoke("Reply with exactly: hello")
            return bool(output.content) and bool(output.usage_metadata)
        await probe("stream", streaming)
        buffer = io.BytesIO()
        image = Image.new("RGB", (400, 150), "white")
        ImageDraw.Draw(image).text((30, 40), "WEIGHT: 150 g", fill="black", font_size=32)
        image.save(buffer, format="PNG")
        image_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        async def vision():
            model = Models(AgentSettings(DEFAULT_MODEL=VISION_MODEL, AGENT_MODELS={}, MODEL_MAX_RETRIES=0)).get("tool")
            output = await model.ainvoke([HumanMessage(content=[
                {"type": "text", "text": "What weight in grams is printed? Reply only with the number."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ])])
            return "150" in output.content
        await probe("vision-number", vision)
        config = EmbeddingSettings()
        embedding, reranker = EmbeddingClient(config), RerankClient(config)
        try:
            async def embed():
                vector = await embedding.embed(["Phục hồi sau chạy marathon"])
                return len(vector[0]) == 1024
            async def rerank():
                scores = await reranker.rerank("Marathon recovery", ["Rest after a marathon", "Making noodle soup"])
                return scores[0] > scores[1]
            await probe("embedding", embed)
            await probe("rerank", rerank)
        finally:
            await embedding.close()
            await reranker.close()
    return {"status": "pass" if all(r["ok"] for r in rows) else "fail", "checks": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--out", default="eval_results/openrouter-migration/preflight.json")
    args = parser.parse_args()
    try:
        result = asyncio.run(preflight(args))
    except Exception as exc:
        result = {"status": "blocked", "error_type": type(exc).__name__,
                  "http_status": getattr(getattr(exc, "response", None), "status_code", None)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
