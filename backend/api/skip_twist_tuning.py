"""Self-consistency skip tuning for square-lattice global twist (option (a)).

A square-lattice bundle is built assuming 10.67 bp/turn but relaxes toward B-DNA's
~10.5 bp/turn, so without correction it acquires a global (left-handed) twist — the
relaxed structure does NOT match the straight bundle the design depicts.  The standard
fix is a periodic deletion ("skip") pattern (Dietz/Douglas/Shih 2009;
:func:`~backend.core.loop_skip_calculator.sq_lattice_periodic_skips`, canonical period
48 bp).  This module closes the loop on that correction: it builds the seamless, routed,
sequenced bundle with a given skip period, relaxes it in oxDNA, and tunes the period
until the simulated time-averaged structure matches the design's ANALYTIC geometry
(``geometry_match`` RMSD), steering on the SIGNED global-twist residual the gate reports.

Knob = skip period P (bp per deletion); smaller P = more deletions = more de-twisting.
Three-Layer Law: the knob edits TOPOLOGY (loop_skip marks); the relaxed mean structure
is READ to score, never written back into the design.

Validate the loop mechanics on a small ``2x3x40`` proxy, then run full-scale on
``3x6x400`` (see ``tests/test_skip_twist_tuning_production.py``).
"""

from __future__ import annotations

from backend.core.loop_skip_calculator import (
    SQ_SKIP_PERIOD_DEFAULT,
    apply_loop_skips,
    sq_lattice_periodic_skips,
)
from backend.core.models import Design, LatticeType


def square_cells(rows: int, cols: int) -> list[tuple]:
    """``(row, col)`` lattice cells for a ``rows x cols`` square bundle."""
    return [(r, c) for r in range(rows) for c in range(cols)]


def _select_scaffold(design, scaffold) -> str:
    """The scaffold name to fully sequence ``design`` with.  ``scaffold=None`` =>
    auto-pick the SHORTEST library scaffold (M13mp18 < p7560 < p8064) that leaves no
    undefined base (the seamless scaffold path of a large bundle can exceed M13's 7249
    nt); an explicit name is used verbatim.  Raises if no library scaffold is long
    enough (the design needs a custom/tiled scaffold — out of scope here)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.sequences import SCAFFOLD_LIBRARY
    from backend.physics.oxdna_interface import count_undefined_bases

    if scaffold is not None:
        return scaffold
    for name, _length, _seq in sorted(SCAFFOLD_LIBRARY, key=lambda t: t[1]):
        hb.full_sequence(scaffold_name=name)
        if count_undefined_bases(design_state.get_or_404())[0] == 0:
            return name
    longest = max(SCAFFOLD_LIBRARY, key=lambda t: t[1])
    raise ValueError(
        f"no library scaffold covers this design (longest is {longest[0]} at "
        f"{longest[1]} nt) — it needs a custom/tiled scaffold"
    )


def build_sq_skip_design(
    cells, length_bp: int, skip_period, *, scaffold: str | None = None
) -> Design:
    """A seamless, fully-routed, fully-sequenced square-lattice bundle carrying the
    periodic de-twist skip pattern at ``skip_period`` bp (``None`` => no skips, the
    uncorrected baseline).

    Build order: bundle -> seamless scaffold route -> full autostaple (crossovers +
    breaks) -> apply periodic skips (needs crossovers + routed dsDNA intervals) ->
    full sequence (so the assigned sequence matches the post-skip nucleotide count).
    ``scaffold=None`` auto-selects the shortest covering library scaffold (see
    :func:`_select_scaffold`).  Returns a deep copy detached from the build session.
    """
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(cells, length_bp, lattice=LatticeType.SQUARE, name="sq_skip")
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple(scaffold_name=scaffold or "M13mp18")
        if skip_period is not None:
            mods = sq_lattice_periodic_skips(
                design_state.get_or_404(), int(skip_period)
            )
            design_state.set_design(apply_loop_skips(design_state.get_or_404(), mods))
        chosen = _select_scaffold(design_state.get_or_404(), scaffold)
        hb.full_sequence(scaffold_name=chosen)
        return design_state.get_or_404().model_copy(deep=True)


def core_reference_geometry(design) -> list[dict]:
    """The design's ANALYTIC geometry restricted to the rigid dsDNA core — the
    self-consistency target (``reference_fn`` for ``iterate_to_constraint``).

    CRITICAL — keyed like the SIMULATION, not the display.  The reference must share
    ``(helix_id, bp_index, direction)`` keys with the simulated mean structure, which
    comes from ``read_configuration_full`` over the strand walk
    (:func:`_strand_nucleotide_order`).  The render-feed ``_geometry_for_design`` keys
    differ for ~13% of nucleotides (display-only phantom strands + a different unpaired
    convention), so the reference is built the way the oxDNA *config* is: resolve the
    strand-walk keys to analytic positions via :func:`resolved_nuc_map` over the SAME
    ``compact_skips=True`` geometry the runner writes.

    The dsDNA CORE is then defined topologically — every ``(helix, bp)`` column that
    carries BOTH strands — which drops the floppy single-stranded seamless ends (ill-
    defined time-average, and not what the skip pattern controls) without depending on
    any display flag.  The returned list doubles as the core MASK applied to the mean
    structure (shared-key intersection in ``check_relaxed_constraint``)."""
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import (
        _XB_SENTINEL,
        _strand_nucleotide_order,
        resolved_nuc_map,
    )

    resolved = resolved_nuc_map(
        design, _geometry_for_design(design, compact_skips=True)
    )
    recs: list[tuple] = []
    strands_at: dict = {}
    for key in _strand_nucleotide_order(design):
        if key[0] == _XB_SENTINEL:
            continue
        nuc = resolved.get(key)
        if nuc is None:
            continue
        hid, bp = key[0], int(key[1])
        direction = getattr(key[2], "value", key[2])
        copy = (
            key[3] if len(key) == 4 else 0
        )  # loop-copy index (0 for plain nucleotides)
        recs.append((hid, bp, direction, copy, nuc["backbone_position"]))
        strands_at.setdefault((hid, bp), set()).add(direction)
    return [
        {
            "helix_id": hid,
            "bp_index": bp,
            "direction": d,
            "copy": copy,
            "backbone_position": list(pos),
        }
        for (hid, bp, d, copy, pos) in recs
        if len(strands_at[(hid, bp)]) >= 2
    ]


class PeriodAdjuster:
    """Stateful ``adjust_fn(period, verdict) -> next_period`` driving the SIGNED twist
    residual to 0 by a secant step on the skip period.

    The first adjustment is a sign-DIRECTED step whose SIZE SCALES with how far off the
    residual is (square-lattice d(twist)/d(period) > 0, so an over-twisted design —
    residual > 0 — gets more skips = smaller period; under-twisted gets fewer = larger).
    A large residual (e.g. a SQUARE design's analytical under-correction, ~+70°, which needs
    roughly half the period) takes a big step up to ``explore_max`` (≈ halving); a
    near-converged residual takes a gentle nudge (down to ``explore_min``) — so it converges
    fast when the analytical start is far off AND fine-tunes gently when it is already close.
    Every later step is a secant interpolation through the two most recent (period, residual)
    samples, jumping straight to the zero-crossing; a big first step also makes that slope
    reliable above the per-round twist noise.  Periods are clamped to ``[p_min, p_max]`` and
    kept integer + distinct from the last value.
    """

    def __init__(
        self,
        *,
        p_min: int = 8,
        p_max: int = 400,
        explore_max: float = 0.5,
        explore_gain: float = 0.015,
        explore_min: float = 0.03,
    ):
        self.p_min, self.p_max = p_min, p_max
        self.explore_max, self.explore_gain, self.explore_min = (
            explore_max,
            explore_gain,
            explore_min,
        )
        self.history: list[tuple] = []  # (period, residual_deg)

    @staticmethod
    def _residual(verdict) -> float:
        steering = (verdict or {}).get("steering") or {}
        r = steering.get("bundle_twist_residual_deg")
        if r is None:
            raise ValueError(
                "PeriodAdjuster needs the signed twist residual — drive a "
                "geometry_match constraint with a reference (verdict['steering'])."
            )
        return float(r)

    def _clamp(self, p: float, last: int) -> int:
        p = int(round(p))
        p = max(self.p_min, min(self.p_max, p))
        if p == last:  # ensure a distinct rebuild
            p = max(self.p_min, min(self.p_max, p - 1 if last > self.p_min else p + 1))
        return p

    def _explore_step(self, period: int, residual: float) -> int:
        # DIRECTED step sized to the residual: far-off (big |residual|) → big step toward the
        # fix (up to explore_max ≈ halving — square's 48→~24); near-converged → gentle nudge
        # (>= explore_min so a distinct second secant point still exists).  Square-lattice
        # d(twist)/d(period) > 0: over-twisted (residual > 0) → smaller period (more skips).
        frac = min(
            self.explore_max, max(self.explore_min, abs(residual) * self.explore_gain)
        )
        factor = (1.0 - frac) if residual > 0 else (1.0 + frac)
        return self._clamp(period * factor, period)

    def __call__(self, period: int, verdict) -> int:
        period = int(period)
        residual = self._residual(verdict)
        self.history.append((period, residual))
        if len(self.history) < 2:
            return self._explore_step(period, residual)
        (p0, r0), (p1, r1) = self.history[-2], self.history[-1]
        slope = (r1 - r0) / (p1 - p0) if p1 != p0 else 0.0
        if abs(slope) < 1e-9:  # flat / no signal — small directed step
            return self._explore_step(period, residual)
        return self._clamp(p1 - r1 / slope, period)  # secant toward residual = 0


def build_sq_skip_from_design(base_design, skip_period, *, scaffold: str | None = None):
    """Re-derive the periodic skip pattern at ``skip_period`` on an ALREADY-routed,
    sequenced square-lattice design (the autorefine build_fn — refines a design the
    user loaded rather than building from cells).  Clears the existing loop/skip marks,
    applies the period-``skip_period`` pattern (``None`` => no skips), and re-sequences
    so the assigned bases match the new nucleotide count.  Topology only — display/
    physical state untouched."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.loop_skip_calculator import clear_all_loop_skips

    with hb.scratch_session(LatticeType.SQUARE):
        design_state.set_design(base_design.model_copy(deep=True))
        d = clear_all_loop_skips(design_state.get_or_404())
        if skip_period is not None:
            d = apply_loop_skips(d, sq_lattice_periodic_skips(d, int(skip_period)))
        design_state.set_design(d)
        hb.full_sequence(
            scaffold_name=_select_scaffold(design_state.get_or_404(), scaffold)
        )
        return design_state.get_or_404().model_copy(deep=True)


def build_regional_skip_design(
    base_design,
    skip_period,
    deviation_by_bp,
    strain_by_bp,
    *,
    w_dev: float = 1.0,
    w_strain: float = 0.25,
    min_spacing: int = 4,
    scaffold: str | None = None,
):
    """REGIONAL analog of :func:`build_sq_skip_from_design` (Phase 5): lay the SAME
    per-helix deletion COUNT that the uniform period-``skip_period`` pattern would (so net
    twist density is preserved), but place each deletion by the per-(helix,bp) deviation +
    strain fields rather than uniformly — see :mod:`backend.core.regional_skip_placer` for
    the anti-clustering even-slot guarantee.  Empty fields (the first iteration, before any
    simulation has run) collapse to the uniform-equivalent placement.  Topology only;
    re-sequences after placing so the bases match the post-skip nucleotide count."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.regional_skip_placer import (
        budget_from_uniform_period,
        place_regional_skips,
    )

    with hb.scratch_session(LatticeType.SQUARE):
        design_state.set_design(base_design.model_copy(deep=True))
        d = clear_all_loop_skips(design_state.get_or_404())
        if skip_period is not None:
            budget = budget_from_uniform_period(d, int(skip_period))
            mods = place_regional_skips(
                d,
                budget,
                deviation_by_bp or {},
                strain_by_bp or {},
                w_dev=w_dev,
                w_strain=w_strain,
                min_spacing=min_spacing,
            )
            d = apply_loop_skips(d, mods)
        design_state.set_design(d)
        hb.full_sequence(
            scaffold_name=_select_scaffold(design_state.get_or_404(), scaffold)
        )
        return design_state.get_or_404().model_copy(deep=True)


def build_explicit_skip_from_design(
    base_design, skips_by_helix, *, scaffold: str | None = None
):
    """Lay an EXPLICIT (caller-chosen) deletion pattern on a routed square-lattice design
    and re-sequence — the apply path for a converged REGIONAL pattern (which is non-uniform
    and so cannot be re-derived from a single period).  ``skips_by_helix`` is
    ``{helix_id: [bp_index, ...]}``.  Clears existing loop/skip marks first."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.models import LoopSkip

    with hb.scratch_session(LatticeType.SQUARE):
        design_state.set_design(base_design.model_copy(deep=True))
        d = clear_all_loop_skips(design_state.get_or_404())
        mods = {
            hid: [LoopSkip(bp_index=int(bp), delta=-1) for bp in bps]
            for hid, bps in (skips_by_helix or {}).items()
            if bps
        }
        if mods:
            d = apply_loop_skips(d, mods)
        design_state.set_design(d)
        hb.full_sequence(
            scaffold_name=_select_scaffold(design_state.get_or_404(), scaffold)
        )
        return design_state.get_or_404().model_copy(deep=True)


def measure_skip_fields(job, workspace, design, reference):
    """Per-(helix,bp) deviation + strain fields from a finished job's mean structure (the
    pooled production mean, vs the analytic ``reference``) and its final frame (backbone
    FENE strain) — the signals that steer the NEXT iteration's regional placement.  Both
    come from the SAME simulation (no extra sims).  Best-effort: returns ``({}, {})`` on
    any read failure, so the loop simply falls back to uniform-equivalent placement."""
    import glob
    from pathlib import Path

    from backend.api.headless_oxdna_build import read_flexibility_map
    from backend.core.oxdna_health import backbone_strain_field, geometry_deviation_map
    from backend.core.regional_skip_placer import aggregate_deviation_per_bp
    from backend.physics.oxdna_interface import read_configuration_full

    deviation: dict = {}
    strain: dict = {}
    try:
        mean = read_flexibility_map(job.job_id, workspace)
        if mean.get("positions") and reference:
            deviation = aggregate_deviation_per_bp(
                geometry_deviation_map(mean["positions"], reference)
            )
    except Exception:
        deviation = {}
    try:
        jd = job.job_dir(Path(workspace))
        confs = sorted(glob.glob(f"{jd}/*production*/last_conf.dat"))
        if confs:
            strain = backbone_strain_field(
                design, read_configuration_full(Path(confs[-1]), design)
            )
    except Exception:
        strain = {}
    return deviation, strain


def _finetune_measure(
    design, workspace, *, n_prod, production_steps, timeout, on_job=None, **relax_params
):
    """Pool a HIGH-confidence sim of ``design`` and return ``{twist, dev_max, dev_mean,
    deviation_by_bp, shape_profile}`` — the local-hotspot signals the fine-tuner ranks edits by.
    ``None`` on a failed relax/production.  ``on_job`` is called with each in-flight job (so the
    UI can track/select/stop it)."""
    import numpy as np

    from backend.api.headless_oxdna_build import (
        append_production,
        read_flexibility_map,
        run_relaxation,
        wait_for_terminal,
    )
    from backend.core.oxdna_health import (
        _filter_to_reference_core,
        geometry_deviation_map,
        measure_bundle_twist,
        measure_bundle_twist_profile,
    )
    from backend.core.regional_skip_placer import (
        aggregate_deviation_per_bp,
        detrend_error_profile,
    )

    job = run_relaxation(design, workspace, timeout=timeout, **relax_params)
    if on_job:
        on_job(job)
    if job.status.value != "completed":
        return None
    for _ in range(max(1, n_prod)):
        append_production(job.job_id, workspace, steps=production_steps)
        job = wait_for_terminal(job.job_id, workspace, timeout=timeout)
        if on_job:
            on_job(job)
        if job.status.value != "completed":
            return None
    mean = read_flexibility_map(job.job_id, workspace)
    if not mean.get("positions"):
        return None
    ref = core_reference_geometry(design)
    dmap = geometry_deviation_map(mean["positions"], ref)
    core = _filter_to_reference_core(mean["positions"], ref)
    sim = measure_bundle_twist_profile(core)
    ana = measure_bundle_twist_profile(ref)
    st = np.array([p[0] for p in sim])
    sv = np.array([p[1] for p in sim])
    at = np.array([p[0] for p in ana])
    av = np.array([p[1] for p in ana])
    shape = detrend_error_profile(
        list(zip(st.tolist(), (sv - np.interp(st, at, av)).tolist()))
    )
    devs = [p["deviation"] for p in dmap["positions"]]
    return {
        "twist": measure_bundle_twist(core),
        "dev_max": max(devs),
        "dev_mean": sum(devs) / len(devs),
        "deviation_by_bp": aggregate_deviation_per_bp(dmap),
        "shape_profile": shape,
    }


def greedy_finetune_skips(
    converged_design,
    workspace,
    *,
    max_edits: int = 5,
    tol_twist_deg: float = 5.0,
    dev_improve_nm: float = 0.1,
    sigma: float = 1.0,
    min_spacing: int = 8,
    n_prod: int = 3,
    production_steps: int = 2_000_000,
    on_progress=None,
    should_stop=None,
    on_job=None,
    timeout: float = 14400.0,
    **relax_params,
) -> dict:
    """Greedy 1–``max_edits`` discrete skip FINE-TUNER (Phase 5, re-scoped).

    Starts from a CONVERGED uniform design (net twist ≈ 0) and proposes a handful of single-skip
    edits at LOCAL deviation hotspots (:func:`skip_finetune.identify_finetune_edits`), applying
    each only if a high-confidence re-simulation shows it REDUCES the worst local deviation
    (``dev_max``) by ≥ ``dev_improve_nm`` while keeping |net twist| ≤ ``tol_twist_deg``.  Edits are
    net-twist-safe by scale (one skip ≈ 0.2° of a full-scale correction), so this fine-tunes the
    LOCAL profile without the register upheaval of wholesale redistribution.  Does no harm when no
    hotspot clears the noise floor (0 edits).  Returns ``{status, n_candidates, edits_kept, before,
    after, converged_skips}``."""
    from backend.api.headless_oxdna_build import STANDARD_RELAX_PARAMS
    from backend.core.skip_finetune import (
        apply_finetune_edit,
        current_skips_by_helix,
        identify_finetune_edits,
    )

    relax_params = {**STANDARD_RELAX_PARAMS, **relax_params}
    kw = dict(
        n_prod=n_prod,
        production_steps=production_steps,
        timeout=timeout,
        on_job=on_job,
        **relax_params,
    )

    def emit(ev):
        if on_progress:
            on_progress(ev)

    base = converged_design
    before = _finetune_measure(base, workspace, **kw)
    if before is None:
        return {
            "status": "error",
            "error": "baseline simulation failed",
            "edits_kept": [],
            "n_candidates": 0,
        }
    emit({"phase": "baseline", "twist": before["twist"], "dev_max": before["dev_max"]})

    candidates = identify_finetune_edits(
        base,
        before["deviation_by_bp"],
        before["shape_profile"],
        max_edits=max_edits,
        sigma=sigma,
        min_spacing=min_spacing,
    )
    emit({"phase": "candidates", "n": len(candidates)})

    cur_skips = current_skips_by_helix(base)
    best = before
    kept: list[dict] = []
    for i, edit in enumerate(candidates):
        if should_stop and should_stop():
            break
        trial_skips = apply_finetune_edit(cur_skips, edit)
        trial = build_explicit_skip_from_design(base, trial_skips)
        m = _finetune_measure(trial, workspace, **kw)
        if m is None:
            continue
        accept = (
            abs(m["twist"]) <= tol_twist_deg
            and m["dev_max"] <= best["dev_max"] - dev_improve_nm
        )
        emit(
            {
                "phase": "edit",
                "i": i,
                **edit,
                "twist": m["twist"],
                "dev_max": m["dev_max"],
                "accepted": accept,
            }
        )
        if accept:
            cur_skips, best = trial_skips, m
            kept.append({**edit, "twist": m["twist"], "dev_max": m["dev_max"]})

    out = {
        "status": "done",
        "n_candidates": len(candidates),
        "edits_kept": kept,
        "before": {
            "twist": before["twist"],
            "dev_max": before["dev_max"],
            "dev_mean": before["dev_mean"],
        },
        "after": {
            "twist": best["twist"],
            "dev_max": best["dev_max"],
            "dev_mean": best["dev_mean"],
        },
        "converged_skips": cur_skips,
    }
    emit({"phase": "done", **out})
    return out


def prepare_design_for_autorefine(design):
    """Ensure a design is oxDNA-ready for autorefine, returning ``(prepared_design, did_prep)``.

    Autorefine refines FROM the analytical skip pattern, so the design must already carry skips
    AND a full sequence.  If the user has not applied the default skip/loop feature and generated
    sequences (no skip marks, or any undefined 'N' base), do it here: lay the analytical seed
    period (their existing density if any, else the literature 48 bp) and re-sequence via
    :func:`build_sq_skip_from_design`.  A design that already has skips and is fully sequenced is
    returned unchanged (preserving any hand-tuned pattern)."""
    from backend.physics.oxdna_interface import count_undefined_bases

    has_skips = any(h.loop_skips for h in design.helices)
    undefined, _ = count_undefined_bases(design, exclude_reference=True)
    if has_skips and undefined == 0:
        return design, False
    return build_sq_skip_from_design(design, seed_skip_period(design)), True


_GEOMETRY_CONSTRAINT = {"measure": "geometry_match", "target_nm": 0.0}


def seed_skip_period(
    design, *, default: int = SQ_SKIP_PERIOD_DEFAULT, p_min: int = 8, p_max: int = 400
) -> int:
    """The skip period the autorefine's FIRST iteration should start from.

    If the design carries no loop/skips, returns the literature-standard ``default``
    (48 bp — one deletion per 48 bp, the Dietz/Douglas/Shih "add loops/skips" pattern),
    so iteration 0 begins at the standard correction rather than from a bare bundle.  If
    the design ALREADY has marks, returns the effective period of that pattern (total
    core length / marks-per-helix) so the loop refines from the design's current state
    instead of resetting it.  Clamped to ``[p_min, p_max]``."""
    helices = list(design.helices)
    total = sum(len(h.loop_skips) for h in helices)
    if total == 0 or not helices:
        return default
    avg_len = sum(max(1, h.length_bp) for h in helices) / len(helices)
    avg_marks = total / len(helices)
    period = int(round(avg_len / avg_marks)) if avg_marks > 0 else default
    return max(p_min, min(p_max, period))


def _metrics_from_verdict(verdict) -> dict:
    """Pull both self-consistency metrics out of a verdict's steering block (present
    whichever measure gated): rmsd-to-design (nm) + signed global twist (deg)."""
    steering = (verdict or {}).get("steering") or {}
    return {
        "rmsd_nm": steering.get("geometry_rmsd_nm", (verdict or {}).get("measured_nm")),
        "twist_residual_deg": steering.get("bundle_twist_residual_deg"),
    }


def measure_design_self_consistency(
    design,
    workspace,
    *,
    tol_nm: float,
    min_confidence: int,
    production_steps: int,
    max_production_rounds: int,
    timeout: float,
    screen_steps=None,
    should_stop=None,
    on_job=None,
    **relax_params,
) -> dict:
    """Relax + produce ``design`` once and score its simulated mean structure against
    its own straight ANALYTIC geometry.  Returns ``{rmsd_nm, twist_residual_deg,
    n_frames, status, job_id}`` (or ``{error}``) — the single-design measurement the
    autorefine BEFORE baseline is built from.  Physical-layer read-only."""
    from backend.api.headless_oxdna_build import _pool_until_conclusive, run_relaxation
    from backend.core.oxdna_health import parse_constraint_spec

    reference = core_reference_geometry(design)
    job = run_relaxation(design, workspace, timeout=timeout, **relax_params)
    if on_job:
        on_job(job)
    if job.status.value != "completed":
        return {
            "error": job.error or "relaxation did not complete",
            "job_id": job.job_id,
            "stopped": bool(should_stop and should_stop()),
        }
    parsed = parse_constraint_spec(
        {**_GEOMETRY_CONSTRAINT, "tol_nm": tol_nm, "min_confidence": min_confidence}
    )
    verdict, _rounds = _pool_until_conclusive(
        job,
        workspace,
        parsed,
        production_steps=production_steps,
        max_production_rounds=max_production_rounds,
        timeout=timeout,
        reference=reference,
        should_stop=should_stop,
        screen_steps=screen_steps,
    )
    return {
        **_metrics_from_verdict(verdict),
        "n_frames": verdict["n_frames"],
        "status": verdict["status"],
        "job_id": job.job_id,
    }


def autorefine_sq_design(
    base_design,
    workspace,
    *,
    on_progress=None,
    should_stop=None,
    on_job=None,
    tol_nm: float = 2.0,
    tol_twist_deg: float = 5.0,
    min_confidence: int = 400,
    baseline_min_confidence: int = 100,
    initial_period: int | None = None,
    max_iterations: int = 6,
    production_steps: int = 8_000_000,
    screen_steps: int = 2_000_000,
    max_production_rounds: int = 6,
    early_reject_factor: float = 3.0,
    regional: bool = False,
    w_dev: float = 1.0,
    w_strain: float = 0.25,
    min_spacing: int = 4,
    finetune: bool = False,
    finetune_max_edits: int = 5,
    finetune_sigma: float = 1.0,
    equilibration_steps: int = 10_000_000,
    timeout: float = 14400.0,
    **relax_params,
) -> dict:
    """Autorefine a square-lattice design's skip pattern until its oxDNA simulation
    matches the geometry it depicts, and report a BEFORE/AFTER score comparison.

    BEFORE = the design exactly as loaded (its current skips).  AFTER = the refined
    design (tuned skip period).  The FIRST iteration seeds from :func:`seed_skip_period`
    — the literature-standard "add loops/skips" 48-bp pattern when the design has no
    marks, else the design's existing skip density — so it starts at the standard
    correction (override with an explicit ``initial_period``).

    The STOP GATE is chosen by design type: a plain square-lattice bundle (no bend/twist
    deformation) gates on **bundle_twist** (target 0°, ``tol_twist_deg``) — the sensitive,
    CG-floor-free metric, because geometry_match RMSD is too insensitive to a distributed
    global twist on a large bundle (it falsely "converges" while the bundle stays
    twisted).  A curved/twisted design gates on geometry_match RMSD (``tol_nm``), where
    deviation-from-design IS the target.  ``primary_metric`` reports which (``global_twist_deg``
    vs ``deviation_nm``); both metrics are always shown in before/after.

    EFFICIENCY: each iteration runs a short ``screen_steps`` round first and EARLY-REJECTS
    a grossly-off skip period (> ``early_reject_factor`` x tol) without pooling to full
    confidence — high confidence is needed only to ACCEPT.  Only near-tolerance iterations
    pool the longer ``production_steps`` rounds up to ``min_confidence``.  The baseline uses
    a cheaper ``baseline_min_confidence`` (it only needs a ballpark starting deviation).

    Returns ``{status, converged_period, primary_metric, before, after, iterations}``.
    Three-Layer Law: only the skip TOPOLOGY is tuned; relaxed coordinates are read to
    score, never written back.
    """
    from backend.api.headless_oxdna_build import (
        STANDARD_RELAX_PARAMS,
        iterate_to_constraint,
    )

    # Autorefine is ALWAYS a real-engine (CUDA) run, so default to a REAL relaxation
    # (md_relax 1e6 + min_bp_retained 0.5), not create_job's mock-oriented 100-step
    # defaults.  A 100-step "relaxation" leaves a skipped square bundle badly
    # under-relaxed, so its unbiased production immediately goes numerically unstable
    # and blows up — the dt-halving gate then exhausts its retries and marks the
    # production stage ``failed``, after which the next pooling round's append 400s
    # ("Production requires a completed relaxation job").  Explicit caller params win.
    #
    # EQUILIBRATION (exp34, 2026-06-29): the global twist of a long square bundle has a
    # ~5M-step relaxation transient (the built/over-wound seed unwinding); the stock
    # ``equil_steps`` of 100k is ~50x too short, so the MEASURED production starts badly
    # unequilibrated and reads a biased, drifting twist (the ±9° "noise" that derailed
    # exp31/exp32 was this transient, not sampling — see project_skip_twist_curvature_sweep
    # + LESSONS A8).  Default the equil stage to ``equilibration_steps`` (~10M, unbiased MD)
    # so production begins post-transient and the pooled twist is the true equilibrium value.
    relax_params = {
        **STANDARD_RELAX_PARAMS,
        "equil_steps": equilibration_steps,
        **relax_params,
    }

    # Auto-prepare: if the user hasn't applied the default skip/loop pattern AND generated
    # sequences, do it now (analytical seed period + full sequence) — otherwise the baseline +
    # iterations fail with "undefined bases".  Autorefine then refines from this analytical start.
    base_design, _prepared = prepare_design_for_autorefine(base_design)
    if _prepared and on_progress:
        on_progress({"phase": "prepared"})

    plain_sq = not getattr(base_design, "deformations", None)
    primary = "global_twist_deg" if plain_sq else "deviation_nm"
    # First iteration starts at the literature-standard "add loops/skips" pattern (48 bp)
    # when the design has none, else from its existing skip density (refine in place).
    seed_period = (
        int(initial_period)
        if initial_period is not None
        else seed_skip_period(base_design)
    )
    if on_progress:  # surface the starting pattern so the UI can apply it immediately
        on_progress({"phase": "seed", "period": seed_period})
    constraint = (
        {
            "measure": "bundle_twist",
            "target_nm": 0.0,
            "tol_nm": tol_twist_deg,
            "min_confidence": min_confidence,
        }
        if plain_sq
        else {
            "measure": "geometry_match",
            "target_nm": 0.0,
            "tol_nm": tol_nm,
            "min_confidence": min_confidence,
        }
    )

    # BEFORE = design as loaded — a cheap, ballpark baseline (low confidence is fine; it
    # only shows the starting deviation, it is not a gate).
    before = measure_design_self_consistency(
        base_design,
        workspace,
        tol_nm=tol_nm,
        min_confidence=baseline_min_confidence,
        production_steps=production_steps,
        max_production_rounds=max_production_rounds,
        timeout=timeout,
        screen_steps=screen_steps,
        should_stop=should_stop,
        on_job=on_job,
        **relax_params,
    )
    if on_progress:
        on_progress({"phase": "before", **before})
    if should_stop and should_stop():  # stopped during the baseline measurement
        out = {
            "status": "stopped",
            "converged_period": None,
            "primary_metric": primary,
            "before": before,
            "after": {},
            "iterations": [],
        }
        if on_progress:
            on_progress({"phase": "done", **out})
        return out

    # Placement strategy: uniform period (textbook) OR regional (Phase 5) — the secant
    # still sets the per-helix deletion COUNT via the period (net-twist gate); regional
    # only redistributes that count by the prior round's deviation+strain fields, harvested
    # by ``on_measure`` into a closure the next build reads.  First iteration: empty fields
    # => uniform-equivalent.
    _state = {"deviation": {}, "strain": {}, "design": None}
    if regional:

        def _build(period):
            return build_regional_skip_design(
                base_design,
                period,
                _state["deviation"],
                _state["strain"],
                w_dev=w_dev,
                w_strain=w_strain,
                min_spacing=min_spacing,
            )

        def _on_measure(design, reference, job, ws):
            dev, strn = measure_skip_fields(job, ws, design, reference)
            # The just-measured design is the candidate for THIS knob; keep it so the
            # converged regional (non-uniform) pattern can be applied EXACTLY later
            # (re-deriving from the period alone would re-lay it uniformly).
            _state["deviation"], _state["strain"], _state["design"] = dev, strn, design

        build_fn, on_measure = _build, _on_measure
    else:
        build_fn, on_measure = (
            (lambda p: build_sq_skip_from_design(base_design, p)),
            None,
        )

    result = iterate_to_constraint(
        build_fn=build_fn,
        adjust_fn=PeriodAdjuster(),
        constraint=constraint,
        workspace=workspace,
        initial_knob=seed_period,
        reference_fn=core_reference_geometry,
        max_iterations=max_iterations,
        production_steps=production_steps,
        max_production_rounds=max_production_rounds,
        timeout=timeout,
        should_stop=should_stop,
        on_job=on_job,
        early_reject_factor=early_reject_factor,
        screen_steps=screen_steps,
        on_measure=on_measure,
        on_iteration=(
            lambda rec: on_progress(
                {
                    "phase": "iteration",
                    "period": rec["knob"],
                    **(rec.get("verdict") or {}),
                }
            )
        )
        if on_progress
        else None,
        **relax_params,
    )

    av = result.get("verdict") or {}
    after = {
        **_metrics_from_verdict(av),
        "n_frames": av.get("n_frames"),
        "status": av.get("status"),
        "period": result.get("knob"),
    }
    out = {
        "status": result["status"],
        "converged_period": result["knob"],
        "primary_metric": primary,
        "placement": "regional" if regional else "uniform",
        "before": before,
        "after": after,
        "iterations": [
            {
                "period": it["knob"],
                **_metrics_from_verdict(it.get("verdict")),
                "early_reject": bool((it.get("verdict") or {}).get("early_reject")),
                "status": (it.get("verdict") or {}).get("status"),
            }
            for it in result["iterations"]
        ],
    }
    # Regional: carry the EXACT converged non-uniform deletion pattern so the apply route
    # can lay it verbatim (the converged_period alone would re-derive a uniform pattern).
    if regional and _state.get("design") is not None:
        fd = _state["design"]
        out["converged_skips"] = {
            h.id: sorted(ls.bp_index for ls in h.loop_skips if ls.delta == -1)
            for h in fd.helices
            if any(ls.delta == -1 for ls in h.loop_skips)
        }

    # Optional Phase-5 FINE-TUNE pass: once the uniform secant has converged net twist, add/remove
    # a HANDFUL of single skips at local deviation hotspots (greedy, net-twist-safe — one edit is
    # ~0.2° of a full-scale correction).  Runs only on a usable converged period, not stopped.
    if (
        finetune
        and not regional
        and result.get("knob") is not None
        and out["status"] in ("met", "exhausted")
        and not (should_stop and should_stop())
    ):

        def _ft_progress(ev):
            if on_progress:
                on_progress(
                    {
                        "phase": "finetune",
                        "ft_phase": ev.get("phase"),
                        "i": ev.get("i"),
                        "op": ev.get("op"),
                        "helix_id": ev.get("helix_id"),
                        "bp_index": ev.get("bp_index"),
                        "accepted": ev.get("accepted"),
                        "dev_max": ev.get("dev_max"),
                        "twist": ev.get("twist"),
                        "n": ev.get("n"),
                    }
                )

        converged_design = build_sq_skip_from_design(base_design, int(result["knob"]))
        ft = greedy_finetune_skips(
            converged_design,
            workspace,
            max_edits=finetune_max_edits,
            tol_twist_deg=tol_twist_deg,
            sigma=finetune_sigma,
            on_progress=_ft_progress,
            should_stop=should_stop,
            on_job=on_job,
            timeout=timeout,
            **relax_params,
        )
        out["finetune"] = {
            k: ft.get(k)
            for k in ("status", "n_candidates", "edits_kept", "before", "after")
        }
        out["placement"] = "finetuned"
        if ft.get(
            "converged_skips"
        ):  # final fine-tuned pattern → apply lays it verbatim
            out["converged_skips"] = ft["converged_skips"]

    if on_progress:
        on_progress({"phase": "done", **out})
    return out


def iterate_sq_skips(
    cells,
    length_bp: int,
    workspace,
    *,
    tol_twist_deg: float = 5.0,
    min_confidence: int = 400,
    initial_period: int = SQ_SKIP_PERIOD_DEFAULT,
    max_iterations: int = 6,
    scaffold: str | None = None,
    p_min: int = 8,
    p_max: int = 400,
    early_reject_factor: float = 3.0,
    **iterate_kwargs,
) -> dict:
    """Closed build -> relax -> measure -> adjust loop that tunes the square-lattice
    skip period until the simulated mean structure matches the straight analytic
    geometry (build-from-cells path; the validation harness analog of
    :func:`autorefine_sq_design`).

    Gates on **bundle_twist** (target 0°, ``tol_twist_deg``) — the sensitive, CG-floor-
    free metric (geometry_match RMSD is too insensitive to a distributed global twist on
    a large bundle and falsely "converges"; see the full-scale post-mortem).  Steers on
    the signed twist via :class:`PeriodAdjuster`, uses ``core_reference_geometry`` as the
    per-iteration analytic reference, and EARLY-REJECTS grossly-off periods.  Extra kwargs
    (``production_steps``, ``screen_steps``, ``timeout``, relax params, …) pass through.
    Returns ``iterate_to_constraint``'s ``{status, knob, job, iterations, verdict}``."""
    from backend.api.headless_oxdna_build import iterate_to_constraint

    constraint = {
        "measure": "bundle_twist",
        "target_nm": 0.0,
        "tol_nm": tol_twist_deg,
        "min_confidence": min_confidence,
    }
    return iterate_to_constraint(
        build_fn=lambda p: build_sq_skip_design(cells, length_bp, p, scaffold=scaffold),
        adjust_fn=PeriodAdjuster(p_min=p_min, p_max=p_max),
        constraint=constraint,
        workspace=workspace,
        initial_knob=int(initial_period),
        reference_fn=core_reference_geometry,
        max_iterations=max_iterations,
        early_reject_factor=early_reject_factor,
        **iterate_kwargs,
    )
