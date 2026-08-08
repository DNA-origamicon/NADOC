"""CanDo-FEM autorefine — REST surface (Phase-5 Item 4).

Sibling of ``routes_autorefine.py`` (the oxDNA square-lattice self-consistency loop), but the
oracle is the FAST in-process CanDo FEM shape predictor instead of a CUDA oxDNA simulation, so a
run finishes in seconds-to-minutes rather than hours and needs no GPU / no subprocess.  The loop
greedily adds/removes loop/skip marks to shrink the FEM-vs-intended deviation RMSD
(:func:`backend.core.cando_autorefine.fem_refine`).

Like the oxDNA autorefine, a run is a background daemon thread tracked in an in-memory registry
(polled by the panel) with a durable JSON copy; there is no per-run job store.  Unlike it, this
works on ANY lattice — square lattice tunes with skips only, curved/twisted (honeycomb) designs
also use loops — because the objective is a positional RMSD, not the square-lattice twist gate.

All routes prefixed ``/api``.  Mounted in ``backend/api/main.py``.

Route summary
─────────────
POST   /design/cando/autorefine/start        launch a background FEM-oracle refine loop
GET    /design/cando/autorefine/{run_id}      poll state / progress / result
POST   /design/cando/autorefine/{run_id}/stop request cancellation
POST   /design/cando/autorefine/{run_id}/apply land the converged marks on the active design

Three-Layer Law: the loop reads topology + predicts a Physical-layer shape; only ``apply`` mutates
the design, and it does so as a single reversible feature-log entry.
"""

from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.routes_cando import _workspace

router = APIRouter(tags=["cando-autorefine"])

# In-memory registry of refine runs (one background loop each).  Status is polled by the panel;
# the final result is also written to disk for durability.  Stop events live in a SEPARATE map
# (threading.Event is not JSON-serialisable, so kept out of the polled dict).
_RUNS: dict[str, dict] = {}
_STOP: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


class CandoAutorefineStartRequest(BaseModel):
    nonlinear: bool = Field(
        False,
        description="FEM oracle mode per trial: Coarse/linear (default, "
        "~seconds) vs Fine/nonlinear (slower, closer to CanDo). "
        "Coarse is the sensible inner-loop oracle; run a Fine job "
        "afterwards to confirm.",
    )
    allow_loops: bool | None = Field(
        None,
        description="Candidate edit space: None => auto (square "
        "lattice = skips only, else skips + loops); "
        "True/False overrides.",
    )
    sigma: float = Field(
        1.0, ge=0.0, description="Hotspot noise-floor: mean + sigma·std"
    )
    max_hotspots: int = Field(
        8, ge=1, le=64, description="Max deviation hotspots to visit"
    )
    min_spacing: int = Field(
        8, ge=1, description="Min bp between hotspots / marks on a helix"
    )
    rmsd_improve_nm: float = Field(
        0.05, ge=0.0, description="Min RMSD drop (nm) to accept an edit"
    )


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _run(run_id: str, design, req: CandoAutorefineStartRequest) -> None:
    from backend.core.cando_autorefine import fem_refine

    stop_event = _STOP[run_id]

    def on_progress(ev: dict) -> None:
        # last_event tracks EVERY event (phase text); last_iteration retains the most recent
        # per-iteration metrics so the status line keeps showing them through the interspersed
        # trial events (which fire between iteration boundaries).
        fields = {"phase": ev.get("phase"), "last_event": ev}
        if ev.get("phase") == "iteration":
            fields["last_iteration"] = ev
        _set(run_id, **fields)

    try:
        result = fem_refine(
            design,
            nonlinear=req.nonlinear,
            allow_loops=req.allow_loops,
            sigma=req.sigma,
            max_hotspots=req.max_hotspots,
            min_spacing=req.min_spacing,
            rmsd_improve_nm=req.rmsd_improve_nm,
            on_progress=on_progress,
            should_stop=stop_event.is_set,
        )
        final = "stopped" if result.get("status") == "stopped" else "done"
        _set(run_id, state=final, result=result, phase=final)
        try:  # durable copy alongside the oxDNA autorefine runs
            import json

            out_dir = _workspace() / "cando_autorefine"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{run_id}.json").write_text(json.dumps(result, indent=2))
        except OSError:
            pass
    except Exception as exc:  # surface any failure to the poller
        _set(run_id, state="error", error=str(exc), phase="error")


@router.post("/design/cando/autorefine/start")
def start_cando_autorefine(req: CandoAutorefineStartRequest) -> dict:
    """Launch a background CanDo-FEM refine loop on the active design.  Returns
    ``{autorefine_id}``; poll ``/design/cando/autorefine/{id}``."""
    design = design_state.get_or_404()
    from backend.core.models import LatticeType

    if not design.helices:
        raise HTTPException(400, detail="Design has no helices to refine.")
    # A SQUARE bundle is always refinable even bare: its crossover register imposes an intrinsic
    # global over-twist at ZERO skips, and the density sweep adds the deletions that relieve it.
    # Honeycomb has no such register term, so a bare honeycomb design needs a bend/twist or marks.
    if (
        design.lattice_type != LatticeType.SQUARE
        and not any(h.loop_skips for h in design.helices)
        and not design.deformations
    ):
        raise HTTPException(
            400,
            detail="Nothing to refine: the design carries no loop/skips and no bend/twist "
            "to realise.  Draw a bend/twist (or add loop/skips) first, then autorefine tunes the "
            "loop/skip placement so the FEM-predicted shape matches it.",
        )

    run_id = uuid.uuid4().hex[:12]
    _STOP[run_id] = threading.Event()
    _set(run_id, state="running", phase="starting", result=None, error=None)
    snapshot = design.model_copy(deep=True)
    threading.Thread(target=_run, args=(run_id, snapshot, req), daemon=True).start()
    return {"autorefine_id": run_id, "state": "running"}


@router.get("/design/cando/autorefine/{run_id}")
def get_cando_autorefine(run_id: str) -> dict:
    """Current state of a refine run: ``{state, phase, last_event, result?, error?}``.
    ``state`` ∈ ``running`` | ``done`` | ``stopped`` | ``error``; ``result`` (on done) carries the
    BEFORE/AFTER RMSD, the kept edits, and the converged mark set."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no CanDo autorefine run {run_id!r}")
        return {"autorefine_id": run_id, **run}


@router.post("/design/cando/autorefine/{run_id}/stop")
def stop_cando_autorefine(run_id: str) -> dict:
    """Request cancellation: the loop exits at the next hotspot / trial boundary.  The current FEM
    solve cannot be interrupted mid-way (in-process scipy), so it finishes then stops."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no CanDo autorefine run {run_id!r}")
        ev = _STOP.get(run_id)
    if ev is not None:
        ev.set()
    return {"autorefine_id": run_id, "stopping": True}


@router.post("/design/cando/autorefine/{run_id}/apply")
def apply_cando_autorefine(run_id: str) -> dict:
    """Land a completed run's converged loop/skip mark set on the ACTIVE design as a reversible
    feature-log entry (``op_kind='cando-autorefine-marks'``) — the user can seek / revert / delete
    it.  Clears the existing marks, lays the converged set, and re-sequences so staples stay
    Watson-Crick complementary."""
    from backend.api.crud import _design_response

    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, detail=f"no CanDo autorefine run {run_id!r}")
    if run.get("state") not in ("done", "stopped"):
        raise HTTPException(409, detail="CanDo autorefine run is not complete")
    result = run.get("result") or {}
    marks = result.get("converged_marks")
    if not marks:
        raise HTTPException(409, detail="this run produced no loop/skip marks to apply")

    design = design_state.get_or_404()
    n_skip = sum(1 for bps in marks.values() for dl in bps.values() if dl == -1)
    n_loop = sum(1 for bps in marks.values() for dl in bps.values() if dl == +1)
    n_kept = len(result.get("edits_kept") or [])
    label = f"CanDo autorefine ({n_skip} skips, {n_loop} loops)"
    params = {
        "source": "cando-autorefine",
        "run_id": run_id,
        "mode": result.get("mode"),
        "edits_kept": n_kept,
        "before_rmsd": (result.get("before") or {}).get("rmsd"),
        "after_rmsd": (result.get("after") or {}).get("rmsd"),
        "resequenced": True,
    }

    # Build OUTSIDE mutate_with_feature_log: the resequence rebuild runs in a scratch headless
    # session that re-acquires the same global state lock the callback holds → self-deadlock.
    # Build first, hand the finished design in as a pure replacement (same pattern as the oxDNA
    # autorefine apply).
    from backend.core.cando_autorefine import build_refined_design

    refined = build_refined_design(design, marks)
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="cando-autorefine-marks",
        label=label,
        params=params,
        fn=lambda _d: refined,
    )
    return _design_response(updated, report)
