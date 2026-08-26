"""Bounded, privacy-safe process metrics for protein import and conjugation."""

from __future__ import annotations

import math
import threading
from collections import Counter, deque
from copy import deepcopy

_MAX_RUNS = 512
_lock = threading.Lock()
_runs: deque[dict] = deque(maxlen=_MAX_RUNS)


def record_protein_process(operation: str, metrics: dict) -> None:
    """Record normalized timings/outcome without molecular or user content."""
    safe = {
        "operation": str(operation),
        "operation_id": str(metrics.get("operation_id") or ""),
        "outcome": str(metrics.get("outcome") or "unknown"),
        "total_ms": max(0.0, float(metrics.get("total_ms") or 0.0)),
        "stages_ms": {
            str(name): max(0.0, float(value))
            for name, value in (metrics.get("stages_ms") or {}).items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        },
    }
    with _lock:
        _runs.append(safe)


def clear_protein_process_metrics() -> None:
    with _lock:
        _runs.clear()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def protein_process_summary() -> dict:
    with _lock:
        runs = deepcopy(list(_runs))
    operations: dict[str, dict] = {}
    for operation in sorted({run["operation"] for run in runs}):
        selected = [run for run in runs if run["operation"] == operation]
        totals = [run["total_ms"] for run in selected]
        stage_names = sorted(
            {name for run in selected for name in run["stages_ms"]}
        )
        operations[operation] = {
            "run_count": len(selected),
            "outcomes": dict(sorted(Counter(run["outcome"] for run in selected).items())),
            "correlated_run_count": sum(bool(run["operation_id"]) for run in selected),
            "correlation_rate": round(
                sum(bool(run["operation_id"]) for run in selected) / len(selected), 4
            ),
            "total_ms": {
                "p50": _percentile(totals, 0.50),
                "p95": _percentile(totals, 0.95),
                "max": round(max(totals), 3),
            },
            "stages_ms": {
                name: {
                    "sample_count": sum(name in run["stages_ms"] for run in selected),
                    "p50": _percentile(
                        [run["stages_ms"][name] for run in selected if name in run["stages_ms"]],
                        0.50,
                    ),
                    "p95": _percentile(
                        [run["stages_ms"][name] for run in selected if name in run["stages_ms"]],
                        0.95,
                    ),
                }
                for name in stage_names
            },
        }
    return {
        "schema_version": 1,
        "retention_limit": _MAX_RUNS,
        "retained_run_count": len(runs),
        "operations": operations,
    }
