"""Graphs & Metrics — REST surface for the MD (NAMD) "Graphs and Metrics" card.

The MD twin of :mod:`backend.api.routes_oxdna_metrics`: computes twist, curvature and
base-pairing over a NAMD run's DCD trajectory in ONE pass
(:func:`backend.core.md_trajectory.md_metric_series`) and serves them as both domains —
spatial (vs position along the bundle) and temporal (vs frame index) — for the graph
popups + PNG/CSV export.  ``scope="latest"`` measures a single job; ``scope="chain"``
measures the whole parent/child (refit) lineage, concatenating the temporal series
end-to-end and overlaying one spatial profile per job.

Reading + reconstructing DCD frames is the expensive part, so the work runs in a
background daemon thread with a pollable progress + ETA (identical registry pattern to
``routes_oxdna_metrics``); the card drives a per-metric loading bar off it.  Registered
in ``backend/api/main.py``.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.routes_md import (
    _load_job,
    _md_segment_dcds,
    _md_snapshot_design,
    _workspace,
)

router = APIRouter(tags=["md-metrics"])

# In-memory registry of metric-compute runs (one background pass each), polled by the card.
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()


class MdMetricsStartRequest(BaseModel):
    scope: str = "latest"      # "latest" (this job only) | "chain" (whole refit lineage)
    n_slices: int = 0          # 0 => auto (~1-turn slabs), matching the measure defaults


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _job_inputs(job, ws: Path):
    """(psf, ref_pdb, segments, design) for one MD job's composite, or None if it has no
    usable topology/trajectory yet.  Mirrors ``routes_md._md_traj_inputs`` but analyses
    the job's FROZEN ``design.json`` snapshot only (no active-design fallback — a metric
    run over a drifted/other design mis-maps P atoms and voids the result)."""
    from backend.api import state as design_state

    package_dir = job.package_dir(ws)
    psf = package_dir / f"{job.name_stem}.psf"
    ref = package_dir / f"{job.name_stem}.pdb"
    if not psf.exists() or not ref.exists():
        return None
    segments = _md_segment_dcds(job)
    if not segments:
        return None
    design = _md_snapshot_design(job)
    if design is None:
        # Legacy pre-snapshot job: fall back to the active design (best effort).
        try:
            design = design_state.get_or_404()
        except Exception:
            return None
    return psf, ref, segments, design


def _md_job_chain(job_id: str, all_jobs: list):
    """The whole refit lineage of ``job_id`` (root → every descendant, chronological),
    linked by ``MdJob.parent_job_id``.  Mirrors ``oxdna_job.resolve_job_chain``."""
    by_id = {j.job_id: j for j in all_jobs}
    anchor = by_id.get(job_id)
    if anchor is None:
        return []
    # Walk up to the root.
    root = anchor
    seen = {root.job_id}
    while getattr(root, "parent_job_id", None) and root.parent_job_id in by_id:
        root = by_id[root.parent_job_id]
        if root.job_id in seen:
            break
        seen.add(root.job_id)
    # Collect root + all descendants.
    kids: dict[str, list] = {}
    for j in all_jobs:
        pid = getattr(j, "parent_job_id", None)
        if pid:
            kids.setdefault(pid, []).append(j)
    chain: list = []
    stack = [root]
    visited: set[str] = set()
    while stack:
        j = stack.pop(0)
        if j.job_id in visited:
            continue
        visited.add(j.job_id)
        chain.append(j)
        stack.extend(sorted(kids.get(j.job_id, []), key=lambda x: x.created_at or 0))
    chain.sort(key=lambda x: x.created_at or 0)
    return chain


def _resolve_jobs(job_id: str, scope: str, ws: Path):
    """The chronological job list a metric run covers: just the anchor job (``latest``)
    or its whole refit lineage (``chain``)."""
    from backend.core.md_job import MdJob

    anchor = _load_job(job_id)
    if scope != "chain":
        return [anchor]
    chain = _md_job_chain(job_id, MdJob.list_jobs(ws))
    return chain or [anchor]


def _compute(run_id: str, job_id: str, req: MdMetricsStartRequest, ws: Path) -> None:
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.md_trajectory import count_md_frames, md_metric_series

    try:
        jobs = _resolve_jobs(job_id, req.scope, ws)
        inputs = [(j, _job_inputs(j, ws)) for j in jobs]
        inputs = [(j, io) for j, io in inputs if io is not None]
        if not inputs:
            _set(run_id, state="done", result={"ready": False,
                 "reason": "no NAMD trajectory yet for the selected job(s)"})
            return

        total = 0
        for _j, (_psf, _ref, segments, _d) in inputs:
            total += count_md_frames(segments)
        _set(run_id, frames_total=max(1, total), frames_done=0, progress=0.0, eta_s=None)

        started = time.time()
        done = {"n": 0}

        def _tick() -> None:
            done["n"] += 1
            elapsed = time.time() - started
            frac = done["n"] / max(1, total)
            eta = (elapsed / done["n"]) * (total - done["n"]) if done["n"] else None
            _set(run_id, frames_done=done["n"], progress=round(min(1.0, frac), 4),
                 eta_s=round(eta, 1) if eta is not None else None)

        # temporal series concatenate end-to-end; spatial profiles overlay one per job.
        twist_pf: list[float] = []
        curv_pf: list[float] = []
        bp_pf: list[float] = []
        boundaries: list[dict] = []
        per_job: list[dict] = []
        n_designed = 0
        for j, (psf, ref, segments, design) in inputs:
            analytic = core_reference_geometry(design)
            res = md_metric_series(psf, segments, ref, design, analytic,
                                   n_slices=req.n_slices, on_frame=_tick)
            if not res.get("ready"):
                continue
            boundaries.append({"job_id": j.job_id, "start_frame": len(twist_pf),
                               "n_frames": res["n_frames"]})
            twist_pf.extend(res["twist"]["temporal"]["per_frame"])
            curv_pf.extend(res["curvature"]["temporal"]["per_frame"])
            bp_pf.extend(res["base_pairing"]["temporal"]["per_frame"])
            n_designed = max(n_designed, res["base_pairing"]["temporal"]["n_designed"])
            per_job.append({
                "job_id": j.job_id,
                "twist_spatial": res["twist"]["spatial"],
                "curvature_spatial": res["curvature"]["spatial"],
                "base_pairing_spatial": res["base_pairing"]["spatial"],
            })

        if not per_job:
            _set(run_id, state="done", result={"ready": False,
                 "reason": "trajectory has too few helices/frames to measure"})
            return

        result = {
            "ready": True,
            "scope": req.scope,
            "jobs": [j.job_id for j, _ in inputs],
            "twist": {"temporal": {"per_frame": twist_pf, "boundaries": boundaries},
                      "spatial": [{"job_id": p["job_id"], "points": p["twist_spatial"]}
                                  for p in per_job]},
            "curvature": {"temporal": {"per_frame": curv_pf, "boundaries": boundaries},
                          "spatial": [{"job_id": p["job_id"], "points": p["curvature_spatial"]}
                                      for p in per_job]},
            "base_pairing": {"temporal": {"per_frame": bp_pf, "boundaries": boundaries,
                                          "n_designed": n_designed},
                             "spatial": [{"job_id": p["job_id"], "points": p["base_pairing_spatial"]}
                                         for p in per_job]},
        }
        _set(run_id, state="done", progress=1.0, eta_s=0.0, result=result)
    except Exception as exc:                   # surface any failure to the poller
        _set(run_id, state="error", error=str(exc))


@router.post("/md/jobs/{job_id}/metrics/start")
def start_md_metrics(job_id: str, req: MdMetricsStartRequest) -> dict:
    """Launch a background twist/curvature/base-pairing compute for a NAMD job
    (``scope=latest``) or its whole refit lineage (``scope=chain``).  Returns
    ``{metrics_id}``; poll ``GET /md/metrics/{id}`` for progress + the result."""
    _load_job(job_id)                          # 404 early if the job is unknown
    run_id = uuid.uuid4().hex[:12]
    _set(run_id, state="running", progress=0.0, eta_s=None, frames_done=0,
         frames_total=None, result=None, error=None)
    threading.Thread(target=_compute, args=(run_id, job_id, req, _workspace()),
                     daemon=True).start()
    return {"metrics_id": run_id, "state": "running"}


@router.get("/md/metrics/{run_id}")
def get_md_metrics(run_id: str) -> dict:
    """Progress + result of an MD metric run: ``{state, progress, eta_s, frames_done,
    frames_total, result?, error?}``.  ``state`` is ``running`` | ``done`` | ``error``;
    ``result`` (on done) carries the twist/curvature/base-pairing series for both
    domains — SAME shape as the oxDNA metrics route, so the graph card reuses it."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no metric run {run_id!r}")
        return {"metrics_id": run_id, **run}
