"""Số đo thuần (không I/O): truy hồi Hit/Precision/Recall@K, MRR, nDCG; phân loại P/R/F1, macro-F1, ma trận nhầm;
phân vị độ trễ và tổng hợp token/chi phí. Dùng chung cho mọi bộ eval để định nghĩa số đo chỉ có một chỗ."""

import math
from collections import Counter


# ------------------------------------------------------------------------------------------- truy hồi
def hit_at_k(flags, k):
    return float(any(flags[:k]))


def precision_at_k(flags, k):
    top = flags[:k]
    return sum(top) / k if k else 0.0


def recall_at_k(found, total):
    """`found`: số mục liên quan (vd. khoảng trang kỳ vọng) xuất hiện trong top-K; `total`: số mục liên quan."""
    return found / total if total else 0.0


def reciprocal_rank(flags, k=None):
    for index, flag in enumerate(flags[:k] if k else flags, 1):
        if flag:
            return 1 / index
    return 0.0


def ndcg_at_k(flags, ideal, k):
    """nDCG nhị phân: `ideal` là số mục liên quan có thật trong kho (xếp hạng lý tưởng)."""
    dcg = sum(1 / math.log2(i + 1) for i, flag in enumerate(flags[:k], 1) if flag)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(k, ideal) + 1))
    return dcg / idcg if idcg else 0.0


def retrieval_metrics(flags, *, found, total, ideal, ks=(1, 3, 5, 10)):
    out = {}
    for k in ks:
        out[f"hit@{k}"] = hit_at_k(flags, k)
        out[f"precision@{k}"] = precision_at_k(flags, k)
    out["recall@5"] = recall_at_k(found, total)
    out["mrr@10"] = reciprocal_rank(flags, 10)
    out["ndcg@5"] = ndcg_at_k(flags, ideal, 5)
    return out


# ------------------------------------------------------------------------------------------- phân loại
def per_label(pairs):
    """`pairs`: [(tập nhãn kỳ vọng, tập nhãn dự đoán)] — nhãn đơn là tập một phần tử (multi-intent là nhiều)."""
    tp, fp, fn = Counter(), Counter(), Counter()
    labels = set()
    for expected, predicted in pairs:
        expected, predicted = set(expected), set(predicted)
        labels |= expected | predicted
        for label in expected & predicted:
            tp[label] += 1
        for label in predicted - expected:
            fp[label] += 1
        for label in expected - predicted:
            fn[label] += 1
    rows = {}
    for label in sorted(labels):
        p = tp[label] / (tp[label] + fp[label]) if tp[label] + fp[label] else 0.0
        r = tp[label] / (tp[label] + fn[label]) if tp[label] + fn[label] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows[label] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "support": tp[label] + fn[label],
        }
    return rows


def classification_summary(pairs):
    rows = per_label(pairs)
    supported = [row for row in rows.values() if row["support"]]
    exact = sum(set(e) == set(p) for e, p in pairs)
    return {
        "accuracy": round(exact / len(pairs), 4) if pairs else None,
        "macro_precision": round(sum(r["precision"] for r in supported) / len(supported), 4)
        if supported
        else None,
        "macro_recall": round(sum(r["recall"] for r in supported) / len(supported), 4)
        if supported
        else None,
        "macro_f1": round(sum(r["f1"] for r in supported) / len(supported), 4)
        if supported
        else None,
        "per_label": rows,
    }


def confusion_matrix(pairs):
    """Nhãn đơn: {'labels': [...], 'matrix': [[đếm]] với hàng = kỳ vọng, cột = dự đoán}."""
    labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for expected, predicted in pairs:
        matrix[index[expected]][index[predicted]] += 1
    return {"labels": labels, "matrix": matrix}


# ------------------------------------------------------------------------------------------- hiệu năng
def percentile(values, q):
    """Phân vị theo hạng gần nhất (cùng cách với các bộ eval cũ)."""
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))] if values else None


def latency_summary(values_ms):
    values = [v for v in values_ms if v is not None]
    return {
        "latency_p50_ms": percentile(values, 0.5),
        "latency_p95_ms": percentile(values, 0.95),
        "latency_p99_ms": percentile(values, 0.99),
        "latency_mean_ms": round(sum(values) / len(values), 3) if values else None,
    }


def usage_summary(usages):
    """Tổng token; chi phí chỉ có khi MỌI lần chạy có giá đã cấu hình (một lần chưa biết giá → tổng chưa biết)."""
    usages = list(usages)
    costs = [u.get("cost") for u in usages]
    known = (
        bool(usages)
        and all(c is not None for c in costs)
        and all(u.get("cost_status") == "configured" for u in usages)
    )
    return {
        "llm_calls": sum(u.get("llm_calls", 0) for u in usages),
        "llm_attempts": sum(u.get("llm_attempts", 0) for u in usages),
        "input_tokens": sum(u.get("input_tokens", 0) for u in usages),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usages),
        "cost": round(sum(costs), 6) if known else None,
        "cost_status": "configured" if known else "unknown",
    }


def rate(values):
    values = [bool(v) for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None
