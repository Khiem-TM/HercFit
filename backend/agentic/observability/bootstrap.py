"""Kiểm tra cấu hình và trace tổng hợp cho operator; không bao giờ dùng nội dung chat thật.

python -m agentic.observability.bootstrap --check   # cấu hình + xác thực key, không in secret
python -m agentic.observability.bootstrap --smoke   # gửi trace giả, flush, đọc lại từ Langfuse
"""

import argparse
import asyncio
import json
import sys
import time

from agentic.observability.settings import ObservabilitySettings

SYNTHETIC_EMAIL = "synthetic@example.test"
SYNTHETIC_NAME = "Synthetic Person"


async def smoke(config):
    from agentic.observability.langfuse_adapter import Observer, current, identify, outcome, span

    manager = Observer(config)
    if not manager.client:
        raise RuntimeError("Tracing đang tắt hoặc thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY")
    with manager.request("smoke.synthetic", "operator") as state:
        identify("synthetic-user", "synthetic-session", (SYNTHETIC_NAME,))
        with span(
            "synthetic.tool",
            "tool",
            inputs={
                "weight_kg": 62.5,
                "email": SYNTHETIC_EMAIL,
                "note": f"{SYNTHETIC_NAME} nặng 62 kg, mail {SYNTHETIC_EMAIL}",
            },
        ) as run:
            if run:
                run.end(outputs={"ok": True})
        outcome("completed")
        trace_id = state.trace_id
    assert current.get() is None
    client = manager.client
    await manager.close()
    return client, trace_id


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    config = ObservabilitySettings()
    # Secret bí danh/lan truyền được suy ra từ secret key khi chưa đặt (settings.py).
    missing = [
        name for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not getattr(config, name)
    ]
    print(
        json.dumps(
            {
                "enabled": config.enabled,
                "configured": config.configured,
                "base_url": config.LANGFUSE_BASE_URL,
                "environment": config.LANGFUSE_TRACING_ENVIRONMENT,
                "capture_mode": config.LANGFUSE_CAPTURE_MODE,
                "sample_rate": config.LANGFUSE_SAMPLE_RATE,
                "secrets": config.secret_sources,
                "missing": missing,
            }
        )
    )
    if (args.check or args.smoke) and missing:
        sys.exit(
            "Đặt LANGFUSE_PUBLIC_KEY và LANGFUSE_SECRET_KEY (backend/.env hoặc agentic/.env) trước; không dán secret vào log."
        )
    if args.check:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY.get_secret_value(),
            base_url=config.LANGFUSE_BASE_URL,
            tracing_enabled=False,
        )
        print(json.dumps({"auth_ok": bool(client.auth_check())}))
    if args.smoke:
        if not config.enabled:
            sys.exit("Đặt LANGFUSE_TRACING=true để chạy smoke.")
        client, trace_id = asyncio.run(smoke(config))
        # Chỉ báo thành công khi đọc lại được từ Langfuse, không phải chỉ vì đã xếp hàng.
        observations = []
        for attempt in range(15):
            observations = client.api.observations.get_many(
                trace_id=trace_id, fields="core,basic,io"
            ).data
            if len(observations) >= 2:
                break
            time.sleep(3)
        if not observations:
            sys.exit(f"Không đọc lại được trace {trace_id} sau 45 s.")
        exported = json.dumps(
            [o.dict() if hasattr(o, "dict") else o for o in observations],
            default=str,
            ensure_ascii=False,
        )
        leaked = [
            value
            for value in (SYNTHETIC_EMAIL, SYNTHETIC_NAME, "synthetic-user", "62 kg", "62.5")
            if value in exported
        ]
        print(
            json.dumps(
                {
                    "verified_trace_id": trace_id,
                    "observations": len(observations),
                    "leaked_values": leaked,
                    "url": f"{config.LANGFUSE_BASE_URL.rstrip('/')}/trace/{trace_id}",
                }
            )
        )
        if leaked:
            sys.exit("Dữ liệu tổng hợp không được che hết.")


if __name__ == "__main__":
    main()
