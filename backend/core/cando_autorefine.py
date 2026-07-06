"""CanDo-FEM autorefine — Phase-5 Item 4.

Greedy loop/skip placement refinement driven by the FAST in-process CanDo FEM shape
oracle (``fem_solver.predict_shape`` → ``cando_deviation.compute_deviation``), replacing
the hours-long oxDNA CUDA simulation that the square-lattice self-consistency loop
(:mod:`backend.api.skip_twist_tuning`) uses.  Because a linear FEM solve is ~seconds on a
6HB/210, the greedy single-edit inner loop that was impractical with oxDNA becomes routine.

**Objective** = shrink the Item-3 deviation RMSD: the per-nucleotide distance between the
FEM-predicted relaxed shape and the design's INTENDED (displayed) geometry — i.e. make the
loop/skip program actually realise the bend/twist the user drew.  This is a mirror of
:func:`backend.api.skip_twist_tuning.greedy_finetune_skips`, with the FEM oracle swapped in
for the pooled oxDNA measurement.

**Edit strategy (topology-safe).**  Deciding whether a hotspot wants an added deletion, an
added loop, or a removed mark is a *directional / topological* judgement — which this module
NEVER makes geometrically (see CLAUDE.md's DNA-topology rule + [[feedback_crossover_no_reasoning]]).
Instead every candidate edit is TRIED and the FEM oracle empirically keeps whichever lowers
the RMSD.  Two modes, per the user's split:

  * **square lattice** → candidate edits are ADD-skip / REMOVE-mark only (deletion-only space,
    matching the oxDNA finetuner);
  * **twist/bend designs** (honeycomb) → also ADD-loop, so a hotspot can be corrected by
    lengthening (loop, +1) as well as shortening (skip, −1).

**Placement is off-crossover / off-end.**  Auto-placed marks must never sit on a crossover bp
or a strand terminus/nick ([[feedback_loopskip_no_crossover_ends]] — CanDo crashes on such
files).  ``free_interior_candidates`` filters ``core_candidates`` down to crossover-free,
endpoint-free, end-margin-free interior bp before any ADD.

Three-Layer Law: this module reads topology and predicts a Physical-layer shape; it returns a
proposed loop/skip mark set but NEVER mutates the active design.  The REST ``apply`` route lands
the converged marks as a reversible feature-log entry.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Optional

from backend.core.models import Design, LatticeType

# bp kept clear of each helix's duplex ends (mirrors the exp36 battery generator's END_MARGIN).
END_MARGIN = 6

# Accept a SQUARE refinement's end-to-end twist once it lands within this many degrees of the
# design's INTENDED twist.  exp37 (experiments/exp37_cando_skip_twist_map) mapped the 3x6x400 SQ
# landscape and drove twist 14.3°→0.37° — 1° is comfortably reachable by fractional skip density.
TWIST_TOL_DEG = 1.0

# HONEYCOMB coupled (twist, bend) objective (exp38/exp40).  Accept bend within this many degrees of
# the intended bend — generous because the continuum FEM intrinsically realises only ~92% of a
# programmed bend (exp36; G1 residual ~4° on a 60° bend).  And only ENGAGE the bend row of the
# Jacobian when the intended bend exceeds the arc-bend estimator noise floor (exp40 G3: below ~this,
# the bend signal is noise and the coupled solve chases it — twist-only is better).
BEND_TOL_DEG = 3.0
BEND_TARGET_FLOOR_DEG = 3.0


def _twist_error(measure: Optional[dict], target_twist_deg: float) -> float:
    """|FEM end-to-end twist − INTENDED twist| for a :func:`fem_measure` result.  The intended
    twist is the target (often 0 for a straight strut, but non-zero for a programmed-twist design);
    measuring the DIFFERENCE cancels the ~fixed lattice offset in ``measure_bundle_twist`` (its
    docstring: "USE DIFFERENTIALLY") and generalises to honeycomb designs whose intended shape
    carries both bend and twist.  Returns ``inf`` for a missing measure / unresolvable twist so a
    failed solve never looks optimal."""
    if measure is None:
        return float("inf")
    tw = measure.get("twist_deg")
    if tw is None:
        return float("inf")
    return abs(float(tw) - float(target_twist_deg))


# ── Deviation field + hotspot ranking (mechanical: highest positional error) ────────────────

def aggregate_deviation_by_bp(positions: list[dict]) -> dict[tuple[str, int], float]:
    """Collapse a :func:`compute_deviation` per-nucleotide list to a per-(helix, bp) field by
    averaging the deviation across the two strand directions and any loop copies at each station."""
    acc: dict[tuple[str, int], list[float]] = defaultdict(list)
    for p in positions:
        acc[(p["helix_id"], int(p["bp_index"]))].append(float(p["deviation"]))
    return {k: sum(v) / len(v) for k, v in acc.items()}


def rank_hotspots(deviation_by_bp: dict[tuple[str, int], float], *,
                  sigma: float = 1.0, max_hotspots: int = 8,
                  min_spacing: int = 8) -> list[tuple[str, int]]:
    """The up-to-``max_hotspots`` worst deviation stations, most-severe first.

    A hotspot must exceed ``mean + sigma·std`` of the whole field, so a uniform / already-good
    field yields NO hotspots (the refiner does no harm when there is nothing local to fix — the
    same noise-floor gate as :func:`skip_finetune.identify_finetune_edits`).  Stations within
    ``min_spacing`` bp of an already-chosen one on the same helix are skipped so edits stay spread.
    """
    if not deviation_by_bp:
        return []
    vals = list(deviation_by_bp.values())
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    threshold = mean + sigma * std
    ranked = sorted((kv for kv in deviation_by_bp.items() if kv[1] > threshold),
                    key=lambda kv: kv[1], reverse=True)
    chosen: list[tuple[str, int]] = []
    for (hid, bp), _dev in ranked:
        if len(chosen) >= max_hotspots:
            break
        if any(h2 == hid and abs(bp - b2) < min_spacing for h2, b2 in chosen):
            continue
        chosen.append((hid, bp))
    return chosen


# ── Off-crossover / off-end candidate placement ([[feedback_loopskip_no_crossover_ends]]) ───

def _forbidden_bps(design: Design) -> tuple[dict[str, set[int]], dict[str, tuple[int, int]]]:
    """Per helix: the bp an auto mark must NOT land on (crossover bp + strand domain endpoints
    + a duplex-end margin) and the ``(lo, hi)`` interior range.  Mirrors the exp36 generator's
    ``_forbidden_bps`` so the live refiner enforces the same rule the battery does."""
    from backend.core.crossover_positions import extract_crossovers_from_strands

    forb: dict[str, set[int]] = {h.id: set() for h in design.helices}
    interior: dict[str, tuple[int, int]] = {}
    # Crossovers from strand TOPOLOGY (design.crossovers is often empty on loaded designs).
    try:
        xos, _ = extract_crossovers_from_strands(
            design.strands, design.helices, design.lattice_type)
    except Exception:  # noqa: BLE001
        xos = list(getattr(design, "crossovers", []) or [])
    for xo in xos:
        for half in (xo.half_a, xo.half_b):
            if half.helix_id in forb:
                forb[half.helix_id].add(half.index)
    cov: dict[str, set[int]] = {h.id: set() for h in design.helices}
    for s in design.strands:
        if getattr(s, "is_reference", False):
            continue
        for dm in s.domains:
            if dm.helix_id not in forb:
                continue
            forb[dm.helix_id].add(dm.start_bp)
            forb[dm.helix_id].add(dm.end_bp)
            cov[dm.helix_id].update(range(min(dm.start_bp, dm.end_bp),
                                          max(dm.start_bp, dm.end_bp) + 1))
    for hid, bps in cov.items():
        if bps:
            lo, hi = min(bps), max(bps)
            interior[hid] = (lo + END_MARGIN, hi - END_MARGIN)
            for b in range(lo, lo + END_MARGIN):
                forb[hid].add(b)
            for b in range(hi - END_MARGIN + 1, hi + 1):
                forb[hid].add(b)
        else:
            interior[hid] = (0, -1)
    return forb, interior


def free_interior_candidates(design: Design, helix, forbidden: set[int]) -> list[int]:
    """dsDNA-core bp on ``helix`` where a NEW auto mark may legally be placed: ``core_candidates``
    (both tracks present, not already marked) minus the ``forbidden`` set (crossovers / endpoints /
    end margin).  ``forbidden`` is precomputed once per design via :func:`_forbidden_bps`."""
    from backend.core.regional_skip_placer import core_candidates
    return [bp for bp in core_candidates(design, helix) if bp not in forbidden]


# ── Mark bookkeeping + trial builds (pure / topological) ────────────────────────────────────

def current_marks_by_helix(design: Design) -> dict[str, dict[int, int]]:
    """``{helix_id: {bp_index: delta}}`` for the design's existing loop/skips (delta −1 skip, +1 loop)."""
    return {h.id: {ls.bp_index: ls.delta for ls in h.loop_skips}
            for h in design.helices if h.loop_skips}


def build_refined_design(base_design: Design, marks_by_helix: dict[str, dict[int, int]]) -> Design:
    """Lay the converged ``{helix_id: {bp_index: delta}}`` mark set on ``base_design`` and
    RE-SEQUENCE (delta-aware, any lattice) — the APPLY path (unlike the fast inner-loop
    :func:`apply_marks`, which skips re-sequencing).  Changing the mark set shifts every downstream
    base, so staples must be re-complemented or the design's sequences go non-Watson-Crick.  Clears
    existing loop/skips first, applies the converged set, re-sequences, and returns a detached copy.

    Runs inside an isolated headless scratch document (its own doc id), so it never disturbs the
    live design/document — the caller hands the returned design to ``mutate_with_feature_log`` as a
    pure replacement (build OUTSIDE the mutate callback to avoid the state-lock self-deadlock).
    Shared by the REST apply route and the autorefine JOB runner."""
    from backend.api import headless_build as hb
    from backend.api import state as ds
    from backend.api.skip_twist_tuning import _select_scaffold
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.models import LoopSkip

    with hb.scratch_session(base_design.lattice_type):
        ds.set_design(base_design.model_copy(deep=True))
        d = clear_all_loop_skips(ds.get_or_404())
        mods = {hid: [LoopSkip(bp_index=int(bp), delta=int(dl)) for bp, dl in sorted(bps.items())]
                for hid, bps in (marks_by_helix or {}).items() if bps}
        if mods:
            d = apply_loop_skips(d, mods)
        ds.set_design(d)
        hb.full_sequence(scaffold_name=_select_scaffold(ds.get_or_404(), None))
        return ds.get_or_404().model_copy(deep=True)


def apply_marks(base_design: Design, marks_by_helix: dict[str, dict[int, int]]) -> Design:
    """Return a copy of ``base_design`` whose loop/skips are EXACTLY ``marks_by_helix``
    (clear-then-apply).  Pure/topological and — deliberately — does NOT re-sequence: the FEM
    oracle reads duplex-coverage geometry, not base letters, so skipping the (slow) full-sequence
    rebuild keeps the inner loop fast.  The REST apply route re-sequences before landing on the
    real design (staple complementarity would otherwise drift — see routes_cando_autorefine)."""
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.models import LoopSkip

    d = clear_all_loop_skips(base_design)
    mods = {hid: [LoopSkip(bp_index=int(bp), delta=int(dl)) for bp, dl in sorted(bps.items())]
            for hid, bps in marks_by_helix.items() if bps}
    if mods:
        d = apply_loop_skips(d, mods)
    return d


def periodic_skip_marks(design: Design, period: int) -> dict[str, dict[int, int]]:
    """A UNIFORM periodic-skip mark set at ``period`` bp for a SQUARE-lattice design, relocated off
    crossovers/ends — ``{helix_id: {bp_index: -1}}``.

    This is the density knob the SQUARE register over-twist is tuned with: one deletion every
    ``period`` bp on every helix (staggered by helix index, via
    :func:`loop_skip_calculator.sq_lattice_periodic_skips`), then any mark that landed on a
    crossover / strand end / margin is moved to the nearest free interior bp
    ([[feedback_loopskip_no_crossover_ends]]).  **Skips only** — the register over-twist is relieved
    by DELETIONS, never loops.  Returns ``{}`` for a non-square design (no register-twist knob) or a
    period that lands nothing.  Mirrors :func:`skip_twist_tuning.build_sq_skip_from_design` but WITHOUT
    the (slow) re-sequence — the FEM oracle reads geometry, not base letters (see :func:`apply_marks`).
    """
    from backend.core.loop_skip_calculator import (
        clear_all_loop_skips, relocate_marks_off_forbidden, sq_lattice_periodic_skips,
    )
    if design.lattice_type != LatticeType.SQUARE or period < 1:
        return {}
    base = clear_all_loop_skips(design.model_copy(deep=True))
    mods = sq_lattice_periodic_skips(base, int(period))
    try:
        mods = relocate_marks_off_forbidden(mods, base)
    except Exception:  # noqa: BLE001 — relocation is best-effort; a bad bp is simply dropped
        pass
    return {hid: {int(ls.bp_index): int(ls.delta) for ls in lss}
            for hid, lss in mods.items() if lss}


# ── The FEM oracle: one linear/nonlinear solve → deviation RMSD + field ──────────────────────

def fem_measure(design: Design, *, nonlinear: bool = False) -> Optional[dict]:
    """Run the CanDo FEM shape oracle once on ``design`` and return
    ``{rmsd, dev_max, dev_mean, n, deviation_by_bp, shape}`` — the RMSD is the objective the greedy
    loop minimises, ``deviation_by_bp`` steers the next round's hotspots, and ``shape`` (the raw
    ``predict_shape`` output) is retained so twist/bend can be measured for the status readout
    WITHOUT a second solve.

    Returns ``None`` when the design has no double-helical core to solve (``predict_shape`` raises
    ``ValueError`` on <2 duplex bp) so the caller can bail cleanly instead of crashing.
    """
    from backend.core.cando_deviation import compute_deviation
    from backend.physics.fem_solver import predict_shape

    try:
        shape = predict_shape(design, nonlinear=nonlinear, with_rmsf=False)
    except ValueError:
        return None
    dev = compute_deviation(design, shape["positions"])
    # Measure the FEM shape's end-to-end twist + bend off the SAME cached solve (no second solve) so
    # every trial carries a twist number — the primary objective for the SQUARE register over-twist.
    tb = _measure_twist_bend(shape["positions"], _core_keys(shape))
    return {
        "rmsd":            dev["rmsd_nm"],
        "dev_max":         dev["max_deviation"],
        "dev_mean":        dev["mean_deviation"],
        "n":               dev["n"],
        "deviation_by_bp": aggregate_deviation_by_bp(dev["positions"]),
        "twist_deg":       tb["twist_deg"],
        "bend_deg":        tb["bend_deg"],
        "shape":           shape,
    }


# ── Twist / bend readout for the live status (no extra solve; measured off the cached shape) ────

def _core_keys(shape: dict) -> set[tuple[str, int]]:
    """The duplex-core (helix, bp) stations of a ``predict_shape`` result (its axis nodes) —
    the rigid set to restrict twist/bend measurement to (ssDNA ends / loop copies have ill-defined
    cross-section centres, per ``measure_bundle_twist``'s 'pass the duplex CORE' guidance)."""
    return {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}


def _measure_twist_bend(positions: list[dict], core_keys: set[tuple[str, int]]) -> dict:
    """``{twist_deg, bend_deg}`` of a backbone-position list (restricted to ``core_keys``), reusing
    the shared bundle-shape estimators.  Either value is ``None`` if its estimator can't resolve
    (too few helices / degenerate axis) — the status then shows '—' rather than a bogus number."""
    from backend.core.oxdna_health import measure_bundle_arc_bend, measure_bundle_twist

    core = [p for p in positions if (p["helix_id"], int(p["bp_index"])) in core_keys]
    out: dict = {"twist_deg": None, "bend_deg": None}
    try:
        out["twist_deg"] = float(measure_bundle_twist(core))
    except Exception:      # noqa: BLE001 — degenerate geometry → leave None
        pass
    try:
        out["bend_deg"] = float(measure_bundle_arc_bend(core))   # chord-sagitta: true arc angle
    except Exception:      # noqa: BLE001
        pass
    return out


def _intended_positions(design: Design) -> list[dict]:
    """The design's INTENDED (displayed) backbone positions as a measurement list
    ``[{helix_id, bp_index, backbone_position}]`` — the same ``deformed_nucleotide_positions`` the
    deviation oracle targets.  Twist/bend of THIS is the target the FEM prediction is aiming at."""
    from backend.core.deformation import deformed_nucleotide_positions

    out: list[dict] = []
    for h in design.helices:
        for nuc in deformed_nucleotide_positions(h, design):
            pos = nuc.position
            out.append({"helix_id": nuc.helix_id, "bp_index": nuc.bp_index,
                        "backbone_position": [float(pos[0]), float(pos[1]), float(pos[2])]})
    return out


def target_metrics(base_design: Design, core_keys: set[tuple[str, int]]) -> dict:
    """The target the refiner aims at: ``{deviation:0.0, twist_deg, bend_deg}`` — deviation target
    is 0 (perfect match) and twist/bend are measured off the design's intended geometry with the
    SAME estimators used for the current prediction, so the two are directly comparable."""
    tb = _measure_twist_bend(_intended_positions(base_design), core_keys)
    return {"deviation": 0.0, "twist_deg": tb["twist_deg"], "bend_deg": tb["bend_deg"]}


def current_metrics(measure: dict, core_keys: set[tuple[str, int]]) -> dict:
    """The current prediction's ``{deviation, twist_deg, bend_deg}`` from a :func:`fem_measure`
    result (reuses its cached ``shape`` — no extra solve)."""
    tb = _measure_twist_bend(measure["shape"]["positions"], core_keys)
    return {"deviation": measure["rmsd"], "twist_deg": tb["twist_deg"], "bend_deg": tb["bend_deg"]}


# ── Candidate edit enumeration (try-both; direction chosen empirically by the oracle) ────────

def candidate_edits(hotspot: tuple[str, int], marks_by_helix: dict[str, dict[int, int]],
                    free_by_helix: dict[str, list[int]], *, allow_loops: bool) -> list[dict]:
    """The edits to TRY at one ``(helix, bp)`` hotspot.  Never decides direction — enumerates the
    whole applicable set and lets :func:`fem_refine` keep whichever the oracle says helps.

    Each edit is ``{helix_id, op, bp_index}`` where ``op`` ∈ {``add_skip``, ``add_loop``,
    ``remove``}.  ADD ops target the nearest FREE INTERIOR bp (off crossovers/ends); REMOVE targets
    the nearest EXISTING mark on the helix.  Square-lattice mode omits ``add_loop``.
    """
    hid, bp = hotspot
    edits: list[dict] = []
    free = free_by_helix.get(hid, [])
    if free:
        target = min(free, key=lambda c: abs(c - bp))
        edits.append({"helix_id": hid, "op": "add_skip", "bp_index": int(target)})
        if allow_loops:
            edits.append({"helix_id": hid, "op": "add_loop", "bp_index": int(target)})
    existing = list(marks_by_helix.get(hid, {}).keys())
    if existing:
        nearest = min(existing, key=lambda c: abs(c - bp))
        edits.append({"helix_id": hid, "op": "remove", "bp_index": int(nearest)})
    return edits


def _with_edit(marks_by_helix: dict[str, dict[int, int]], edit: dict) -> dict[str, dict[int, int]]:
    """Return a deep-ish copy of ``marks_by_helix`` with one ``candidate_edits`` edit applied."""
    out = {hid: dict(bps) for hid, bps in marks_by_helix.items()}
    hid, op, bp = edit["helix_id"], edit["op"], int(edit["bp_index"])
    cur = out.setdefault(hid, {})
    if op == "add_skip":
        cur[bp] = -1
    elif op == "add_loop":
        cur[bp] = +1
    elif op == "remove":
        cur.pop(bp, None)
    if not cur:
        out.pop(hid, None)
    return out


# ── Global skip-DENSITY search (SQUARE register over-twist) ──────────────────────────────────
# The per-hotspot greedy loop below can't navigate a GLOBAL twist objective: on a plain square
# strut the register over-twist spreads the deviation uniformly (no local hotspot exceeds the
# noise floor → 0 edits), and a single skip moves the RMSD only ~0.004 nm (below any sane accept
# bar).  The right knob is the whole-bundle skip DENSITY — one deletion every `period` bp — swept
# to minimise the FEM deviation-vs-intended RMSD, exactly as `skip_twist_tuning` sweeps the period
# to match the oxDNA twist, but with the fast in-process FEM oracle so a full sweep is seconds.


def _search_min_period(fn: Callable[[int], float], lo: int, hi: int) -> int:
    """Integer unimodal minimiser (ternary search) of ``fn`` on ``[lo, hi]`` — the RMSD-vs-period
    curve has a single well (validated on the SQ battery), so ternary converges in ~log steps.
    ``fn`` is expected to cache its solves (see :func:`sweep_skip_period`)."""
    lo, hi = int(lo), int(hi)
    while hi - lo > 2:
        m1 = lo + (hi - lo) // 3
        m2 = hi - (hi - lo) // 3
        if m2 <= m1:
            m2 = m1 + 1
        if fn(m1) <= fn(m2):
            hi = m2
        else:
            lo = m1
    return min(range(lo, hi + 1), key=fn)


def sweep_skip_period(base_design: Design, *, nonlinear: bool = False,
                      p_min: int = 8, p_max: int = 400, coarse_ratio: float = 1.4,
                      cost_fn: Optional[Callable[[Optional[dict]], float]] = None,
                      on_progress: Optional[Callable[[dict], None]] = None,
                      should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """Find the uniform skip PERIOD that minimises ``cost_fn`` of the FEM shape.

    ``cost_fn`` maps a :func:`fem_measure` result (or ``None`` on a failed/stopped solve) to a
    scalar to minimise; it defaults to the deviation RMSD (``m["rmsd"]``).  The SQUARE twist path
    passes a TWIST-ERROR cost (``_twist_error`` vs the design's intended twist) so the sweep lands
    the density that nulls the register over-twist rather than the one that minimises positional
    deviation — the two optima DIFFER (exp37: RMSD-min ≈ 10 skips/helix at +14° twist, twist-min ≈
    12.6 skips/helix), which is why a deviation-only sweep floors twist at ~10-15°.

    A coarse geometric pass over the period range (plus the 0-skip point) brackets the minimum,
    then a ternary refine finds the integer optimum — typically ~15-20 FEM solves, seconds each.
    Each candidate period ``p`` builds ``periodic_skip_marks(base_design, p)`` (skips only, off
    crossovers/ends) and measures it with the FEM oracle; every solve is cached so the coarse and
    fine passes never re-solve a period.

    Returns ``{status, best_period, best_marks, best_measure, baseline_measure, curve}`` where
    ``best_period`` is ``None`` when NO skip density beats the 0-skip design (skips never help),
    ``best_marks`` is the winning ``{helix_id:{bp:-1}}`` (``{}`` for ``None``), ``best_measure`` is
    its :func:`fem_measure` dict, and ``curve`` is the sampled ``[{period, n_skips, rmsd, twist,
    cost}]`` (for the panel / log).  ``status`` ∈ {done, stopped}.  Non-square designs get an empty
    knob → the 0-skip point is the only sample (``best_period=None``)."""
    cost = cost_fn or (lambda m: (m["rmsd"] if m else float("inf")))

    def emit(ev: dict) -> None:
        if on_progress:
            on_progress(ev)

    lens = [max(1, h.length_bp) for h in base_design.helices]
    avg_len = (sum(lens) / len(lens)) if lens else float(p_max)
    p_hi = max(p_min + 1, min(p_max, int(avg_len)))   # a period > helix length lands no skips

    curve: list[dict] = []
    cache: dict = {}   # period (int) or None → fem_measure dict (or None on stop/failure)

    def measure(period) -> Optional[dict]:
        if period in cache:
            return cache[period]
        if should_stop and should_stop():
            cache[period] = None
            return None
        marks = periodic_skip_marks(base_design, period) if period is not None else {}
        m = fem_measure(apply_marks(base_design, marks), nonlinear=nonlinear)
        cache[period] = m
        n = sum(len(v) for v in marks.values())
        rec = {"period": period, "n_skips": n, "rmsd": (m["rmsd"] if m else None),
               "twist": (m["twist_deg"] if m else None),
               "cost": (cost(m) if m else None)}
        curve.append(rec)
        emit({"phase": "density_trial", **rec})
        return m

    def cost_at(period) -> float:
        return cost(measure(period))

    # Coarse geometric periods (descending from the helix-length bound) + the 0-skip baseline.
    coarse: list[int] = []
    p = float(p_hi)
    while p >= p_min:
        ip = int(round(p))
        if ip >= p_min and ip not in coarse:
            coarse.append(ip)
        p /= coarse_ratio
    coarse = sorted(set(coarse))

    measure(None)                                     # 0-skip point (design with marks cleared)
    for ip in coarse:
        if should_stop and should_stop():
            break
        measure(ip)

    stopped = bool(should_stop and should_stop())
    finite = [ip for ip in coarse if cache.get(ip)]
    if finite and not stopped:
        p_star = min(finite, key=cost_at)             # best coarse period (by cost_fn)
        idx = coarse.index(p_star)
        a = coarse[idx - 1] if idx > 0 else max(p_min, p_star - 1)
        b = coarse[idx + 1] if idx < len(coarse) - 1 else min(p_hi, p_star + 1)
        _search_min_period(cost_at, a, b)             # fine refine (results land in cache/curve)

    measured = [k for k, v in cache.items() if v is not None]
    best_period = min(measured, key=lambda k: cost(cache[k])) if measured else None
    best_marks = periodic_skip_marks(base_design, best_period) if best_period is not None else {}
    best_measure = cache.get(best_period)
    out = {"status": "stopped" if stopped else "done",
           "best_period": best_period, "best_marks": best_marks,
           "best_measure": best_measure, "baseline_measure": cache.get(None),
           "curve": sorted(curve, key=lambda r: (r["period"] is not None, r["period"] or 0))}
    emit({"phase": "density_best", "period": best_period,
          "rmsd": (best_measure or {}).get("rmsd"),
          "baseline_rmsd": (cache.get(None) or {}).get("rmsd")})
    return out


# ── Fractional per-helix skip density (SQUARE twist nulling) ─────────────────────────────────
# The uniform density sweep steps ~5°/skip and STRADDLES the target twist (exp37: 12 skips/helix →
# +3.3°, 13 → −2.1°).  Fractional density — a subset of helices at N+1 — resolves inside ±1°.  This
# is the exp37 "spread" result (bump the highest twist-AUTHORITY helices, which turned out to be the
# 3×6 middle row), reached WITHOUT any geometric reasoning: authority is MEASURED per helix and every
# bump is empirically kept only if it lowers the twist error ([[feedback_crossover_no_reasoning]]).

def _even_place(free: list[int], n: int) -> list[int]:
    """``n`` evenly-spaced bp from the sorted free-interior candidate list.  Placement is
    twist-irrelevant on the FEM oracle (exp37 probe: <0.2° across placements at fixed count), so an
    even spread just makes the mark set deterministic + spacing-friendly."""
    free = sorted(free)
    if n <= 0 or not free:
        return []
    if n >= len(free):
        return list(free)
    idx = [round(i * (len(free) - 1) / (n - 1)) if n > 1 else (len(free) // 2) for i in range(n)]
    return sorted({free[i] for i in idx})


def _fractional_twist_bump(base_design: Design, *, base_count: int, target_twist_deg: float,
                           nonlinear: bool, twist_tol: float, forbidden: dict[str, set[int]],
                           free_base: dict[str, list[int]],
                           on_progress: Optional[Callable[[dict], None]] = None,
                           should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """From the swept UNIFORM density (``base_count`` skips/helix), bump individual helices by one
    skip toward ``target_twist_deg`` — highest MEASURED twist-authority first — until the end-to-end
    twist is within ``twist_tol`` of the intended twist, using the FEWEST added skips (least
    deviation cost).  Returns ``{marks, measure, authority, n_bumped, base_count}``."""
    helix_ids = [h.id for h in base_design.helices]

    def emit(ev: dict) -> None:
        if on_progress:
            on_progress(ev)

    cache: dict[tuple, tuple] = {}   # counts-signature → (measure, marks)

    def measure(counts: dict[str, int]):
        key = tuple(counts[h] for h in helix_ids)
        if key not in cache:
            mk = {h: {bp: -1 for bp in _even_place(free_base[h], counts[h])} for h in helix_ids}
            mk = {h: v for h, v in mk.items() if v}
            cache[key] = (fem_measure(apply_marks(base_design, mk), nonlinear=nonlinear), mk)
        return cache[key]

    counts0 = {h: base_count for h in helix_ids}
    m0, mk0 = measure(counts0)
    if m0 is None:
        return {"marks": mk0, "measure": None, "authority": {}, "n_bumped": 0,
                "base_count": base_count}
    err0 = _twist_error(m0, target_twist_deg)
    over = (m0.get("twist_deg") or 0.0) > target_twist_deg    # over-wound → ADD a skip (+1)
    step = 1 if over else -1

    # Authority probe: one single-helix bump each, from the uniform base (cached → reused below).
    authority: dict[str, float] = {}
    for h in helix_ids:
        if should_stop and should_stop():
            break
        nc = base_count + step
        if nc < 0 or nc > len(free_base[h]):
            continue
        m, _ = measure({**counts0, h: nc})
        if m is None or m.get("twist_deg") is None:
            continue
        authority[h] = float(m["twist_deg"]) - float(m0["twist_deg"] or 0.0)
        emit({"phase": "twist_authority", "helix_id": h, "dtwist": round(authority[h], 3)})

    # Rank helices by how hard they steer twist in the HELPFUL direction (over → most-negative
    # dtwist first), then greedily COMMIT real bumps until within tol or a bump stops helping.
    ranked = sorted(authority, key=lambda h: (authority[h] if over else -authority[h]))
    cur_counts = dict(counts0)
    cur_m, cur_err, nb = m0, err0, 0
    for h in ranked:
        if should_stop and should_stop():
            break
        if cur_err <= twist_tol:
            break
        nc = cur_counts[h] + step
        if nc < 0 or nc > len(free_base[h]):
            continue
        m, _ = measure({**cur_counts, h: nc})
        if m is None:
            continue
        e = _twist_error(m, target_twist_deg)
        if e < cur_err - 1e-9:
            cur_counts[h], cur_m, cur_err, nb = nc, m, e, nb + 1
            emit({"phase": "twist_bump", "helix_id": h, "count": nc, "twist_err": round(e, 3)})
        else:
            break                                     # overshoot: further same-direction bumps worsen
    _, final_mk = measure(cur_counts)
    return {"marks": final_mk, "measure": cur_m, "authority": authority, "n_bumped": nb,
            "base_count": base_count}


# ── Coupled (twist, bend) shape solve (HONEYCOMB / programmed-shape designs) ──────────────────
# exp38 (G1) + exp40 (G3): a per-helix skip moves BOTH twist and bend, and bend authority varies by
# cross-section position (bimetallic: inner-helix skips bend one way, outer the other) while twist
# authority is ~uniform → the 2×H authority Jacobian J is well-conditioned, so a ridge least-squares
# solve hits (twist_target, bend_target) jointly.  The bend row is ENGAGED only when the intended bend
# clears the estimator noise floor (G3) — else it degenerates to the twist-only least-squares.  Every
# edit is TRIED and kept only if it lowers the combined shape error (no geometric reasoning about
# direction — [[feedback_crossover_no_reasoning]]).

def _shape_error(tw, bd, tw_star, bd_star, use_bend):
    """Combined |twist−target| (+ |bend−target| when the bend row is engaged), in degrees."""
    e = abs((tw if tw is not None else 0.0) - tw_star)
    if use_bend and bd is not None and bd_star is not None:
        e += abs(bd - bd_star)
    return e


def _solve_shape_targets(base_design: Design, *, target_twist_deg: float,
                         target_bend_deg: Optional[float], nonlinear: bool,
                         forbidden: dict[str, set[int]], free_base: dict[str, list[int]],
                         allow_loops: bool, probe_skips: int = 4, max_iters: int = 4,
                         twist_tol: float = TWIST_TOL_DEG, bend_tol: float = BEND_TOL_DEG,
                         on_progress: Optional[Callable[[dict], None]] = None,
                         should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """Drive the FEM-predicted (twist, bend) to (``target_twist_deg``, ``target_bend_deg``) with a
    ridge least-squares solve on the MEASURED 2×H authority Jacobian, iterated.  Starts from the
    design's existing marks; each iteration re-probes the Jacobian (``probe_skips`` per helix ÷ count,
    so the bend row clears the noise floor — exp40 fix), solves ``min_x ‖J·x − residual‖² + λ‖x‖²``,
    realises the integer per-helix deltas (x>0 → skips, x<0 → loops when ``allow_loops``), and KEEPS
    the step only if it lowers the combined shape error.  ``target_bend_deg=None`` → twist-only row.

    Returns ``{marks, measure, authority, twist, bend, n_iters}`` where ``authority`` is
    ``{helix_id: [∂twist/∂skip, ∂bend/∂skip]}``."""
    import numpy as np

    use_bend = target_bend_deg is not None

    def emit(ev: dict) -> None:
        if on_progress:
            on_progress(ev)

    def measure(marks):
        return fem_measure(apply_marks(base_design, marks), nonlinear=nonlinear)

    helices = list(base_design.helices)
    cur = current_marks_by_helix(base_design)
    cur_m = measure(cur)
    if cur_m is None:
        return {"marks": cur, "measure": None, "authority": {}, "twist": None, "bend": None,
                "n_iters": 0}
    cur_tw, cur_bd = cur_m.get("twist_deg"), cur_m.get("bend_deg")
    cur_err = _shape_error(cur_tw, cur_bd, target_twist_deg, target_bend_deg, use_bend)
    authority: dict[str, list[float]] = {}
    n_iters = 0

    for it in range(max_iters):
        if should_stop and should_stop():
            break
        tw_ok = abs((cur_tw or 0.0) - target_twist_deg) <= twist_tol
        bd_ok = (not use_bend) or (cur_bd is not None
                                   and abs(cur_bd - target_bend_deg) <= bend_tol)
        if tw_ok and bd_ok:
            break
        n_iters = it + 1
        rows = 2 if use_bend else 1
        J = np.zeros((rows, len(helices)))
        for j, h in enumerate(helices):
            if should_stop and should_stop():
                break
            avail = [bp for bp in free_base[h.id] if bp not in cur.get(h.id, {})]
            picks = _even_place(avail, probe_skips)
            if not picks:
                continue
            trial = {k: dict(v) for k, v in cur.items()}
            trial.setdefault(h.id, {}).update({bp: -1 for bp in picks})
            m = measure(trial)
            if m is None or m.get("twist_deg") is None:
                continue
            dtw = (float(m["twist_deg"]) - float(cur_tw or 0.0)) / len(picks)
            J[0, j] = dtw
            if use_bend and m.get("bend_deg") is not None and cur_bd is not None:
                dbd = (float(m["bend_deg"]) - float(cur_bd)) / len(picks)
                J[1, j] = dbd
                authority[h.id] = [round(dtw, 4), round(dbd, 4)]
            else:
                authority[h.id] = [round(dtw, 4), 0.0]
        r = np.array([target_twist_deg - (cur_tw or 0.0)]
                     + ([target_bend_deg - (cur_bd or 0.0)] if use_bend else []))
        try:
            x = J.T @ np.linalg.solve(J @ J.T + 0.5 * np.eye(rows), r)
        except np.linalg.LinAlgError:
            break
        deltas = {h.id: int(round(x[j])) for j, h in enumerate(helices) if round(x[j]) != 0}
        if not deltas:
            break
        trial = {k: dict(v) for k, v in cur.items()}
        for hid, n in deltas.items():
            avail = [bp for bp in free_base[hid] if bp not in trial.get(hid, {})]
            for bp in _even_place(avail, abs(n)):
                trial.setdefault(hid, {})[bp] = -1 if n > 0 else (+1 if allow_loops else -1)
            if not trial.get(hid):
                trial.pop(hid, None)
        m = measure(trial)
        if m is None:
            break
        e = _shape_error(m.get("twist_deg"), m.get("bend_deg"),
                         target_twist_deg, target_bend_deg, use_bend)
        emit({"phase": "shape_iter", "iter": it, "twist": m.get("twist_deg"),
              "bend": m.get("bend_deg"), "shape_err": round(e, 3)})
        if e < cur_err - 1e-6:
            cur, cur_m, cur_tw, cur_bd, cur_err = trial, m, m.get("twist_deg"), m.get("bend_deg"), e
        else:
            break                                     # step did not help → stop (no regression)
    return {"marks": cur, "measure": cur_m, "authority": authority,
            "twist": cur_tw, "bend": cur_bd, "n_iters": n_iters}


# ── The greedy refinement loop ───────────────────────────────────────────────────────────────

def fem_refine(base_design: Design, *, nonlinear: bool = False, sigma: float = 1.0,
               max_hotspots: int = 8, min_spacing: int = 8, rmsd_improve_nm: float = 0.05,
               allow_loops: Optional[bool] = None,
               on_progress: Optional[Callable[[dict], None]] = None,
               should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """Refine loop/skip marks so the FEM-predicted shape matches the design's INTENDED shape.

    The objective is LATTICE-SPECIFIC (exp37 — ``experiments/exp37_cando_skip_twist_map``):

    * **SQUARE → null the end-to-end TWIST** relative to the intended twist (``_twist_error``).  A
      square bundle's crossover register imposes a global over-twist; the deviation RMSD is
      minimised at a LOWER skip density than the twist (RMSD-min ≈ 10 skips/helix at +14°, twist-min
      ≈ 12.6), so a deviation objective structurally floors twist at ~10-15°.  The refiner instead
      (1) sweeps the uniform skip PERIOD to the twist-nulling density (:func:`sweep_skip_period`
      with a twist-error ``cost_fn``), then (2) bumps individual helices by one skip — highest
      measured twist-authority first (:func:`_fractional_twist_bump`) — to resolve inside ±1°.
      Deviation is REPORTED but not minimised; it rises modestly as twist → 0 (the twist↔deviation
      tradeoff).  ``authority`` in the result is the per-helix ∂twist/∂skip map.

    * **HONEYCOMB / other → hit the intended (TWIST, BEND) shape** (exp38/exp40).  If the design
      carries a real shape target — a programmed bend above the arc-bend noise floor, or a twist
      error beyond tol — the coupled :func:`_solve_shape_targets` drives the FEM (twist, bend) to the
      intended pair via a ridge least-squares solve on the measured 2×H authority Jacobian
      (``objective="shape"``, ``authority`` = per-helix ``[∂twist/∂skip, ∂bend/∂skip]``).  Otherwise
      (straight / weak-target designs, where the bend row would be noise — exp40 G3) it falls back to
      the local greedy on the DEVIATION field (``objective="deviation"``): rank hotspots, TRY every
      edit (add-skip / add-loop / remove), KEEP the best if it lowers the RMSD by ≥ ``rmsd_improve_nm``.

    ``allow_loops`` defaults to ``design.lattice_type != SQUARE`` (square → skips only, per the
    user's split); pass an explicit bool to override.  ``nonlinear=False`` (linear, ~seconds) is
    the sensible inner-loop oracle; run a final Fine job to confirm.

    Returns ``{status, mode, objective, n_hotspots, n_evaluated, edits_kept, before, after,
    twist_target, twist_before, twist_after, twist_tol, metrics, converged_marks, density,
    authority}``.  ``converged_marks`` is ``{helix_id: {bp_index: delta}}`` (the apply route lands
    it); ``before``/``after`` are ``{rmsd, dev_max, dev_mean}``; ``twist_*`` carry the end-to-end
    twist objective (the runner's apply gate for square); ``density``/``authority`` are square-only
    (else ``None``).  ``status`` ∈ {done, stopped, error}.
    """
    if allow_loops is None:
        allow_loops = base_design.lattice_type != LatticeType.SQUARE
    is_square = base_design.lattice_type == LatticeType.SQUARE
    mode = "loops_and_skips" if allow_loops else "skips_only"
    objective = "twist" if is_square else "deviation"    # honeycomb may switch to "shape" below

    def emit(ev: dict) -> None:
        if on_progress:
            on_progress(ev)

    emit({"phase": "baseline", "mode": mode})
    baseline = fem_measure(base_design, nonlinear=nonlinear)
    if baseline is None:
        return {"status": "error", "mode": mode,
                "error": "design has no double-helical core to predict a shape for",
                "edits_kept": [], "n_hotspots": 0, "n_evaluated": 0}

    # Twist/bend/deviation readout for the live status: the target (intended geometry, measured
    # once) and the current best (reuses each fem_measure's cached shape — no extra solves).  The
    # objective is |FEM twist − INTENDED twist| (target["twist_deg"], usually ~0 for a straight
    # strut but non-zero for a programmed-twist design) — see _twist_error.
    core_keys = _core_keys(baseline["shape"])
    target = target_metrics(base_design, core_keys)
    target_twist = target["twist_deg"] if target["twist_deg"] is not None else 0.0
    target_bend = target["bend_deg"]
    before_metrics = current_metrics(baseline, core_keys)
    emit({"phase": "iteration", "iteration": 0, "n_hotspots": None,
          "current": before_metrics, "target": target})

    forbidden, _interior = _forbidden_bps(base_design)
    helix_by_id = {h.id: h for h in base_design.helices}
    free_base = {h.id: free_interior_candidates(base_design, h, forbidden[h.id])
                 for h in base_design.helices}
    cur_marks = current_marks_by_helix(base_design)
    best = baseline
    stopped = False
    density = None
    authority = None
    kept: list[dict] = []
    evaluated = 0
    n_hotspots = 0

    if is_square:
        # ── SQUARE: null end-to-end twist relative to the INTENDED twist ─────────────────────
        # exp37: deviation-min ≠ twist-min (RMSD bottoms at ~10 skips/helix / +14°, twist at
        # ~12.6), so the objective is the TWIST error, not RMSD.  A uniform density sweep drives
        # to the twist-nulling density, then fractional per-helix bumps resolve inside ±1°.
        cost = lambda m: _twist_error(m, target_twist)     # noqa: E731
        sweep = sweep_skip_period(base_design, nonlinear=nonlinear, cost_fn=cost,
                                  on_progress=emit, should_stop=should_stop)
        stopped = sweep["status"] == "stopped"
        density = {"best_period": sweep["best_period"],
                   "baseline_rmsd": (sweep["baseline_measure"] or {}).get("rmsd"),
                   "best_rmsd": (sweep["best_measure"] or {}).get("rmsd"),
                   "curve": sweep["curve"]}
        bm_marks = sweep["best_marks"]
        if not stopped and bm_marks:
            per = [len(v) for v in bm_marks.values()]
            n_uniform = round(sum(per) / len(per)) if per else 0
            frac = _fractional_twist_bump(
                base_design, base_count=n_uniform, target_twist_deg=target_twist,
                nonlinear=nonlinear, twist_tol=TWIST_TOL_DEG, forbidden=forbidden,
                free_base=free_base, on_progress=emit, should_stop=should_stop)
            cand = frac["measure"]
            # Adopt the twist-nulled program only if it beats the design as loaded on the TWIST
            # error (never a twist regression); deviation is allowed to rise modestly — that is the
            # intrinsic twist↔deviation tradeoff (exp37 rmsd 0.44→0.54 at twist→0), not a failure.
            if cand is not None and (_twist_error(cand, target_twist)
                                     < _twist_error(best, target_twist) - 1e-9):
                cur_marks = {hid: dict(bps) for hid, bps in frac["marks"].items()}
                best = cand
                authority = {h: round(v, 4) for h, v in frac["authority"].items()}
                emit({"phase": "iteration", "iteration": 0, "n_hotspots": None,
                      "density_period": sweep["best_period"],
                      "current": current_metrics(best, core_keys), "target": target})
    # Does this (non-square) design carry a real SHAPE target to hit — a programmed bend above the
    # arc-bend noise floor (exp40 G3), or a twist error beyond tol?  If so, use the coupled
    # (twist,bend) Jacobian solve (exp38 G1); else fall back to the deviation greedy (straight /
    # weak-target designs, where the bend row would be noise and the greedy does no harm).
    use_bend_target = (not is_square and target_bend is not None
                       and abs(target_bend) > BEND_TARGET_FLOOR_DEG)
    base_bd = before_metrics["bend_deg"]
    twist_off = abs((before_metrics["twist_deg"] or 0.0) - target_twist) > TWIST_TOL_DEG
    bend_off = use_bend_target and base_bd is not None and abs(base_bd - target_bend) > BEND_TOL_DEG
    use_shape = (not is_square) and (use_bend_target or twist_off) and (twist_off or bend_off)

    if is_square:
        pass                                            # handled above
    elif use_shape:
        # ── HONEYCOMB coupled (twist, bend) SHAPE solve (exp38 G1) ───────────────────────────
        objective = "shape"
        emit({"phase": "shape_target", "twist": target_twist,
              "bend": (target_bend if use_bend_target else None)})
        sol = _solve_shape_targets(
            base_design, target_twist_deg=target_twist,
            target_bend_deg=(target_bend if use_bend_target else None),
            nonlinear=nonlinear, forbidden=forbidden, free_base=free_base,
            allow_loops=allow_loops, on_progress=emit, should_stop=should_stop)
        cand = sol["measure"]
        use_bd = use_bend_target
        # Adopt only if it lowers the combined shape error over the design as loaded (no regression).
        base_err = _shape_error(before_metrics["twist_deg"], base_bd,
                                target_twist, target_bend, use_bd)
        cand_err = (_shape_error(cand.get("twist_deg"), cand.get("bend_deg"),
                                 target_twist, target_bend, use_bd) if cand else float("inf"))
        if cand is not None and cand_err < base_err - 1e-6:
            cur_marks = {hid: dict(bps) for hid, bps in sol["marks"].items()}
            best = cand
            authority = sol["authority"]
        emit({"phase": "iteration", "iteration": sol.get("n_iters", 0), "n_hotspots": None,
              "current": current_metrics(best, core_keys), "target": target})
    else:
        # ── HONEYCOMB / other: local greedy on the DEVIATION field (straight / weak-target) ──
        hotspots = [] if stopped else rank_hotspots(
            best["deviation_by_bp"], sigma=sigma, max_hotspots=max_hotspots, min_spacing=min_spacing)
        emit({"phase": "hotspots", "n": len(hotspots)})
        n_hotspots = len(hotspots)
        iteration = 0
        for hs in hotspots:
            if should_stop and should_stop():
                stopped = True
                break
            if hs[0] not in helix_by_id:
                continue
            iteration += 1
            # Re-derive free candidates for THIS helix from the accumulated pattern so a bp used by
            # an earlier accepted edit is not offered again (core_candidates already drops marked bp).
            helix = helix_by_id[hs[0]]
            live_free = free_interior_candidates(apply_marks(base_design, cur_marks), helix,
                                                 forbidden[hs[0]])
            free_now = {hs[0]: live_free}
            best_edit = None
            best_measure = best
            for edit in candidate_edits(hs, cur_marks, free_now, allow_loops=allow_loops):
                if should_stop and should_stop():
                    stopped = True
                    break
                trial_marks = _with_edit(cur_marks, edit)
                m = fem_measure(apply_marks(base_design, trial_marks), nonlinear=nonlinear)
                evaluated += 1
                if m is None:
                    continue
                emit({"phase": "trial", "helix_id": hs[0], "bp": hs[1], "op": edit["op"],
                      "rmsd": m["rmsd"]})
                if m["rmsd"] < best_measure["rmsd"]:
                    best_edit, best_measure = edit, m
            if stopped:
                break
            accepted = best_edit is not None and best_measure["rmsd"] <= best["rmsd"] - rmsd_improve_nm
            if accepted:
                cur_marks = _with_edit(cur_marks, best_edit)
                best = best_measure
                kept.append({**best_edit, "rmsd": best["rmsd"], "dev_max": best["dev_max"]})
            emit({"phase": "iteration", "iteration": iteration, "n_hotspots": len(hotspots),
                  "helix_id": hs[0], "bp": hs[1],
                  "op": best_edit["op"] if accepted else None, "accepted": accepted,
                  "current": current_metrics(best, core_keys), "target": target})

    after_metrics = current_metrics(best, core_keys)
    out = {
        "status":          "stopped" if stopped else "done",
        "mode":            mode,
        # "twist" (square) | "shape" (honeycomb coupled twist+bend) | "deviation" (greedy fallback).
        "objective":       objective,
        "n_hotspots":      n_hotspots,
        "n_evaluated":     evaluated,
        "edits_kept":      kept,
        "before":          {k: baseline[k] for k in ("rmsd", "dev_max", "dev_mean")},
        "after":           {k: best[k] for k in ("rmsd", "dev_max", "dev_mean")},
        # End-to-end twist + bend vs the intended shape — the objective (the runner's apply gate).
        "twist_target":    target_twist,
        "twist_before":    before_metrics["twist_deg"],
        "twist_after":     after_metrics["twist_deg"],
        "twist_tol":       TWIST_TOL_DEG,
        "bend_target":     target_bend,
        "bend_before":     before_metrics["bend_deg"],
        "bend_after":      after_metrics["bend_deg"],
        "bend_tol":        BEND_TOL_DEG,
        # Final twist/bend/deviation of the best prediction vs the target (for the result readout).
        "metrics":         {"before": before_metrics, "after": after_metrics, "target": target},
        "converged_marks": {hid: {int(bp): int(dl) for bp, dl in bps.items()}
                            for hid, bps in cur_marks.items() if bps},
        # Square-lattice density sweep report (None for honeycomb / non-square).
        "density":         density,
        # Per-helix measured authority: square → {helix: ∂twist/∂skip}; shape → {helix:
        # [∂twist/∂skip, ∂bend/∂skip]}; deviation → None.
        "authority":       authority,
    }
    emit({"phase": "done", "status": out["status"], "kept": len(kept),
          "before_rmsd": out["before"]["rmsd"], "after_rmsd": out["after"]["rmsd"],
          "twist_before": out["twist_before"], "twist_after": out["twist_after"],
          "current": after_metrics, "target": target})
    return out
