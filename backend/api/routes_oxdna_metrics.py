"""Graphs & Metrics — REST surface for the oxDNA "Graphs and Metrics" card.

Computes twist, curvature and base-pairing over a production trajectory in ONE pass
(:func:`backend.core.oxdna_health.production_metric_series`) and serves them as both
domains — spatial (vs position along the bundle) and temporal (vs simulation time) — for
the graph popups + PNG/CSV export.  ``scope="latest"`` measures a single job; ``scope=
"chain"`` measures the whole parent/child lineage (:func:`resolve_job_chain`), concatenating
the temporal series end-to-end and overlaying one spatial profile per job.

Reading trajectory frames is the expensive part, so the work runs in a background daemon
thread with a pollable progress + ETA (mirrors ``routes_autorefine``'s registry pattern);
the panel drives a per-metric loading bar off it.  Registered in ``backend/api/main.py``.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.routes_oxdna import (
    _design_ref_conf,
    _load_job,
    _stage_trajectories,
    _workspace,
)

router = APIRouter(tags=["oxdna-metrics"])

# In-memory registry of metric-compute runs (one background pass each), polled by the card.
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()


class MetricsStartRequest(BaseModel):
    scope: str = "latest"      # "latest" (this job only) | "chain" (whole parent/child lineage)
    n_slices: int = 0          # 0 => auto (~1-turn slabs), matching the measure defaults


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _job_inputs(job, ws: Path):
    """Design + reference-conf + production/field trajectories for one job, or None if the
    job has no usable frames yet.  Mirrors the deviation/rmsf route's loading."""
    from backend.core.models import Design

    prod = [s for s in job.stages if s.kind in ("production", "field")
            and s.status in ("done", "running")]
    if not prod:
        return None
    jd = job.job_dir(ws)
    trajs: list[Path] = []
    for s in prod:
        trajs.extend(_stage_trajectories(job.stage_dir(ws, s.name)))
    if not trajs:
        return None
    design = Design.model_validate_json((jd / "design.json").read_text())
    ref_conf = _design_ref_conf(jd, design)
    return design, ref_conf, trajs


def _resolve_jobs(job_id: str, scope: str, ws: Path):
    """The chronological job list a metric run covers: just the anchor job (``latest``) or
    its whole parent/child lineage (``chain``)."""
    from backend.core.oxdna_job import OxdnaJob, resolve_job_chain

    anchor = _load_job(job_id)
    if scope != "chain":
        return [anchor]
    chain = resolve_job_chain(job_id, OxdnaJob.list_jobs(ws))
    return chain or [anchor]


def _compute(run_id: str, job_id: str, req: MetricsStartRequest, ws: Path) -> None:
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.oxdna_health import count_trajectory_frames, production_metric_series

    try:
        jobs = _resolve_jobs(job_id, req.scope, ws)
        inputs = [(j, _job_inputs(j, ws)) for j in jobs]
        inputs = [(j, io) for j, io in inputs if io is not None]
        if not inputs:
            _set(run_id, state="done", result={"ready": False,
                 "reason": "no production frames yet for the selected job(s)"})
            return

        total = 0
        for _j, (_d, _r, trajs) in inputs:
            total += sum(count_trajectory_frames(p) for p in trajs)
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
        for j, (design, ref_conf, trajs) in inputs:
            analytic = core_reference_geometry(design)
            res = production_metric_series(design, trajs, ref_conf, analytic,
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


@router.post("/oxdna/jobs/{job_id}/metrics/start")
def start_metrics(job_id: str, req: MetricsStartRequest) -> dict:
    """Launch a background twist/curvature/base-pairing compute for a job (``scope=latest``)
    or its whole parent/child lineage (``scope=chain``).  Returns ``{metrics_id}``; poll
    ``GET /oxdna/metrics/{id}`` for progress + the result."""
    _load_job(job_id)                          # 404 early if the job is unknown
    run_id = uuid.uuid4().hex[:12]
    _set(run_id, state="running", progress=0.0, eta_s=None, frames_done=0,
         frames_total=None, result=None, error=None)
    threading.Thread(target=_compute, args=(run_id, job_id, req, _workspace()),
                     daemon=True).start()
    return {"metrics_id": run_id, "state": "running"}


@router.get("/oxdna/metrics/{run_id}")
def get_metrics(run_id: str) -> dict:
    """Progress + result of a metric run: ``{state, progress, eta_s, frames_done,
    frames_total, result?, error?}``.  ``state`` is ``running`` | ``done`` | ``error``;
    ``result`` (on done) carries the twist/curvature/base-pairing series for both domains."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no metric run {run_id!r}")
        return {"metrics_id": run_id, **run}
