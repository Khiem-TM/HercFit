"""Kiểm tra Jev tổng hợp có xác thực: python -m agentic.scripts.jev_preflight [--list-only]."""

import argparse
import asyncio
import json

from agentic.core.app.config import AgentSettings, agent_settings
from agentic.tools.integrations.jev import JevClient, JevError


def failure_report(exc):
    reason = exc.reason if isinstance(exc, JevError) else "invalid_configuration"
    result = {"status": "error", "reason": reason}
    hints = {
        "http_401": "Gateway rejected authentication. Check JEV_API_KEY is a valid, unexpired virtual key for JEV_GATEWAY_URL and has model access.",
        "http_403": "Gateway denied access. Check the virtual key permissions and allowed models.",
        "http_404": "Check JEV_GATEWAY_URL is the API base (including /v1 when required), not the systemone endpoint.",
        "invalid_configuration": "Check JEV_GATEWAY_URL, JEV_API_KEY and JEV_MODEL. Set a known deployment ID or use --list-only to discover it before enabling JEV_MODE.",
    }
    if reason in hints:
        result["hint"] = hints[reason]
    return result


async def preflight(settings: AgentSettings, *, list_only=False, client=None):
    settings.check_jev(require_model=not list_only)
    owned = client is None
    client = client or JevClient(settings)
    try:
        if list_only:
            return {"status": "ok", "models": await client.models()}
        # Lời gọi là căn cứ có thẩm quyền: khoá có phạm vi có thể gọi một deployment
        # mà không được phép liệt kê danh sách model của gateway.
        result = await client.evaluate(
            {"colour": "blue"},
            {
                "colour": {
                    "type": "choice",
                    "instructions": "Select the colour explicitly given in state.",
                    "criteria": {"blue": "The state says blue.", "red": "The state says red."},
                },
                "is_blue": {
                    "type": "noul",
                    "instructions": "Does the state explicitly say the colour is blue?",
                },
            },
            settings.JEV_MODEL,
        )
        answers = result["answers"]
        if answers["colour"]["choice"] != "blue" or answers["is_blue"]["noul"] < 0.9:
            raise JevError("synthetic_check_failed")
        return {
            "status": "ok",
            "configured_model": settings.JEV_MODEL,
            "resolved_model": result["model"],
            "usage": result["usage"],
            "cost": result["cost"],
        }
    finally:
        if owned:
            await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List models accessible with the configured virtual key.",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(preflight(agent_settings, list_only=args.list_only))
    except (JevError, ValueError) as exc:
        print(json.dumps(failure_report(exc)))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
