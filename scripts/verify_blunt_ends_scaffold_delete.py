"""Verify that deleting scaffold strands from helices 0-3 leaves all blunt-end
positions unchanged.

Usage:
    python scripts/verify_blunt_ends_scaffold_delete.py

The script:
1. Loads Ultimate Polymer Hinge.nadoc and applies _recenter_design (same as the
   server-side load path).
2. Records every free helix endpoint (blunt end) and its 3-D position.
3. Simulates deletion of all scaffold strands whose every domain lies on helices
   0-3 by applying the refactored _apply logic from delete_strand.
4. Records blunt ends again on the post-deletion design.
5. Prints a diff; exits 0 if they are identical (within 1 pm tolerance), 1 otherwise.
"""

import sys
import math
import json
import copy
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend.core.models import Design
from backend.core.deformation import deformed_helix_axes

DESIGN_PATH = REPO / "workspace" / "Ultimate Polymer Hinge.nadoc"
TOL = 1e-3   # 1 pm in nm — same as blunt_ends.js


# ── helpers ───────────────────────────────────────────────────────────────────

def _recenter(design: Design) -> Design:
    """Translate helix XY so the bounding-box centre is at the origin."""
    if not design.helices:
        return design
    xs = [h.axis_start.x for h in design.helices]
    ys = [h.axis_start.y for h in design.helices]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    if abs(cx) < 1e-6 and abs(cy) < 1e-6:
        return design
    from backend.core.models import Vec3
    new_helices = [
        h.model_copy(update={
            "axis_start": Vec3(x=h.axis_start.x - cx, y=h.axis_start.y - cy, z=h.axis_start.z),
            "axis_end":   Vec3(x=h.axis_end.x   - cx, y=h.axis_end.y   - cy, z=h.axis_end.z),
        })
        for h in design.helices
    ]
    return design.model_copy(update={"helices": new_helices})


def _blunt_ends(design: Design) -> dict[str, tuple[float, float, float]]:
    """Return {label: (x, y, z)} for every free helix endpoint.

    'Free' means no other helix has an endpoint within TOL nm of that position.
    Label is '<helix_index>_start' or '<helix_index>_end'.
    """
    axes = deformed_helix_axes(design)
    # Build lookup: helix_id -> {start, end}
    pos_by_id: dict[str, dict] = {
        a["helix_id"]: {"start": tuple(a["start"]), "end": tuple(a["end"])}
        for a in axes
    }

    all_points: list[tuple[float, float, float]] = []
    for a in axes:
        all_points.append(tuple(a["start"]))
        all_points.append(tuple(a["end"]))

    def _is_free(pt: tuple) -> bool:
        count = sum(
            1 for p in all_points
            if math.sqrt(sum((a - b) ** 2 for a, b in zip(pt, p))) < TOL
        )
        return count == 1   # only itself → free

    helices = design.helices
    result: dict[str, tuple] = {}
    for i, h in enumerate(helices):
        label = h.label if h.label is not None else str(i)
        p = pos_by_id.get(h.id)
        if p is None:
            continue
        if _is_free(p["start"]):
            result[f"{label}_start"] = p["start"]
        if _is_free(p["end"]):
            result[f"{label}_end"] = p["end"]
    return result


def _simulate_delete_strands(design: Design, strand_ids: set[str]) -> Design:
    """Apply the refactored delete_strand logic for a set of strand IDs at once.

    - Removes the strands and their overhang specs.
    - Drops helices that have no remaining strand coverage.
    - Cascade-deletes crossovers whose bp positions are no longer covered.
    - Does NOT trim helix axes (the refactored behaviour).
    """
    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id in strand_ids}
    new_strands  = [s for s in design.strands  if s.id not in strand_ids]
    new_overhangs = [o for o in design.overhangs if o.id not in ovhg_ids_to_remove]

    covered: set[str] = {dom.helix_id for s in new_strands for dom in s.domains}
    new_helices = [h for h in design.helices if h.id in covered]

    # Cascade-delete stale crossovers
    slot_cov: dict[str, list[tuple[int, int]]] = {}
    for s in new_strands:
        for dom in s.domains:
            key = f"{dom.helix_id}_{dom.direction}"
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            slot_cov.setdefault(key, []).append((lo, hi))

    def _covered(helix_id: str, bp: int, direction: str) -> bool:
        return any(
            lo <= bp <= hi
            for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
        )

    new_crossovers = [
        xo for xo in design.crossovers
        if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
    ]

    return design.model_copy(update={
        "strands":    new_strands,
        "overhangs":  new_overhangs,
        "helices":    new_helices,
        "crossovers": new_crossovers,
    })


def _pts_equal(a: tuple, b: tuple) -> bool:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) < TOL


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"Loading {DESIGN_PATH.name} …")
    design = Design.from_json(DESIGN_PATH.read_text(encoding="utf-8"))
    design = _recenter(design)

    helices = design.helices
    hids_03 = {h.id for h in helices[:4]}
    print(f"Helices 0-3 IDs: {[h.id[:12] for h in helices[:4]]}")

    # Scaffold strands whose every domain is on helices 0-3
    to_delete: set[str] = {
        s.id for s in design.strands
        if s.strand_type == "scaffold"
        and all(dom.helix_id in hids_03 for dom in s.domains)
    }
    print(f"Scaffold strands to delete: {len(to_delete)}")
    if not to_delete:
        print("  (none found — check helix indices)")
        return 1

    # ── Before ────────────────────────────────────────────────────────────────
    before = _blunt_ends(design)
    print(f"\nBlunt ends BEFORE deletion ({len(before)}):")
    for lbl, pt in sorted(before.items()):
        print(f"  {lbl:30s}  ({pt[0]:+.4f}, {pt[1]:+.4f}, {pt[2]:+.4f})")

    # ── Simulate deletion ──────────────────────────────────────────────────────
    design_after = _simulate_delete_strands(design, to_delete)
    print(f"\nHelices after deletion: {len(design_after.helices)}  (was {len(helices)})")

    # ── After ─────────────────────────────────────────────────────────────────
    after = _blunt_ends(design_after)
    print(f"\nBlunt ends AFTER deletion ({len(after)}):")
    for lbl, pt in sorted(after.items()):
        print(f"  {lbl:30s}  ({pt[0]:+.4f}, {pt[1]:+.4f}, {pt[2]:+.4f})")

    # ── Diff ──────────────────────────────────────────────────────────────────
    all_labels = sorted(set(before) | set(after))
    diffs = []
    for lbl in all_labels:
        if lbl not in before:
            diffs.append(f"  ADDED   {lbl}: {after[lbl]}")
        elif lbl not in after:
            diffs.append(f"  REMOVED {lbl}: {before[lbl]}")
        elif not _pts_equal(before[lbl], after[lbl]):
            diffs.append(
                f"  MOVED   {lbl}: {before[lbl]}  →  {after[lbl]}"
            )

    print()
    if diffs:
        print(f"FAIL — {len(diffs)} blunt end(s) changed:")
        for d in diffs:
            print(d)
        return 1
    else:
        print(f"PASS — all {len(before)} blunt ends identical before and after deletion.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
