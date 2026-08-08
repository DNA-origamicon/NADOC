"""Autorefine skips/loops — REST surface for the square-lattice self-consistency loop.

Starts a background job that tunes the loaded design's skip pattern until its oxDNA
simulation matches the geometry it depicts (see
:func:`backend.api.skip_twist_tuning.autorefine_sq_design`), exposing a pollable status
with a BEFORE/AFTER score comparison.  Square lattice only for now (the loop's knob is
the square-lattice periodic skip period); other designs are rejected with a clear 400.
"""

from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.routes_oxdna import _workspace
from backend.core.models import LatticeType

router = APIRouter(tags=["autorefine"])

# In-memory registry of autorefine runs (one background loop each).  Status is polled
# by the panel; the final result is also written to disk for durability.  Stop events
# live in a SEPARATE map (not JSON-serialisable, so kept out of the polled dict).
_RUNS: dict[str, dict] = {}
_STOP: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


class AutorefineStartRequest(BaseModel):
    backend: str = "CUDA"
    device: str = "0"
    salt_concentration: float = 0.5
    design_source_path: str | None = None  # so the run's jobs filter with this design
    tol_nm: float = 2.0  # RMSD tolerance (curved/twisted designs)
    tol_twist_deg: float = 5.0  # twist tolerance (plain square lattice — the gate)
    min_confidence: int = 400  # frames required to ACCEPT (high-confidence mean)
    initial_period: int | None = (
        None  # None => seed from the design (48 if it has no skips)
    )
    max_iterations: int = 6
    production_steps: int = (
        8_000_000  # long rounds for decorrelated frames near tolerance
    )
    max_production_rounds: int = 6
    regional: bool = False  # Phase 5 (shelved): non-uniform wholesale placement
    w_dev: float = 1.0  # regional: deviation weight (attracts)
    w_strain: float = 0.25  # regional: strain weight (repels)
    min_spacing: int = 4  # regional: min bp between deletions
    finetune: bool = (
        True  # default: fine-tune from the analytical pattern (CanDo-style)
    )
    finetune_max_edits: int = 5  # max add/remove skip edits across the whole origami


def _set(run_id: str, **fields) -> None:
    with _LOCK:
        _RUNS.setdefault(run_id, {}).update(fields)


def _run(run_id: str, design, workspace, params: AutorefineStartRequest) -> None:
    from backend.api.skip_twist_tuning import autorefine_sq_design

    stop_event = _STOP[run_id]

    def on_progress(ev: dict) -> None:
        fields = {"phase": ev.get("phase"), "last_event": ev}
        if ev.get("period") is not None:  # persists the current period across phases
            fields["current_period"] = ev["period"]
        _set(run_id, **fields)

    def on_job(job) -> None:  # track the in-flight job so stop can kill it
        _set(run_id, current_job_id=job.job_id)

    try:
        result = autorefine_sq_design(
            design,
            workspace,
            on_progress=on_progress,
            should_stop=stop_event.is_set,
            on_job=on_job,
            tol_nm=params.tol_nm,
            tol_twist_deg=params.tol_twist_deg,
            min_confidence=params.min_confidence,
            initial_period=params.initial_period,
            max_iterations=params.max_iterations,
            production_steps=params.production_steps,
            max_production_rounds=params.max_production_rounds,
            regional=params.regional,
            w_dev=params.w_dev,
            w_strain=params.w_strain,
            min_spacing=params.min_spacing,
            finetune=params.finetune,
            finetune_max_edits=params.finetune_max_edits,
            backend=params.backend,
            device=params.device,
            salt_concentration=params.salt_concentration,
            design_source_path=params.design_source_path,
        )
        final = "stopped" if result.get("status") == "stopped" else "done"
        _set(run_id, state=final, result=result, phase=final)
        try:  # durable copy alongside the oxDNA jobs
            import json

            out_dir = workspace / "autorefine"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{run_id}.json").write_text(json.dumps(result, indent=2))
        except OSError:
            pass
    except Exception as exc:  # surface any failure to the poller
        _set(run_id, state="error", error=str(exc), phase="error")


@router.post("/design/oxdna/autorefine/start")
def start_autorefine(req: AutorefineStartRequest) -> dict:
    """Validate the loaded design (square lattice) and launch a background autorefine
    loop.  Returns ``{autorefine_id}``; poll ``/design/oxdna/autorefine/{id}``."""
    design = design_state.get_or_404()
    if design.lattice_type != LatticeType.SQUARE:
        raise HTTPException(
            400,
            detail="Autorefine skips/loops currently supports SQUARE lattice "
            "designs only (the knob is the square-lattice periodic skip period). "
            "Support for curved/twisted and other-lattice designs is planned.",
        )
    if not any(s.strand_type.value == "scaffold" for s in design.strands):
        raise HTTPException(
            400,
            detail="Route a scaffold first — autorefine needs a fully routed, "
            "sequenced design to simulate.",
        )

    run_id = uuid.uuid4().hex[:12]
    _STOP[run_id] = threading.Event()
    _set(
        run_id,
        state="running",
        phase="starting",
        result=None,
        error=None,
        current_job_id=None,
    )
    snapshot = design.model_copy(deep=True)
    threading.Thread(
        target=_run, args=(run_id, snapshot, _workspace(), req), daemon=True
    ).start()
    return {"autorefine_id": run_id, "state": "running"}


@router.post("/design/oxdna/autorefine/{run_id}/apply")
def apply_autorefine_skips(run_id: str, period: int | None = None) -> dict:
    """Apply a skip pattern to the ACTIVE design as a feature-log entry (op_kind
    ``autorefine-skips``) — so the refinement actually lands on the model and the user
    can see / seek / revert / delete it.  Clears existing loop/skip marks first, then
    lays the period-``period`` pattern.

    With an explicit ``period`` (query param) this applies THAT iteration's pattern —
    used to update the design live as the loop runs, so the user watches the skips move
    each iteration and can stop early.  Without ``period`` it applies the completed run's
    converged pattern: the EXACT non-uniform deletion set for a REGIONAL run (which cannot
    be re-derived from a single period), else the uniform period-pattern."""
    from backend.api import state as design_state
    from backend.api.crud import _design_response
    from backend.api.skip_twist_tuning import (
        build_explicit_skip_from_design,
        build_sq_skip_from_design,
    )

    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, detail=f"no autorefine run {run_id!r}")

    result = run.get("result") or {}
    # An explicit converged pattern (regional or fine-tuned) lands verbatim — but ONLY on the
    # "apply the finished run" call (period is None).  A live per-iteration preview passes an
    # explicit period and still previews uniformly (the exact pattern lands at completion).
    explicit_skips = result.get("converged_skips")
    apply_explicit = bool(
        period is None and run.get("state") in ("done", "stopped") and explicit_skips
    )

    if period is None and not apply_explicit:
        if run.get("state") not in ("done", "stopped"):
            raise HTTPException(409, detail="autorefine run is not complete")
        period = result.get("converged_period")
        if period is None:
            raise HTTPException(409, detail="this run produced no skip period to apply")

    design = design_state.get_or_404()
    if design.lattice_type != LatticeType.SQUARE:
        raise HTTPException(400, detail="active design is not a square lattice")

    # Re-derive the FULL sequence after laying the new skip pattern — not just the marks.
    # ``strand.sequence`` is consumed in walk order (a skip drops a position WITHOUT
    # consuming a character — see ``topology_rows``), so changing the skip set shifts every
    # downstream base and de-registers the staples from the scaffold: the marks would land
    # but the sequences would no longer be Watson-Crick complementary, and the next oxDNA
    # relaxation would melt (verified on 3x6x400 — apply-without-resequence dropped
    # complementarity from 99% to 27%).  Both build helpers do clear → apply → full_sequence.
    #
    # Build OUTSIDE ``mutate_with_feature_log``: the rebuild runs in a scratch headless
    # session (set_design/get_or_404), which re-acquires the same global state lock that
    # ``mutate_with_feature_log`` holds while it calls ``fn`` — doing it inside the callback
    # self-deadlocks (the lock is non-reentrant).  Build first, hand it in as a replacement.
    if apply_explicit:
        n_del = sum(len(v) for v in explicit_skips.values())
        placement = result.get("placement", "regional")
        refined = build_explicit_skip_from_design(design, explicit_skips)
        label = f"Autorefine skips ({placement}, {n_del} deletions)"
        params = {
            "placement": placement,
            "skip_period": result.get("converged_period"),
            "source": "autorefine",
            "run_id": run_id,
            "resequenced": True,
        }
    else:
        period = int(period)
        refined = build_sq_skip_from_design(design, period)
        label = f"Autorefine skips (period {period} bp)"
        params = {
            "skip_period": period,
            "source": "autorefine",
            "run_id": run_id,
            "resequenced": True,
        }

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="autorefine-skips", label=label, params=params, fn=lambda _d: refined
    )
    return _design_response(updated, report)


@router.post("/design/oxdna/autorefine/{run_id}/stop")
def stop_autorefine(run_id: str) -> dict:
    """Request cancellation of a running autorefine: set its stop flag (the loop exits
    at the next iteration / pooling boundary) AND kill the in-flight oxDNA job so the
    stop takes effect promptly rather than after the current relaxation/production."""
    from backend.core.oxdna_runner import stop_job

    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no autorefine run {run_id!r}")
        ev = _STOP.get(run_id)
        current_job = run.get("current_job_id")
    if ev is not None:
        ev.set()
    killed = bool(current_job) and stop_job(current_job, _workspace())
    return {"autorefine_id": run_id, "stopping": True, "killed_job": killed}


@router.get("/design/oxdna/autorefine/{run_id}")
def get_autorefine(run_id: str) -> dict:
    """Current state of an autorefine run: ``{state, phase, last_event, result?,
    error?}``.  ``state`` is ``running`` | ``done`` | ``error``; ``result`` (on done)
    carries the BEFORE/AFTER comparison."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, detail=f"no autorefine run {run_id!r}")
        return {"autorefine_id": run_id, **run}
