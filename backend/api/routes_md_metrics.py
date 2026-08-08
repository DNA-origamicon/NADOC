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
    scope: str = "latest"  # "latest" (this job only) | "chain" (whole refit lineage)
    n_slices: int = 0  # 0 => auto (~1-turn slabs), matching the measure defaults


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _job_inputs(job, ws: Path):
    """(psf, ref_pdb, segments, design) for one MD job's composite, or a ``str`` reason
    it can't be measured yet.  Prefers the job's FROZEN ``design.json`` snapshot (inherited
    from the parent for production/ensemble children — see ``routes_md._md_snapshot_design``);
    only a pre-snapshot legacy job with none in its whole lineage falls back to the active
    design.  Returning a *reason* (rather than a bare ``None``) lets the card say WHY a run
    couldn't start — a missing snapshot is not the same as a missing trajectory."""
    from backend.api import state as design_state

    package_dir = job.package_dir(ws)
    psf = package_dir / f"{job.name_stem}.psf"
    ref = package_dir / f"{job.name_stem}.pdb"
    if not psf.exists() or not ref.exists():
        return "topology (PSF/PDB) not built for this job yet"
    segments = _md_segment_dcds(job)
    if not segments:
        return "no NAMD trajectory yet"
    design = _md_snapshot_design(job)
    if design is None:
        # No snapshot anywhere in the lineage: fall back to the active design (best effort).
        try:
            design = design_state.get_or_404()
        except Exception:
            return (
                "design snapshot missing for this job — load its design "
                "(File → Open) so the trajectory can be measured"
            )
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
        resolved = [(j, _job_inputs(j, ws)) for j in jobs]
        inputs = [(j, io) for j, io in resolved if not isinstance(io, str)]
        if not inputs:
            # Every selected job was unusable — surface the specific reason(s) rather than
            # a blanket "no trajectory" (which is wrong when a DCD is present but its
            # design snapshot isn't).  De-dupe while preserving order.
            reasons = list(
                dict.fromkeys(io for _j, io in resolved if isinstance(io, str))
            )
            reason = (
                "; ".join(reasons)
                if reasons
                else "no NAMD trajectory yet for the selected job(s)"
            )
            _set(run_id, state="done", result={"ready": False, "reason": reason})
            return

        total = 0
        for _j, (_psf, _ref, segments, _d) in inputs:
            total += count_md_frames(segments)
        _set(
            run_id, frames_total=max(1, total), frames_done=0, progress=0.0, eta_s=None
        )

        started = time.time()
        done = {"n": 0}

        def _tick() -> None:
            done["n"] += 1
            elapsed = time.time() - started
            frac = done["n"] / max(1, total)
            eta = (elapsed / done["n"]) * (total - done["n"]) if done["n"] else None
            _set(
                run_id,
                frames_done=done["n"],
                progress=round(min(1.0, frac), 4),
                eta_s=round(eta, 1) if eta is not None else None,
            )

        # temporal series concatenate end-to-end; spatial profiles overlay one per job.
        twist_pf: list[float] = []
        curv_pf: list[float] = []
        bp_pf: list[float] = []
        boundaries: list[dict] = []
        per_job: list[dict] = []
        n_designed = 0
        for j, (psf, ref, segments, design) in inputs:
            analytic = core_reference_geometry(design)
            res = md_metric_series(
                psf,
                segments,
                ref,
                design,
                analytic,
                n_slices=req.n_slices,
                on_frame=_tick,
            )
            if not res.get("ready"):
                continue
            boundaries.append(
                {
                    "job_id": j.job_id,
                    "start_frame": len(twist_pf),
                    "n_frames": res["n_frames"],
                }
            )
            twist_pf.extend(res["twist"]["temporal"]["per_frame"])
            curv_pf.extend(res["curvature"]["temporal"]["per_frame"])
            bp_pf.extend(res["base_pairing"]["temporal"]["per_frame"])
            n_designed = max(n_designed, res["base_pairing"]["temporal"]["n_designed"])
            per_job.append(
                {
                    "job_id": j.job_id,
                    "twist_spatial": res["twist"]["spatial"],
                    "curvature_spatial": res["curvature"]["spatial"],
                    "base_pairing_spatial": res["base_pairing"]["spatial"],
                }
            )

        if not per_job:
            _set(
                run_id,
                state="done",
                result={
                    "ready": False,
                    "reason": "trajectory has too few helices/frames to measure",
                },
            )
            return

        result = {
            "ready": True,
            "scope": req.scope,
            "jobs": [j.job_id for j, _ in inputs],
            "twist": {
                "temporal": {"per_frame": twist_pf, "boundaries": boundaries},
                "spatial": [
                    {"job_id": p["job_id"], "points": p["twist_spatial"]}
                    for p in per_job
                ],
            },
            "curvature": {
                "temporal": {"per_frame": curv_pf, "boundaries": boundaries},
                "spatial": [
                    {"job_id": p["job_id"], "points": p["curvature_spatial"]}
                    for p in per_job
                ],
            },
            "base_pairing": {
                "temporal": {
                    "per_frame": bp_pf,
                    "boundaries": boundaries,
                    "n_designed": n_designed,
                },
                "spatial": [
                    {"job_id": p["job_id"], "points": p["base_pairing_spatial"]}
                    for p in per_job
                ],
            },
        }
        _set(run_id, state="done", progress=1.0, eta_s=0.0, result=result)
    except Exception as exc:  # surface any failure to the poller
        _set(run_id, state="error", error=str(exc))


@router.post("/md/jobs/{job_id}/metrics/start")
def start_md_metrics(job_id: str, req: MdMetricsStartRequest) -> dict:
    """Launch a background twist/curvature/base-pairing compute for a NAMD job
    (``scope=latest``) or its whole refit lineage (``scope=chain``).  Returns
    ``{metrics_id}``; poll ``GET /md/metrics/{id}`` for progress + the result."""
    _load_job(job_id)  # 404 early if the job is unknown
    run_id = uuid.uuid4().hex[:12]
    _set(
        run_id,
        state="running",
        progress=0.0,
        eta_s=None,
        frames_done=0,
        frames_total=None,
        result=None,
        error=None,
    )
    threading.Thread(
        target=_compute, args=(run_id, job_id, req, _workspace()), daemon=True
    ).start()
    return {"metrics_id": run_id, "state": "running"}


@router.get("/md/jobs/{job_id}/cpd-pairs")
def get_md_cpd_pairs(job_id: str) -> dict:
    """The design's intended extra-base UV weld pairs, with their C5/C6 atom serials.

    Identity only — no coordinates.  The serials index the same solvated-universe atom
    numbering the atomistic display already streams positions under, so the viewer reads
    these four atoms straight out of the frame it is rendering and computes ``d_mid`` /
    ``eta`` client-side.  That is deliberate: the display affine is handed over rather
    than re-derived (``project_md_viz_tools``), so a second coordinate path here would
    draw the markers off the atoms.

    ``pairs`` is empty for a design with no insert-carrying reciprocal crossover pair,
    which is not an error — most designs have none.
    """
    from backend.core.cpd_metrics import (
        D0,
        N0,
        REACTIVE_D_NM,
        REACTIVE_ETA_DEG,
        VDW_FLOOR_NM,
        designed_weld_pairs,
        resolve_weld_serials,
    )

    job = _load_job(job_id)
    inputs = _job_inputs(job, _workspace())
    constants = {
        "d0_nm": D0,
        "eta0_deg": N0,
        "reactive_d_nm": REACTIVE_D_NM,
        "reactive_eta_deg": REACTIVE_ETA_DEG,
        "vdw_floor_nm": VDW_FLOOR_NM,
    }
    if isinstance(inputs, str):
        return {"ready": False, "reason": inputs, "pairs": [], "constants": constants}

    psf, _ref, _segments, design = inputs
    pairs = designed_weld_pairs(design)
    if not pairs:
        return {
            "ready": True,
            "reason": "design has no extra-base reciprocal crossover pair",
            "pairs": [],
            "constants": constants,
        }
    try:
        import MDAnalysis as mda

        pairs = resolve_weld_serials(pairs, mda.Universe(str(psf)))
    except Exception as exc:  # noqa: BLE001 - identity is still useful without serials
        return {
            "ready": False,
            "reason": f"could not read topology: {exc}",
            "pairs": pairs,
            "constants": constants,
        }
    return {"ready": True, "pairs": pairs, "constants": constants}


@router.get("/md/jobs/{job_id}/cpd-colvars")
def get_md_cpd_colvars(
    job_id: str,
    mode: str = "metrics",
    center_ang: float | None = None,
    force_constant: float = 2.0,
    d_start_ang: float = 3.5,
    d_end_ang: float = 12.0,
) -> dict:
    """The runnable Colvars config for this job's weld pair, plus a window ladder.

    ``mode`` is ``metrics`` (observe only) | ``umbrella`` (one window at ``center_ang``)
    | ``eabf`` (adaptive, no window grid).  ``windows`` is the suggested ladder over
    ``[d_start_ang, d_end_ang]`` — dense and stiff at short range where the free energy
    varies fastest.  Preview only; nothing is launched here.
    """
    from backend.core.cpd_colvars import VDW_FLOOR_ANG, emit_colvars, umbrella_windows
    from backend.core.cpd_metrics import designed_weld_pairs, resolve_weld_serials

    job = _load_job(job_id)
    inputs = _job_inputs(job, _workspace())
    if isinstance(inputs, str):
        return {"ready": False, "reason": inputs, "config": "", "windows": []}
    psf, _ref, _segments, design = inputs
    pairs = designed_weld_pairs(design)
    if not pairs:
        return {
            "ready": True,
            "config": "",
            "windows": [],
            "reason": "design has no extra-base reciprocal crossover pair",
        }
    try:
        import MDAnalysis as mda

        pairs = resolve_weld_serials(pairs, mda.Universe(str(psf)))
        config = emit_colvars(
            pairs,
            mode=mode,
            center_ang=center_ang,
            force_constant=force_constant,
            comment=f"{job.name_stem} — {mode}",
        )
        windows = umbrella_windows(d_start_ang, d_end_ang)
    except Exception as exc:  # noqa: BLE001 - a preview must not 500
        return {"ready": False, "reason": str(exc), "config": "", "windows": []}
    return {
        "ready": True,
        "config": config,
        "windows": windows,
        "mode": mode,
        "vdw_floor_ang": VDW_FLOOR_ANG,
        "pairs": [{"id": p["id"], "label": p["label"]} for p in pairs],
    }


class MdCpdTraceRequest(BaseModel):
    stride: int = 1
    max_frames: int = 2000
    # When set, the trace also reports which umbrella windows this run could seed.
    with_windows: bool = False
    d_start_ang: float = 3.5
    d_end_ang: float = 12.0


def _compute_cpd_trace(
    run_id: str, job_id: str, req: MdCpdTraceRequest, ws: Path
) -> None:
    """Background pass: read the trajectory once and measure the weld coordinates."""
    from backend.core.cpd_metrics import weld_trace

    try:
        job = _load_job(job_id)
        inputs = _job_inputs(job, ws)
        if isinstance(inputs, str):
            _set(run_id, state="error", error=inputs)
            return
        psf, _ref, segments, design = inputs
        _set(run_id, frames_total=None)

        def _progress(done: int, total: int) -> None:
            _set(
                run_id,
                progress=(done / total) if total else 0.0,
                frames_done=done,
                frames_total=total,
            )

        windows = None
        if req.with_windows:
            from backend.core.cpd_colvars import umbrella_windows

            windows = umbrella_windows(req.d_start_ang, req.d_end_ang)
        result = weld_trace(
            psf,
            [s[2] for s in segments],
            design,
            stride=max(1, req.stride),
            max_frames=max(1, req.max_frames),
            windows=windows,
            progress=_progress,
        )
        _set(run_id, state="done", progress=1.0, result=result)
    except Exception as exc:  # surface any failure to the poller
        _set(run_id, state="error", error=str(exc))


@router.post("/md/jobs/{job_id}/cpd-trace/start")
def start_md_cpd_trace(job_id: str, req: MdCpdTraceRequest) -> dict:
    """Launch a background pass measuring (d_mid, eta, k) for the design's weld pairs
    over the whole trajectory.  Returns ``{trace_id}``; poll ``GET /md/cpd-trace/{id}``.

    Separate from the overlay, which only ever shows the CURRENT frame: the question
    "did these two extra bases EVER get close enough to weld" is a whole-run question,
    and on a 1xT design the answer so far is no — which you can only see as a trace.
    """
    _load_job(job_id)  # 404 early if the job is unknown
    run_id = uuid.uuid4().hex[:12]
    _set(
        run_id,
        state="running",
        progress=0.0,
        frames_done=0,
        frames_total=None,
        result=None,
        error=None,
    )
    threading.Thread(
        target=_compute_cpd_trace, args=(run_id, job_id, req, _workspace()), daemon=True
    ).start()
    return {"trace_id": run_id, "state": "running"}


@router.get("/md/cpd-trace/{run_id}")
def get_md_cpd_trace(run_id: str) -> dict:
    """Progress + result of a weld-trace run: ``{state, progress, frames_done,
    frames_total, result?, error?}``.  ``result.pairs[]`` carries the per-frame
    ``d_nm`` / ``eta_deg`` / ``k`` series plus the run summary (``d_min_nm``,
    ``k_max``, ``reactive_frames``)."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no weld-trace run {run_id!r}")
        return {"trace_id": run_id, **run}


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
