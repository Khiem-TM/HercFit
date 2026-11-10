"""Luật cảnh báo trên số đo vận hành (`/health/metrics`) và báo cáo eval, theo cửa sổ, không cảnh báo theo request.

    python -m agentic.observability.alerts --url http://agentic:8081/health/metrics --state /var/tmp/hercfit-alerts.json
    python -m agentic.observability.alerts --snapshot metrics.json        # kiểm tra một ảnh chụp
    python -m agentic.observability.alerts --reports eval_results/quality  # thêm cảnh báo hồi quy eval

Bộ đếm là luỹ kế từ lúc tiến trình khởi động; với `--state` bộ kiểm tra so với lần chạy trước để tính trên cửa sổ
(chạy theo cron, ví dụ mỗi 5 phút). Mỗi luật có ngưỡng tối thiểu về lưu lượng để không báo động với vài request.
Mã thoát: 0 không có cảnh báo, 1 có cảnh báo `warning`, 2 có cảnh báo `critical`. Ngưỡng là đề xuất ban đầu (chưa có
dữ liệu production để hiệu chỉnh) và được ghi kèm căn cứ trong `RULES`; hiệu chỉnh lại sau 2 tuần dữ liệu thật.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

RULES = [
    {
        "name": "chat_failure_rate",
        "severity": "warning",
        "threshold": 0.05,
        "min_volume": 20,
        "why": "≥5% phiên chat kết thúc failed/timeout trong cửa sổ (gồm lỗi SSE sau HTTP 200).",
    },
    {
        "name": "chat_failure_rate",
        "severity": "critical",
        "threshold": 0.15,
        "min_volume": 20,
        "why": "≥15%: phần lớn người dùng thấy lỗi.",
    },
    {
        "name": "sse_failure_rate",
        "severity": "warning",
        "threshold": 0.05,
        "min_volume": 20,
        "why": "Riêng /chat/stream: lỗi sau khi stream đã mở không hiện trong mã HTTP.",
    },
    {
        "name": "ttft_p95_ms",
        "severity": "warning",
        "threshold": 10000,
        "min_volume": 20,
        "why": "Token đầu sau 10 s (p95): người dùng thấy treo; RESPONSE_TIMEOUT là 60–90 s.",
    },
    {
        "name": "chat_duration_p95_ms",
        "severity": "warning",
        "threshold": 60000,
        "min_volume": 20,
        "why": "Lượt chat p95 > 60 s, gần ngân sách thời gian của lượt.",
    },
    {
        "name": "provider_retry_exhausted",
        "severity": "critical",
        "threshold": 5,
        "min_volume": 0,
        "why": "≥5 lời gọi model hết mọi lần thử (kể cả dự phòng) trong cửa sổ.",
    },
    {
        "name": "provider_rate_limited",
        "severity": "warning",
        "threshold": 10,
        "min_volume": 0,
        "why": "≥10 lần 429 từ nhà cung cấp model trong cửa sổ.",
    },
    {
        "name": "tool_backend_error_rate",
        "severity": "warning",
        "threshold": 0.10,
        "min_volume": 20,
        "why": "≥10% lời gọi tool lỗi ở backend.",
    },
    {
        "name": "worker_failures",
        "severity": "warning",
        "threshold": 3,
        "min_volume": 0,
        "why": "≥3 lỗi vòng lặp nền (đối soát KG, xoá theo consent, dọn bộ nhớ) trong cửa sổ.",
    },
    {
        "name": "worker_stalled_seconds",
        "severity": "critical",
        "threshold": 900,
        "min_volume": 0,
        "why": "Worker nền không có lần thành công trong 15 phút (chu kỳ đối soát mặc định ngắn hơn nhiều).",
    },
    {
        "name": "telemetry_export_errors",
        "severity": "warning",
        "threshold": 1,
        "min_volume": 0,
        "why": "Lỗi gửi/bỏ span: trace có thể thiếu; không có lỗi cũng không chứng minh đã nhận đủ.",
    },
    {
        "name": "eval_regression",
        "severity": "critical",
        "threshold": 1,
        "min_volume": 0,
        "why": "Lần eval mới nhất của một bộ trượt cổng (an toàn cứng, chất lượng hoặc hồi quy baseline).",
    },
]


def _sum(snapshot, name, **match):
    return sum(
        row["value"]
        for row in snapshot.get("counters", {}).get(name, [])
        if all(row["labels"].get(k) == str(v) for k, v in match.items())
    )


def _hist(snapshot, name, **match):
    rows = [
        row
        for row in snapshot.get("histograms", {}).get(name, [])
        if all(row["labels"].get(k) == str(v) for k, v in match.items())
    ]
    if not rows:
        return [0] * (len(snapshot.get("bucket_bounds_ms", [])) + 1)
    return [sum(values) for values in zip(*(row["buckets"] for row in rows))]


def delta(current, previous):
    """Ảnh chụp chỉ gồm phần tăng từ lần trước (tiến trình khởi động lại thì dùng luỹ kế mới)."""
    if not previous or previous.get("since") != current.get("since"):
        return current
    out = {**current, "counters": {}, "histograms": {}}
    for name, rows in current.get("counters", {}).items():
        before = {
            json.dumps(r["labels"], sort_keys=True): r["value"]
            for r in previous["counters"].get(name, [])
        }
        out["counters"][name] = [
            {**r, "value": r["value"] - before.get(json.dumps(r["labels"], sort_keys=True), 0)}
            for r in rows
        ]
    for name, rows in current.get("histograms", {}).items():
        before = {
            json.dumps(r["labels"], sort_keys=True): r["buckets"]
            for r in previous["histograms"].get(name, [])
        }
        out["histograms"][name] = [
            {
                **r,
                "buckets": [
                    a - b
                    for a, b in zip(
                        r["buckets"],
                        before.get(
                            json.dumps(r["labels"], sort_keys=True), [0] * len(r["buckets"])
                        ),
                    )
                ],
            }
            for r in rows
        ]
    return out


def percentile(counts, bounds, q):
    total = sum(counts)
    if not total:
        return None
    seen = 0
    for index, count in enumerate(counts):
        seen += count
        if seen >= q * total:
            return float(bounds[index]) if index < len(bounds) else float("inf")
    return float("inf")


def signals(window, *, now=None, reports=()):
    now = now or time.time()
    bounds = window.get("bucket_bounds_ms", [])
    sessions = _sum(window, "chat_sessions_total")
    failed = _sum(window, "chat_sessions_total", outcome="failed") + _sum(
        window, "chat_sessions_total", outcome="timeout"
    )
    stream = _sum(window, "chat_sessions_total", endpoint="stream")
    stream_failed = _sum(window, "chat_sessions_total", endpoint="stream", outcome="failed") + _sum(
        window, "chat_sessions_total", endpoint="stream", outcome="timeout"
    )
    tools = _sum(window, "tool_calls_total")
    stalled = [
        now - row["value"] for row in window.get("gauges", {}).get("worker_last_success_ts", [])
    ]
    return {
        "chat_failure_rate": (failed / sessions if sessions else None, sessions),
        "sse_failure_rate": (stream_failed / stream if stream else None, stream),
        "ttft_p95_ms": (
            percentile(_hist(window, "chat_ttft_ms"), bounds, 0.95),
            sum(_hist(window, "chat_ttft_ms")),
        ),
        "chat_duration_p95_ms": (
            percentile(_hist(window, "chat_duration_ms"), bounds, 0.95),
            sum(_hist(window, "chat_duration_ms")),
        ),
        "provider_retry_exhausted": (_sum(window, "llm_retry_exhausted_total"), 0),
        "provider_rate_limited": (_sum(window, "llm_attempt_errors_total", kind="rate_limit"), 0),
        "tool_backend_error_rate": (
            _sum(window, "tool_calls_total", outcome="backend_error") / tools if tools else None,
            tools,
        ),
        "worker_failures": (_sum(window, "worker_failures_total"), 0),
        "worker_stalled_seconds": (max(stalled) if stalled else None, 0),
        "telemetry_export_errors": (
            _sum(window, "telemetry_export_errors_total")
            + _sum(window, "telemetry_spans_dropped_total"),
            0,
        ),
        "eval_regression": (
            sum(1 for r in reports if r.get("status") in {"fail", "safety_fail", "error"}),
            0,
        ),
    }


def evaluate(window, *, reports=(), now=None):
    values = signals(window, now=now, reports=reports)
    firing = []
    for rule in RULES:
        value, volume = values[rule["name"]]
        if value is None or volume < rule["min_volume"]:
            continue
        if value >= rule["threshold"]:
            firing.append(
                {
                    **rule,
                    "value": round(value, 4) if isinstance(value, float) else value,
                    "volume": volume,
                }
            )
    # Một tên luật chỉ báo ở mức nặng nhất.
    worst = {}
    for alert in firing:
        if alert["name"] not in worst or alert["severity"] == "critical":
            worst[alert["name"]] = alert
    return list(worst.values())


def latest_reports(folder):
    latest = {}
    for path in sorted(Path(folder).glob("*/report.json")):
        data = json.loads(path.read_text())
        meta = data.get("metadata") or {}
        latest[(meta.get("suite") or data.get("suite"), meta.get("mode") or data.get("mode"))] = (
            data
        )
    return [r for r in latest.values() if r.get("status") != "blocked"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url")
    parser.add_argument("--snapshot")
    parser.add_argument("--state")
    parser.add_argument("--reports")
    args = parser.parse_args(argv)
    if args.url:
        with urllib.request.urlopen(args.url, timeout=10) as response:  # noqa: S310 - URL nội bộ do operator đặt
            current = json.loads(response.read())
    elif args.snapshot:
        current = json.loads(Path(args.snapshot).read_text())
    else:
        current = {"counters": {}, "histograms": {}, "gauges": {}}
    previous = (
        json.loads(Path(args.state).read_text())
        if args.state and Path(args.state).exists()
        else None
    )
    window = delta(current, previous)
    reports = latest_reports(args.reports) if args.reports else []
    alerts = evaluate(window, reports=reports)
    if args.state:
        Path(args.state).write_text(json.dumps(current))
    print(json.dumps({"alerts": alerts, "checked_rules": len(RULES)}, ensure_ascii=False, indent=2))
    if any(a["severity"] == "critical" for a in alerts):
        return 2
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
