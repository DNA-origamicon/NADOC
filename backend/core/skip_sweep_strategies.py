"""Skip-placement strategies for the skip-count → twist/curvature sweep (experiment exp31).

The autorefine loop tunes ONE knob — a uniform skip period — to drive square-lattice global
twist to zero.  This module supports an experiment that asks a different question: starting
from the analytical baseline, if we change the TOTAL skip count by ±18 (one deletion per
helix) per step, how does net twist (and curvature) respond, and does it matter WHERE the
added/removed deletions go?

Given a square-lattice bundle and a signed step ``delta`` (number of ±1-skip-per-helix rounds
away from the analytical baseline), each strategy returns an EXPLICIT deletion map
``{helix_id: [bp_index, ...]}`` for
:func:`backend.api.skip_twist_tuning.build_explicit_skip_from_design`.  Three strategies:

  - ``"uniform"``     — re-place ``base_count + delta`` deletions EVENLY + staggered on each
    helix (every skip moves register each step; the textbook restagger).
  - ``"incremental"`` — keep the baseline marks fixed; for ``+delta`` add a deletion at each
    helix's LARGEST gap, for ``-delta`` remove the one bordering the SMALLEST gap (minimal
    register disturbance, stays evenly spread).
  - ``"deviation"``   — adaptive feedback: ONE outward round per step, placing/removing each
    helix's deletion at the prior simulation's local deviation hotspot.

By construction all three change the total skip count by exactly ``delta · n_helices`` and
coincide at ``delta = 0`` (the shared analytical baseline) — so every strategy sits on the
SAME total-skip x-grid.  Pure / topological: no simulation, no I/O; deletions only.

The ``design`` passed in is the BARE routed bundle (no loop/skip marks) so
:func:`core_candidates` enumerates the full dsDNA core; each strategy tracks its own skip
positions and excludes them explicitly.
"""
from __future__ import annotations

from backend.core.loop_skip_calculator import (
    SQ_SKIP_PERIOD_DEFAULT,
    sq_lattice_periodic_skips,
)
from backend.core.regional_skip_placer import core_candidates

STRATEGIES = ("uniform", "incremental", "deviation")


def baseline_skips(design, *, skip_period: int = SQ_SKIP_PERIOD_DEFAULT) -> dict[str, list[int]]:
    """The analytical period-``skip_period`` staggered pattern as ``{helix_id: [bp, ...]}``
    (the Δ=0 anchor shared by all strategies)."""
    mods = sq_lattice_periodic_skips(design, skip_period)
    return {hid: sorted(ls.bp_index for ls in lss) for hid, lss in mods.items()}


def _pick_even(cands: list[int], m: int, offset_frac: float) -> list[int]:
    """Choose ``m`` distinct positions from sorted ``cands`` spread evenly across the list,
    phase-shifted by ``offset_frac`` ∈ [0,1) so different helices stagger.  Collisions step
    to the next free slot, guaranteeing exactly ``min(m, len(cands))`` picks."""
    n = len(cands)
    if m <= 0 or n == 0:
        return []
    if m >= n:
        return list(cands)
    step = n / m
    used: set[int] = set()
    for j in range(m):
        idx = int(round((j + offset_frac) * step)) % n
        while idx in used:
            idx = (idx + 1) % n
        used.add(idx)
    return sorted(cands[i] for i in used)


def place_uniform(design, base_skips: dict[str, list[int]], delta: int) -> dict[str, list[int]]:
    """Strategy A — re-place ``len(base_skips[h]) + delta`` deletions evenly + staggered on
    every helix.  Independent of any prior simulation.  At ``delta == 0`` returns the baseline
    verbatim (the shared anchor)."""
    if delta == 0:
        return {k: sorted(v) for k, v in base_skips.items() if v}
    helices = sorted(design.helices, key=lambda h: h.id)
    n = len(helices) or 1
    out: dict[str, list[int]] = {}
    for i, h in enumerate(helices):
        cands = core_candidates(design, h)
        m = max(0, len(base_skips.get(h.id, [])) + delta)
        picks = _pick_even(cands, m, (i % n) / n)
        if picks:
            out[h.id] = picks
    return out


def _add_at_largest_gap(cur: list[int], free: list[int]) -> list[int]:
    """Insert one deletion at the midpoint of the largest gap (including core ends), snapped
    to the nearest free core candidate."""
    avail = [c for c in free if c not in cur]
    if not avail:
        return cur
    if not cur:
        return [avail[len(avail) // 2]]
    lo, hi = min(free), max(free)
    bounds = [lo] + sorted(cur) + [hi]
    best_a, best_b, best_w = lo, hi, -1
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a > best_w:
            best_w, best_a, best_b = b - a, a, b
    mid = (best_a + best_b) // 2
    new = min(avail, key=lambda c: abs(c - mid))
    return sorted(cur + [new])


def _remove_at_smallest_gap(cur: list[int]) -> list[int]:
    """Remove the deletion bordering the smallest inter-skip gap (drops the upper endpoint)."""
    pts = sorted(cur)
    if len(pts) <= 1:
        return []
    idx, best_w = 0, None
    for k in range(len(pts) - 1):
        w = pts[k + 1] - pts[k]
        if best_w is None or w < best_w:
            best_w, idx = w, k
    return pts[: idx + 1] + pts[idx + 2 :]


def place_incremental(design, base_skips: dict[str, list[int]], delta: int) -> dict[str, list[int]]:
    """Strategy B — keep the baseline marks, then per helix apply ``|delta|`` rounds of
    add-at-largest-gap (``delta > 0``) or remove-at-smallest-gap (``delta < 0``).  Cumulative
    and deterministic; baseline marks stay put so the register is minimally disturbed."""
    out: dict[str, list[int]] = {}
    for h in sorted(design.helices, key=lambda x: x.id):
        cur = sorted(base_skips.get(h.id, []))
        free = core_candidates(design, h)
        for _ in range(abs(delta)):
            cur = _add_at_largest_gap(cur, free) if delta > 0 else _remove_at_smallest_gap(cur)
        if cur:
            out[h.id] = cur
    return out


def place_deviation_step(design, prev_skips: dict[str, list[int]], delta_sign: int,
                         deviation_by_bp: dict[tuple, float]) -> dict[str, list[int]]:
    """Strategy C — ONE outward round from ``prev_skips``: add (``delta_sign > 0``) or remove
    (``delta_sign < 0``) exactly one deletion per helix, located at that helix's local
    deviation hotspot from the prior simulation's per-(helix, bp) field.  With no field
    (the very first round before any sim) it falls back to the helix midpoint, deterministically.
    The driver chains this strategy outward (round N consumes round N−1's sim fields)."""
    if delta_sign == 0:
        return {h: sorted(bps) for h, bps in prev_skips.items() if bps}
    out: dict[str, list[int]] = {h: sorted(bps) for h, bps in prev_skips.items()}
    for h in sorted(design.helices, key=lambda x: x.id):
        hid = h.id
        cur = out.get(hid, [])
        dev_here = {bp: d for (hh, bp), d in deviation_by_bp.items() if hh == hid}
        hotspot = max(dev_here, key=lambda bp: dev_here[bp]) if dev_here else None
        if delta_sign > 0:
            avail = [c for c in core_candidates(design, h) if c not in cur]
            if not avail:
                continue
            new = (min(avail, key=lambda c: abs(c - hotspot)) if hotspot is not None
                   else avail[len(avail) // 2])
            out[hid] = sorted(cur + [new])
        else:
            if not cur:
                continue
            rem = (min(cur, key=lambda c: abs(c - hotspot)) if hotspot is not None
                   else cur[len(cur) // 2])
            out[hid] = [c for c in cur if c != rem]
    return {hid: bps for hid, bps in out.items() if bps}
