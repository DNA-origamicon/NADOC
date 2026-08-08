"""Regional (non-uniform) skip placement for square-lattice autorefine (Phase 5).

The uniform-period generator (:func:`loop_skip_calculator.sq_lattice_periodic_skips`)
places one deletion every N bp per helix — it fixes the per-helix deletion COUNT (hence
the net global twist) but is blind to WHERE the simulated structure actually deviates or
where mechanical strain concentrates.  This module keeps the per-helix count (so net
twist is preserved) but chooses each deletion's POSITION from two per-(helix, bp) fields
measured on the oxDNA mean structure:

  * deviation — geometric error of the simulated mean vs the intended design
    (:func:`oxdna_health.geometry_deviation_map`).  ATTRACTS deletions: correct where the
    local twist/shape error actually is.
  * strain    — backbone FENE stretch (:func:`oxdna_health.backbone_strain_field`).
    REPELS deletions: a deletion adds local tensile strain, so don't pile it onto an
    already-stressed site ("distribute the strain elsewhere").

ANTI-CLUSTERING GUARANTEE (the load-bearing invariant requested for Phase 5): the
per-helix budget is spread across EVENLY-SIZED slots along the helix and EXACTLY ONE
deletion is placed per slot, so the cumulative-deletion staircase tracks the linear ideal
correction curve.  A degenerate "all skips clustered at the ends — same net twist but the
middle deviates" solution is therefore impossible by construction; the fields only bias
the position WITHIN each evenly-spaced slot.

Pure / topological: returns a ``{helix_id: [LoopSkip]}`` mod dict; the caller applies it
with :func:`loop_skip_calculator.apply_loop_skips`.  No simulation, no global state, no
I/O — every nucleotide coordinate read is Physical-layer, never written back.
"""

from __future__ import annotations

from backend.core.loop_skip_calculator import _active_intervals_for_helices
from backend.core.models import Design, LatticeType, LoopSkip


def aggregate_deviation_per_bp(deviation_map: dict) -> dict[tuple[str, int], float]:
    """Collapse :func:`geometry_deviation_map`'s per-NUCLEOTIDE entries to per-(helix, bp)
    by averaging the (up to two) strands present at each base-pair column."""
    acc: dict[tuple[str, int], list[float]] = {}
    for p in deviation_map.get("positions", []):
        acc.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            float(p["deviation"])
        )
    return {k: sum(v) / len(v) for k, v in acc.items()}


def core_candidates(design: Design, helix) -> list[int]:
    """GLOBAL bp indices on ``helix`` where a deletion is valid — dsDNA core only (both
    tracks carry a domain), mirroring :func:`sq_lattice_periodic_skips`.  Already-marked
    positions are excluded so a re-placement never doubles up."""
    ivls = _active_intervals_for_helices(design, {helix.id})
    existing = {ls.bp_index for ls in helix.loop_skips}
    out: list[int] = []
    for bp_local in range(helix.length_bp):
        bp = helix.bp_start + bp_local
        if bp in existing:
            continue
        if any(lo <= bp < hi for lo, hi in ivls):
            out.append(bp)
    return out


def _norm(values: list[float]) -> list[float]:
    """Min-max normalise to [0, 1] within a helix (flat field -> all zeros) so ``w_dev``
    and ``w_strain`` weigh comparable quantities regardless of raw units."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def place_regional_skips(
    design: Design,
    budget_per_helix: dict[str, int],
    deviation_by_bp: dict[tuple[str, int], float],
    strain_by_bp: dict[tuple[str, int], float],
    *,
    w_dev: float = 1.0,
    w_strain: float = 0.25,
    min_spacing: int = 4,
) -> dict[str, list[LoopSkip]]:
    """Place each helix's deletion ``budget`` non-uniformly: even slots (anti-clustering)
    + within-slot bias toward high deviation / away from high strain, honouring
    ``min_spacing`` where feasible.

    Returns ``{helix_id: [LoopSkip(bp, -1) sorted by bp]}``.  The per-helix COUNT equals
    the requested budget (capped at the number of core candidates), so the net global
    twist matches the uniform-period pattern of the same total density — only the spatial
    distribution differs.  SQUARE lattice only (returns ``{}`` otherwise).

    ``deviation_by_bp`` / ``strain_by_bp`` are ``{(helix_id, bp): value}`` fields (missing
    entries treated as 0 = neutral), e.g. from :func:`aggregate_deviation_per_bp` and
    :func:`oxdna_health.backbone_strain_field`.
    """
    if design.lattice_type != LatticeType.SQUARE:
        return {}

    result: dict[str, list[LoopSkip]] = {}
    for helix in sorted(design.helices, key=lambda h: h.id):
        budget = int(budget_per_helix.get(helix.id, 0))
        if budget <= 0:
            continue
        cands = core_candidates(design, helix)
        m = len(cands)
        if m == 0:
            continue
        budget = min(budget, m)

        # Per-candidate score (fields normalised within this helix): deviation attracts
        # (+), strain repels (-).
        dev = _norm([deviation_by_bp.get((helix.id, bp), 0.0) for bp in cands])
        strn = _norm([strain_by_bp.get((helix.id, bp), 0.0) for bp in cands])
        score = [w_dev * dev[i] - w_strain * strn[i] for i in range(m)]

        picks: list[int] = []  # chosen candidate INDICES (one per slot)
        last_bp: int | None = None
        for k in range(budget):
            lo_i = (k * m) // budget
            hi_i = max(lo_i + 1, ((k + 1) * m) // budget)
            slot = range(lo_i, min(hi_i, m))
            feasible = [
                i for i in slot if last_bp is None or cands[i] - last_bp >= min_spacing
            ]
            pool = feasible or list(slot)  # slot is never empty (lo_i < m for k<budget)
            best_i = max(pool, key=lambda i: score[i])
            picks.append(best_i)
            last_bp = cands[best_i]

        result[helix.id] = [
            LoopSkip(bp_index=cands[i], delta=-1) for i in sorted(picks)
        ]
    return result


def detrend_error_profile(error_profile):
    """Remove the linear (endpoint) trend from a cumulative twist-error profile ``[(t, e)]``,
    leaving only the LOCAL shape residual.  The net twist (the profile's endpoint) is the
    COUNT's job (the secant); redistribution must act only on departures from a uniform
    correction — otherwise it just re-chases the global over-twist the count already handles
    (and amplifies it).  Returns ``[(t, e − linear_fit(t))]``."""
    if not error_profile or len(error_profile) < 2:
        return list(error_profile)
    t0, e0 = error_profile[0]
    t1, e1 = error_profile[-1]
    width = (t1 - t0) or 1.0
    slope = (e1 - e0) / width
    return [(t, e - (e0 + slope * (t - t0))) for t, e in error_profile]


def _overtwist_rate_sampler(error_profile):
    """From a cumulative twist-ERROR profile ``[(axial_t, e_deg), …]`` (sim − analytic),
    return ``f(s)`` over normalised axial position ``s∈[0,1]`` giving the LOCAL over-twist
    RATE (deg/nm), clamped ≥ 0 — deletions only relieve OVER-winding, so under-wound
    (negative-slope) regions contribute no demand."""
    if not error_profile or len(error_profile) < 2:
        return lambda s: 0.0
    ts = [p[0] for p in error_profile]
    es = [p[1] for p in error_profile]
    t0, t1 = ts[0], ts[-1]
    width = (t1 - t0) or 1.0
    segs = []
    for k in range(len(ts) - 1):
        dt = ts[k + 1] - ts[k]
        slope = (es[k + 1] - es[k]) / dt if abs(dt) > 1e-9 else 0.0
        segs.append(((ts[k] - t0) / width, (ts[k + 1] - t0) / width, slope))

    def f(s):
        for s_lo, s_hi, slope in segs:
            if s_lo <= s <= s_hi:
                return max(0.0, slope)
        return max(0.0, segs[-1][2])

    return f


def _weighted_spread_select(
    cands: list[int],
    weight: list[float],
    budget: int,
    min_spacing: int,
    phase: float = 0.5,
) -> list[int]:
    """Choose ``budget`` of ``cands`` so their DENSITY follows ``weight`` (inverse-CDF over
    the cumulative weight, sampled at the ``budget`` quantiles offset by ``phase``∈[0,1)),
    honouring ``min_spacing`` and distinctness.  Uniform weight → even spacing
    (anti-clustering preserved); a peaked weight → denser there.  ``phase`` shifts the
    sampling grid by a fraction of the inter-deletion spacing — the caller staggers it per
    helix so deletions don't ALL land in the same cross-sectional slice (mirroring
    ``sq_lattice_periodic_skips``' ``offset_i``; cross-section alignment changes the bundle's
    twist/strain response).  Unlike the even-slot placer this lets >1 deletion fall in a
    high-demand region, which the iterative profile-matcher needs."""
    import itertools

    m = len(cands)
    budget = min(budget, m)
    if budget <= 0:
        return []
    cw = list(itertools.accumulate(w if (w := wt) > 0 else 1e-9 for wt in weight))
    total = cw[-1] or 1.0
    picks: list[int] = []
    last_bp = None
    for j in range(budget):
        target = (j + (phase % 1.0)) * total / budget
        i = 0
        while i < m - 1 and cw[i] < target:
            i += 1

        # honour spacing + distinctness by walking forward, then backward, to a free slot
        def _free(idx):
            return idx not in picks and (
                last_bp is None or cands[idx] - last_bp >= min_spacing
            )

        if not _free(i):
            fwd = next((k for k in range(i, m) if _free(k)), None)
            bwd = next((k for k in range(i, -1, -1) if k not in picks), None)
            i = fwd if fwd is not None else (bwd if bwd is not None else i)
        picks.append(i)
        last_bp = cands[i]
    return [cands[i] for i in picks]


def redistribute_by_twist_profile(
    design: Design,
    budget_per_helix: dict[str, int],
    error_profile,
    *,
    gain: float = 1.0,
    base: float = 1.0,
    min_spacing: int = 4,
) -> dict[str, list[LoopSkip]]:
    """Place each helix's deletion budget with DENSITY proportional to the local residual
    OVER-twist — the control law of the Phase-5 iterative profile-matcher.  ``error_profile``
    is the bundle's cumulative twist-error profile (sim − analytic, from
    :func:`measure_bundle_twist_profile`), shared across helices (twist is a global
    cross-section rotation).  Per candidate the weight is ``base + gain·max(0, overtwist_rate)``:
    ``base`` keeps a uniform floor (the net-twist count is preserved regardless), ``gain``
    sets how strongly to chase over-wound regions.  Moderate ``gain`` + the re-simulation
    feedback (over-twist drops where corrected) is what makes the loop converge gently
    instead of the gain-∞ one-shot jump that overshot net twist by 45°.  SQUARE only.
    """
    if design.lattice_type != LatticeType.SQUARE:
        return {}
    rate = _overtwist_rate_sampler(error_profile)
    helices = sorted(design.helices, key=lambda h: h.id)
    n = len(helices) or 1
    result: dict[str, list[LoopSkip]] = {}
    for rank, helix in enumerate(helices):
        budget = int(budget_per_helix.get(helix.id, 0))
        if budget <= 0:
            continue
        cands = core_candidates(design, helix)
        if not cands:
            continue
        lo, hi = cands[0], cands[-1]
        rng = (hi - lo) or 1
        weight = [base + gain * rate((bp - lo) / rng) for bp in cands]
        # Stagger the sampling grid by helix rank so deletions don't align across the
        # cross-section (the bug that made regional placement read as a different structure
        # from staggered uniform — a ~20° twist artifact, not real refinement).
        picks = _weighted_spread_select(
            cands, weight, budget, min_spacing, phase=rank / n
        )
        if picks:
            result[helix.id] = [LoopSkip(bp_index=bp, delta=-1) for bp in sorted(picks)]
    return result


def budget_from_uniform_period(design: Design, skip_period: int) -> dict[str, int]:
    """Per-helix deletion COUNT the uniform period-``skip_period`` pattern would place —
    the twist-preserving budget the regional placer redistributes.  Derived from
    :func:`sq_lattice_periodic_skips` so net twist density is identical to the uniform
    baseline (the regional run differs only in WHERE the same count of deletions go)."""
    from backend.core.loop_skip_calculator import sq_lattice_periodic_skips

    mods = sq_lattice_periodic_skips(design, skip_period)
    return {hid: len(skips) for hid, skips in mods.items()}
