"""Cross-engine comparison — REST surface for the S5 "Shape comparison" card.

Assembles one comparison report (:func:`backend.core.shape_compare.build_comparison_report`)
from the per-engine source bundles the caller supplies — each engine's shape descriptors,
RMSF profile, relaxed frame, and optional field-response — and scores their agreement using
the shared-metric math (S1–S4).  The card renders the scalar table, RMSF overlay, agreement
scores, and field panel from it, and exports PNG/CSV.

Mirrors ``routes_oxdna_metrics``' background daemon-thread registry (``POST …/start`` →
``{metrics_id}``; ``GET …/{run_id}`` for progress + result) so the card drives the same
loading bar and so the per-engine tasks (O1/C5/M5/N4) can later make the source-gathering
step genuinely slow (reading each engine's trajectory) without changing the card.  For now
the sources are posted pre-computed, so the compute itself is instant.  Registered in
``backend/api/main.py``.  Every input here is Physical-layer only (Three-Layer Law).
"""

from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["shape-metrics"])

# In-memory registry of comparison runs, polled by the card (mirrors routes_oxdna_metrics).
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()


class CompareStartRequest(BaseModel):
    #: Per-engine source bundles: ``{engine, descriptors?, rmsf?, shape_frame?, field?}``.
    #: The per-engine emission tasks (O1/C5/M5/N4) produce these for the current design.
    sources: list[dict] = Field(default_factory=list)


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _compute(run_id: str, sources: list[dict]) -> None:
    from backend.core.shape_compare import build_comparison_report

    try:
        report = build_comparison_report(sources)
        _set(run_id, state="done", progress=1.0, result=report)
    except Exception as exc:  # surface any failure to the poller
        _set(run_id, state="error", error=str(exc))


@router.post("/shape/compare/start")
def start_compare(req: CompareStartRequest) -> dict:
    """Launch a cross-engine comparison over the supplied per-engine source bundles.
    Returns ``{metrics_id}``; poll ``GET /shape/compare/{id}`` for the assembled report."""
    run_id = uuid.uuid4().hex[:12]
    _set(run_id, state="running", progress=0.0, result=None, error=None)
    threading.Thread(
        target=_compute, args=(run_id, list(req.sources)), daemon=True
    ).start()
    return {"metrics_id": run_id, "state": "running"}


@router.get("/shape/compare/{run_id}")
def get_compare(run_id: str) -> dict:
    """Progress + result of a comparison run: ``{state, progress, result?, error?}``.
    ``state`` is ``running`` | ``done`` | ``error``; ``result`` (on done) is the
    :func:`build_comparison_report` payload (scalar table, RMSF profiles, agreement,
    field panel)."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no comparison run {run_id!r}")
        return {"metrics_id": run_id, **run}
