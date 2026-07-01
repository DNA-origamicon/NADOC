"""Profile-guided adaptive skip refinement (exp32).

exp31 showed: the square bundle's residual twist accumulates NON-uniformly along the axis
(back-loaded), uniform skip density can't flatten it, deviation-field placement is worst (it
steers on unsigned positional error, not signed twist), and INCREMENTAL-GAP placement is the one
that drives a region to zero twist.  This module closes the obvious loop: read the per-position
twist PROFILE, find the over-/under-wound axial SEGMENTS (the signed local slope), and add/remove
deletions there via incremental-gap, iterating to a flat-zero profile.

Topology note (the load-bearing, directionality-sensitive part): a "segment" is an AXIAL range,
but skips live at per-helix bp indices.  Each helix's bp maps to an axial coordinate by a simple
lerp of its axis geometry (``bp_start`` sits at ``axis_start``), projected onto the bundle axis —
the SAME projection the twist measurement uses.  So an axial segment maps to a contiguous bp
interval per helix, correctly mirrored for helices of opposite polarity (the projection handles
it; we never reason from strand direction).

Pure / topological — no simulation.  The iterative sim loop lives in the exp32 driver.
"""
from __future__ import annotations

import numpy as np

from backend.core.loop_skip_calculator import _active_intervals_for_helices

# One deletion per helix in a segment removes ~one bp of helical rotation from that segment's
# cross-section twist.  Round-1 estimate only; the per-segment secant refines it from data.
ANALYTIC_DEG_PER_DELETION = 34.0


def _bundle_axis(design):
    """(origin, unit_axis) for the bundle from helix axis geometry (mean axis vector)."""
    starts, vecs = [], []
    for h in design.helices:
        s = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z], float)
        e = np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z], float)
        starts.append(s); vecs.append(e - s)
    axis = np.mean(vecs, axis=0)
    axis /= (np.linalg.norm(axis) or 1.0)
    # Match measure_bundle_twist's axis SIGN convention (`_bundle_axis_frame`: largest-magnitude
    # component positive) so the binning's front/back agrees with the profile's position axis —
    # otherwise the controller would add skips at the mirror-image (wrong) end.
    if axis[int(np.argmax(np.abs(axis)))] < 0:
        axis = -axis
    return np.mean(starts, axis=0), axis


def _bp_axial(helix, bp, origin, axis) -> float:
    """Axial coordinate (projection onto the bundle axis) of bp on this helix."""
    s = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z], float)
    e = np.array([helix.axis_end.x, helix.axis_end.y, helix.axis_end.z], float)
    frac = (bp - helix.bp_start) / max(1, helix.length_bp)
    return float((s + frac * (e - s) - origin) @ axis)


def core_bps(design, helix) -> list[int]:
    """All dsDNA-core bp indices on a helix (both tracks present), INCLUDING marked ones —
    the candidate set for binning + gap-finding (unlike ``core_candidates`` which drops marks)."""
    ivls = _active_intervals_for_helices(design, {helix.id})
    return [helix.bp_start + i for i in range(helix.length_bp)
            if any(lo <= helix.bp_start + i < hi for lo, hi in ivls)]


def bin_layout(design, n_bins: int):
    """Map the dsDNA core to ``n_bins`` equal axial bins.

    Returns ``(edges, per_helix)`` where ``edges`` are the ``n_bins+1`` axial-fraction cut points
    (0..1 over the core's axial extent) and ``per_helix[helix_id][i]`` = sorted core bp indices of
    helix ``helix_id`` that fall in bin ``i``.  Fraction is the axial projection normalised over
    the whole bundle's core extent, so bin ``i`` is the SAME physical slab for every helix."""
    origin, axis = _bundle_axis(design)
    helices = sorted(design.helices, key=lambda h: h.id)
    axial = {h.id: {bp: _bp_axial(h, bp, origin, axis) for bp in core_bps(design, h)}
             for h in helices}
    allt = [t for d in axial.values() for t in d.values()]
    tmin, tmax = min(allt), max(allt)
    span = (tmax - tmin) or 1.0
    per_helix: dict[str, dict[int, list[int]]] = {}
    for h in helices:
        b: dict[int, list[int]] = {i: [] for i in range(n_bins)}
        for bp, t in axial[h.id].items():
            i = min(n_bins - 1, int((t - tmin) / span * n_bins))
            b[i].append(bp)
        for i in b:
            b[i].sort()
        per_helix[h.id] = b
    edges = [i / n_bins for i in range(n_bins + 1)]
    return edges, per_helix


def local_twist_per_bin(profile: list[dict], n_bins: int) -> list[float]:
    """Signed local cumulative-twist increment per axial bin (deg), from a profile of
    ``{position_frac, cum_twist_diff}`` points.  Positive = over-wound (add deletions here);
    negative = under-wound (remove).  Interpolates the cumulative at each bin edge then diffs, so
    it aligns with ``bin_layout`` regardless of the profile's own slab count."""
    fr = np.array([p["position_frac"] for p in profile], float)
    cum = np.array([p["cum_twist_diff"] for p in profile], float)
    order = np.argsort(fr); fr, cum = fr[order], cum[order]
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    cum_at = np.interp(edges, fr, cum)
    return [float(cum_at[i + 1] - cum_at[i]) for i in range(n_bins)]


def secant_targets(prev_counts, prev_lt, cur_counts, cur_lt, *, gain: float,
                   deg_per_del: float = ANALYTIC_DEG_PER_DELETION) -> list[int]:
    """Per-bin desired NEW deletions-per-helix count, driving local twist → 0.

    ``cur_counts``/``cur_lt`` = this round's per-bin (deletions-per-helix, measured local twist).
    ``prev_*`` = last round's, or ``None`` on round 1 (then use the analytic slope ``-deg_per_del``
    per deletion).  ``gain`` > 1 deliberately UNDER-damps (overshoot) so add+remove brackets zero
    in fewer rounds.  Adding a deletion lowers local twist, so slope d(lt)/d(count) < 0."""
    out = []
    for i, (n, lt) in enumerate(zip(cur_counts, cur_lt)):
        if prev_counts is not None and (cur_counts[i] - prev_counts[i]) != 0:
            slope = (cur_lt[i] - prev_lt[i]) / (cur_counts[i] - prev_counts[i])
            if abs(slope) < 1e-6:
                slope = -deg_per_del
        else:
            slope = -deg_per_del
        step = -gain * lt / slope                 # counts to change to reach lt = 0
        out.append(max(0, int(round(n + step))))
    return out


def plan_edits(current_skips: dict[str, list[int]], per_helix_bins,
               target_counts: list[int], *, min_spacing: int = 4) -> dict[str, list[int]]:
    """New ``{helix_id: [bp,...]}`` after moving each helix's per-bin deletion count toward
    ``target_counts[i]`` via incremental-gap: ADD at the largest gap within the bin, REMOVE the
    one bordering the smallest gap.  ``current_skips`` need not be confined to bins (baseline
    marks count toward whichever bin they fall in)."""
    out: dict[str, list[int]] = {}
    for hid, bins in per_helix_bins.items():
        cur = set(current_skips.get(hid, []))
        for i, cand in bins.items():
            cand_set = set(cand)
            present = sorted(b for b in cur if b in cand_set)
            want = target_counts[i]
            while len(present) > want and present:                 # REMOVE (under-wound)
                rem = _smallest_gap_member(present, cand)
                present.remove(rem); cur.discard(rem)
            while len(present) < want:                              # ADD (over-wound)
                new = _largest_gap_free(present, cand, cur, min_spacing)
                if new is None:
                    break
                present.append(new); present.sort(); cur.add(new)
        if cur:
            out[hid] = sorted(cur)
    return out


def _largest_gap_free(present: list[int], cand: list[int], used: set, min_spacing: int):
    """Free candidate bp at the midpoint of the largest gap among ``present`` (spanning the
    candidate range), honouring ``min_spacing`` from existing marks where possible."""
    free = [c for c in cand if c not in used]
    if not free:
        return None
    if not present:
        return free[len(free) // 2]
    lo, hi = cand[0], cand[-1]
    bounds = [lo] + sorted(present) + [hi]
    best_a, best_b, best_w = lo, hi, -1
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a > best_w:
            best_w, best_a, best_b = b - a, a, b
    mid = (best_a + best_b) // 2
    spaced = [c for c in free if all(abs(c - p) >= min_spacing for p in present)]
    pool = spaced or free
    return min(pool, key=lambda c: abs(c - mid))


def _smallest_gap_member(present: list[int], cand: list[int]) -> int:
    """The present mark bordering the smallest inter-mark gap (drop the upper endpoint)."""
    pts = sorted(present)
    if len(pts) == 1:
        return pts[0]
    idx, best = 0, None
    for k in range(len(pts) - 1):
        w = pts[k + 1] - pts[k]
        if best is None or w < best:
            best, idx = w, k
    return pts[idx + 1]


def counts_per_bin(current_skips: dict[str, list[int]], per_helix_bins) -> list[int]:
    """Mean deletions-per-helix in each bin for the current pattern (the controller's state)."""
    n_bins = len(next(iter(per_helix_bins.values()))) if per_helix_bins else 0
    totals = [0] * n_bins
    for hid, bins in per_helix_bins.items():
        cur = set(current_skips.get(hid, []))
        for i, cand in bins.items():
            totals[i] += sum(1 for b in cand if b in cur)
    n_helix = max(1, len(per_helix_bins))
    return [int(round(t / n_helix)) for t in totals]
