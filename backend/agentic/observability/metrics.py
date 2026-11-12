"""Số đo vận hành trong tiến trình: bộ đếm và histogram có nhãn giới hạn, không chứa nội dung hay định danh.

Mỗi tiến trình giữ bộ số riêng (giống `core.route_metrics`); `/health/metrics` trả ảnh chụp để bộ kiểm tra
cảnh báo (`agentic.observability.alerts`) hoặc hệ thống giám sát bên ngoài đọc. Nhãn chỉ nhận giá trị từ tập
hữu hạn (kết cục, lớp lỗi, tên tool trong registry, vai trò model); khi một metric vượt `MAX_SERIES` tổ hợp
nhãn, tổ hợp mới được gộp vào nhãn `other` để không bùng nổ cardinality. Ghi số không bao giờ làm hỏng request.
"""

import threading
import time
from collections import defaultdict

# Cận trên (ms). Chat và model chậm hơn API thường nên cần dải tới 2 phút.
BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000, 120000)
MAX_SERIES = 200
OVERFLOW = "other"

_lock = threading.Lock()
_counters: dict[str, dict[tuple, float]] = defaultdict(dict)
_histograms: dict[str, dict[tuple, list[int]]] = defaultdict(dict)
_sums: dict[str, dict[tuple, float]] = defaultdict(dict)
_gauges: dict[str, dict[tuple, float]] = defaultdict(dict)
_started = time.time()


def _key(store, name, labels):
    key = tuple(sorted((k, str(v)) for k, v in labels.items() if v is not None))
    series = store[name]
    if key not in series and len(series) >= MAX_SERIES:
        return tuple((k, OVERFLOW) for k, _ in key)
    return key


def incr(name, value=1, **labels):
    try:
        with _lock:
            key = _key(_counters, name, labels)
            _counters[name][key] = _counters[name].get(key, 0) + value
    except Exception:  # noqa: BLE001 - số đo không được làm hỏng luồng nghiệp vụ
        pass


def gauge(name, value, **labels):
    try:
        with _lock:
            _gauges[name][_key(_gauges, name, labels)] = value
    except Exception:  # noqa: BLE001
        pass


def bucket(value_ms):
    for index, bound in enumerate(BUCKETS_MS):
        if value_ms <= bound:
            return index
    return len(BUCKETS_MS)


def observe(name, value_ms, **labels):
    try:
        with _lock:
            key = _key(_histograms, name, labels)
            counts = _histograms[name].setdefault(key, [0] * (len(BUCKETS_MS) + 1))
            counts[bucket(value_ms)] += 1
            _sums[name][key] = _sums[name].get(key, 0.0) + value_ms
    except Exception:  # noqa: BLE001
        pass


def percentile(counts, q):
    """Cận trên của bucket chứa phân vị q; None khi chưa có mẫu, inf khi vượt cận cuối."""
    total = sum(counts)
    if not total:
        return None
    rank, seen = q * total, 0
    for index, count in enumerate(counts):
        seen += count
        if seen >= rank:
            return float(BUCKETS_MS[index]) if index < len(BUCKETS_MS) else float("inf")
    return float("inf")


def _labels(key):
    return dict(key)


def snapshot():
    """Ảnh chụp JSON: chỉ tên metric, nhãn hữu hạn và số."""
    with _lock:
        counters = {
            name: [{"labels": _labels(k), "value": v} for k, v in sorted(series.items())]
            for name, series in _counters.items()
        }
        gauges = {
            name: [{"labels": _labels(k), "value": v} for k, v in sorted(series.items())]
            for name, series in _gauges.items()
        }
        histograms = {}
        for name, series in _histograms.items():
            rows = []
            for key, counts in sorted(series.items()):
                count = sum(counts)
                rows.append(
                    {
                        "labels": _labels(key),
                        "count": count,
                        "sum_ms": round(_sums[name].get(key, 0.0), 3),
                        "buckets": list(counts),
                        "p50_ms": percentile(counts, 0.5),
                        "p95_ms": percentile(counts, 0.95),
                        "p99_ms": percentile(counts, 0.99),
                    }
                )
            histograms[name] = rows
    return {
        "since": _started,
        "bucket_bounds_ms": list(BUCKETS_MS),
        "counters": counters,
        "gauges": gauges,
        "histograms": histograms,
    }


def total(name, **match):
    """Tổng một bộ đếm trên các chuỗi có nhãn khớp `match` (dùng cho cảnh báo và test)."""
    with _lock:
        return sum(
            value
            for key, value in _counters.get(name, {}).items()
            if all(dict(key).get(k) == str(v) for k, v in match.items())
        )


def reset():
    global _started
    with _lock:
        for store in (_counters, _histograms, _sums, _gauges):
            store.clear()
        _started = time.time()
