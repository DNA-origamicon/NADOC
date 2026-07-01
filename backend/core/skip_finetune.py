"""Phase 5 (re-scoped) — greedy 1–5 discrete skip FINE-TUNER for square-lattice designs.

After the uniform optimizer converges net twist ≈ 0, a handful of LOCAL deviation hotspots may
remain (ends, scaffold/crossover heterogeneity).  This proposes a SMALL number of single-skip
edits — add a deletion in a locally OVER-wound hotspot, remove one near an UNDER-wound hotspot —
to fine-tune the LOCAL profile WITHOUT disturbing net twist.  On a full-scale origami one skip is
~0.2° of the ~50° total twist correction, so 1–5 edits keep net twist in tolerance BY
CONSTRUCTION (unlike wholesale redistribution, which rewrites the global register and swung twist
±30–45° — see ``project_regional_autorefine.md``).

Pure candidate identification + edit application live here; the greedy re-sim / accept-if-improves
loop is :func:`backend.api.skip_twist_tuning.greedy_finetune_skips`.  Topological only.
"""
from __future__ import annotations

from backend.core.models import Design, LatticeType
from backend.core.regional_skip_placer import core_candidates


def current_skips_by_helix(design: Design) -> dict[str, list[int]]:
    """``{helix_id: [bp_index of each deletion]}`` for the design's current loop/skips."""
    return {h.id: sorted(ls.bp_index for ls in h.loop_skips if ls.delta == -1)
            for h in design.helices if any(ls.delta == -1 for ls in h.loop_skips)}


def _signed_overtwist_slope(shape_profile, frac: float) -> float:
    """SIGNED local twist-error rate at normalised axial position ``frac``∈[0,1] from a detrended
    cumulative twist-error profile ``[(t, e), …]``.  > 0 ⇒ locally OVER-wound (add a deletion);
    < 0 ⇒ locally under-wound (remove one)."""
    if not shape_profile or len(shape_profile) < 2:
        return 0.0
    ts = [p[0] for p in shape_profile]
    es = [p[1] for p in shape_profile]
    t0, t1 = ts[0], ts[-1]
    width = (t1 - t0) or 1.0
    x = t0 + max(0.0, min(1.0, frac)) * width
    for k in range(len(ts) - 1):
        if ts[k] <= x <= ts[k + 1]:
            dt = ts[k + 1] - ts[k]
            return (es[k + 1] - es[k]) / dt if abs(dt) > 1e-9 else 0.0
    return 0.0


def identify_finetune_edits(
    design: Design,
    deviation_by_bp: dict[tuple[str, int], float],
    shape_profile,
    *,
    max_edits: int = 5,
    sigma: float = 1.0,
    min_spacing: int = 8,
) -> list[dict]:
    """Rank LOCAL deviation hotspots and propose up to ``max_edits`` single-skip edits.

    A hotspot is a ``(helix, bp)`` whose deviation exceeds ``mean + sigma·std`` of the field (so
    a uniform/noise-only field yields NO edits — the fine-tuner does no harm when there is nothing
    local to fix).  Per hotspot the op is ``add`` if the local twist is over-wound
    (``_signed_overtwist_slope ≥ 0``) else ``remove``.  Hotspots within ``min_spacing`` bp on the
    same helix are de-duplicated so edits stay spread.  Returns ``[{helix_id, bp_index, op}]``
    (op ∈ {"add","remove"}), most-severe first; SQUARE only.
    """
    if design.lattice_type != LatticeType.SQUARE or not deviation_by_bp:
        return []
    vals = list(deviation_by_bp.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var ** 0.5
    threshold = mean + sigma * std

    helix_by_id = {h.id: h for h in design.helices}
    skips = current_skips_by_helix(design)
    ranked = sorted((kv for kv in deviation_by_bp.items() if kv[1] > threshold),
                    key=lambda kv: kv[1], reverse=True)

    edits: list[dict] = []
    chosen: list[tuple[str, int]] = []
    for (hid, bp), _dev in ranked:
        if len(edits) >= max_edits:
            break
        helix = helix_by_id.get(hid)
        if helix is None or helix.length_bp <= 0:
            continue
        if any(h2 == hid and abs(bp - b2) < min_spacing for h2, b2 in chosen):
            continue                                   # keep edits spread out
        frac = (bp - helix.bp_start) / helix.length_bp
        over_wound = _signed_overtwist_slope(shape_profile, frac) >= 0.0
        if over_wound:                                 # ADD a deletion at a free core bp here
            cands = core_candidates(design, helix)     # excludes existing skips
            if not cands:
                continue
            target = min(cands, key=lambda c: abs(c - bp))
            edits.append({"helix_id": hid, "bp_index": int(target), "op": "add"})
            chosen.append((hid, int(target)))
        else:                                          # REMOVE the nearest existing deletion
            existing = skips.get(hid, [])
            if not existing:
                continue                               # nothing to remove (deletion-only)
            target = min(existing, key=lambda c: abs(c - bp))
            edits.append({"helix_id": hid, "bp_index": int(target), "op": "remove"})
            chosen.append((hid, int(target)))
    return edits


def apply_finetune_edit(skips_by_helix: dict[str, list[int]], edit: dict) -> dict[str, list[int]]:
    """Return a copy of ``skips_by_helix`` with one edit applied: ``add`` inserts the bp (no-op if
    present); ``remove`` deletes the skip nearest the bp on that helix (no-op if none)."""
    out = {h: sorted(bps) for h, bps in skips_by_helix.items()}
    hid, bp, op = edit["helix_id"], int(edit["bp_index"]), edit["op"]
    cur = out.get(hid, [])
    if op == "add":
        if bp not in cur:
            out[hid] = sorted(cur + [bp])
    elif op == "remove" and cur:
        nearest = min(cur, key=lambda c: abs(c - bp))
        out[hid] = [b for b in cur if b != nearest]
        if not out[hid]:
            del out[hid]
    return out
