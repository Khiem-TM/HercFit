"""Benchmark tải tất định: graph thật với model kịch bản và backend cô lập ở nhiều mức đồng thời.

Đo phần điều phối của HercFit (định tuyến, luật code, cổng xác nhận, checkpoint trong bộ nhớ) dưới tải, KHÔNG gồm
độ trễ model hay backend thật — số đo model thật thuộc `system_benchmark` (cần credit). Mỗi lượt còn được kiểm tra
cô lập người dùng (lệnh ghi đúng chủ) để tải không che lỗi tương tranh.
"""

import asyncio
import gc
import tracemalloc
from time import perf_counter
from uuid import uuid4

from evaluation import contracts, scoring
from evaluation.adapters.graph_runtime import GraphRuntimeAdapter
from evaluation.contracts import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationScore,
    RunMetadata,
)

VERSION = "perf-1.0"
LEVELS = (1, 8, 32)
TURNS_PER_LEVEL = 64


def _case(index):
    user = f"u-eval-{1 + index % 4}"
    meal = {
        "name": "Bữa sáng",
        "consumed_at": "2026-11-02T07:30:00+07:00",
        "items": [{"food": "bánh bao nhân thịt", "quantity": 1, "unit": "SERVING"}],
    }
    return EvaluationCase(
        id=f"load-{index}",
        suite="performance",
        input={
            "user_id": user,
            "turns": [{"message": "Sáng nay tôi ăn 1 bánh bao nhân thịt", "mode": "normal"}],
            "confirm": "approve",
            "script": {
                "decision": [
                    {
                        "intent": "LOG_FOOD",
                        "next_agent": "tool",
                        "domain": "meals",
                        "action": "tool",
                        "instruction": "Ghi bữa.",
                        "meal_log": [meal],
                    }
                ]
            },
        },
    )


async def level(concurrency, turns=TURNS_PER_LEVEL):
    adapter = GraphRuntimeAdapter()
    gate = asyncio.Semaphore(concurrency)
    latencies, isolated, errors = [], [], 0

    async def one(index):
        nonlocal errors
        case = _case(index)
        async with gate:
            started = perf_counter()
            record = await adapter.run(case)
            latencies.append((perf_counter() - started) * 1000)
        errors += bool(record.errors) or record.status != "completed"
        isolated.append(record.verified_state.get("users_written") == [case.input["user_id"]])

    gc.collect()
    tracemalloc.start()
    started = perf_counter()
    await asyncio.gather(*(one(i) for i in range(turns)))
    wall = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "concurrency": concurrency,
        "turns": turns,
        "wall_s": round(wall, 3),
        "throughput_tps": round(turns / wall, 2),
        "errors": errors,
        "isolation_rate": scoring.rate(isolated),
        "peak_traced_mb": round(peak / 2**20, 2),
        **scoring.latency_summary(latencies),
    }


async def benchmark(levels=LEVELS, turns=TURNS_PER_LEVEL):
    from evaluation.runner import git_state

    rows = [await level(c, turns) for c in levels]
    sha, dirty = git_state()
    dataset = contracts.dataset_info(
        "synthetic_load", [{"levels": list(levels), "turns": turns}], version=VERSION
    )
    results = []
    for row in rows:
        case = EvaluationCase(
            id=f"c{row['concurrency']}",
            suite="performance",
            input={"concurrency": row["concurrency"]},
        )
        scores = [
            EvaluationScore(
                case_id=case.id,
                name="load_isolation",
                value=row["isolation_rate"] == 1.0,
                data_type="BOOLEAN",
                passed=row["isolation_rate"] == 1.0,
                gate="hard_safety",
                evaluator="performance",
                evaluator_version=VERSION,
            ),
            EvaluationScore(
                case_id=case.id,
                name="load_error_free",
                value=row["errors"] == 0,
                data_type="BOOLEAN",
                passed=row["errors"] == 0,
                evaluator="performance",
                evaluator_version=VERSION,
            ),
        ]
        results.append(
            CaseResult(
                case=case, record={**row, "latency_ms": row["latency_p95_ms"]}, scores=scores
            )
        )
    run = EvaluationRun(
        metadata=RunMetadata(
            experiment_id=uuid4().hex,
            experiment_name="performance-deterministic",
            suite="performance",
            mode="deterministic",
            dataset=dataset,
            git_sha=sha,
            git_dirty=dirty,
            started_at=contracts.now(),
            finished_at=contracts.now(),
            models={"all_roles": "scripted"},
            evaluator_versions={"performance": VERSION},
            notes=[
                "Graph thật, model kịch bản, backend cô lập: đo điều phối, không gồm độ trễ model/backend."
            ],
        ),
        results=results,
        analyses={"levels": rows},
    )
    return run
