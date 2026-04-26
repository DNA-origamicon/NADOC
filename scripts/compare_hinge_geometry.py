#!/usr/bin/env python3
"""
Diagnose domain-vs-helix axis rotation bug for shared overhang helices.

Part A: Cross-checks pivot positions between cadnano import and .nadoc load.
Part B: For each rotating overhang on a shared helix, compares the current
        (buggy, whole-helix) axis positions against the correct domain-scoped
        axis positions, and prints the per-endpoint delta.

Usage
-----
    cd /home/joshua/NADOC
    uv run scripts/compare_hinge_geometry.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.models import Design, Direction
from backend.core.cadnano import import_cadnano
from backend.core.lattice import autodetect_all_overhangs
from backend.core.deformation import (
    _rot_from_quaternion,
    _apply_ovhg_rotations_to_axes,
    deformed_helix_axes,
    _AXIS_SAMPLE_STEP,
)
from backend.api.crud import (
    _recenter_design,
    _fix_stale_ovhg_pivots,
    _autodetect_clusters,
    _geometry_for_design,
)

CADNANO_PATH = Path("Examples/cadnano/Ultimate Polymer Hinge 191016.json")
NADOC_PATH   = Path("workspace/Ultimate Polymer Hinge 191016.nadoc")

_IDENTITY_QUAT = [0.0, 0.0, 0.0, 1.0]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sample_bp_list(h, n_samples: int) -> list[int]:
    """Global bp for each axis sample — mirrors deformed_helix_axes generation."""
    if n_samples == 2:
        return [h.bp_start, h.bp_start + h.length_bp - 1]
    local = list(range(0, h.length_bp, _AXIS_SAMPLE_STEP))
    if not local or local[-1] != h.length_bp - 1:
        local.append(h.length_bp - 1)
    return [h.bp_start + lbp for lbp in local]


def _domain_scoped_axes(design: Design, nucleotides: list[dict]) -> list[dict]:
    """Compute helix axes with domain-scoped (correct) rotation applied."""
    axes = deformed_helix_axes(design)  # base, no overhang rotation yet
    helices_by_id = {h.id: h for h in design.helices}
    axes_by_id    = {ax["helix_id"]: ax for ax in axes}
    nuc_lookup    = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in nucleotides
    }
    strand_by_id  = {s.id: s for s in design.strands}

    from backend.core.models import StrandType as _ST
    scaffold_helix_ids = {
        dom.helix_id
        for s in design.strands if s.strand_type == _ST.SCAFFOLD
        for dom in s.domains
    }

    for ovhg in design.overhangs:
        if ovhg.rotation == _IDENTITY_QUAT:
            continue
        if ovhg.id.startswith("ovhg_inline_") and ovhg.helix_id in scaffold_helix_ids:
            continue

        strand = strand_by_id.get(ovhg.strand_id)
        if not strand:
            continue
        dom_idx = next(
            (i for i, d in enumerate(strand.domains) if d.overhang_id == ovhg.id), None
        )
        if dom_idx is None:
            continue

        domain    = strand.domains[dom_idx]
        is_first  = dom_idx == 0
        junc_bp   = domain.end_bp if is_first else domain.start_bp
        dir_str   = "FORWARD" if domain.direction == Direction.FORWARD else "REVERSE"

        pivot_raw = nuc_lookup.get((ovhg.helix_id, junc_bp, dir_str))
        pivot     = np.array(pivot_raw if pivot_raw is not None else ovhg.pivot, dtype=float)
        R         = _rot_from_quaternion(*ovhg.rotation)

        ax = axes_by_id.get(ovhg.helix_id)
        if ax is None:
            continue
        h = helices_by_id.get(ovhg.helix_id)
        if h is None:
            continue

        domain_min = min(domain.start_bp, domain.end_bp)
        domain_max = max(domain.start_bp, domain.end_bp)

        old_samples = ax.get("samples") or [ax["start"], ax["end"]]
        sample_bps  = _sample_bp_list(h, len(old_samples))

        new_samples = [
            (R @ (np.array(pt) - pivot) + pivot).tolist()
            if domain_min <= sample_bps[i] <= domain_max
            else pt
            for i, pt in enumerate(old_samples)
        ]
        ax["samples"] = new_samples
        ax["start"]   = new_samples[0]
        ax["end"]     = new_samples[-1]

    return axes


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ── Part A: cadnano vs nadoc pivot cross-check ────────────────────────────────

def part_a(design_cn: Design, design_nd: Design) -> None:
    print("\n" + "=" * 70)
    print("PART A — Pivot cross-check: cadnano import vs .nadoc load")
    print("=" * 70)

    cn_map = {o.id: o for o in design_cn.overhangs}
    nd_map = {o.id: o for o in design_nd.overhangs}

    all_ids = sorted(set(cn_map) | set(nd_map))
    mismatches = 0

    for oid in all_ids:
        ocn = cn_map.get(oid)
        ond = nd_map.get(oid)
        if ocn is None:
            print(f"  [ONLY IN NADOC] {oid}")
            continue
        if ond is None:
            print(f"  [ONLY IN CADNANO] {oid}")
            continue

        dp = _dist(ocn.pivot, ond.pivot)
        rot_nd = ond.rotation

        flag = "  *** PIVOT MISMATCH ***" if dp > 0.1 else ""
        has_rot = rot_nd != _IDENTITY_QUAT
        rot_str = f"  rot={[round(x,3) for x in rot_nd]}" if has_rot else ""
        print(
            f"  {oid:<25}  h={ocn.helix_id:<20}  Δpivot={dp:.4f} nm{flag}{rot_str}"
        )
        if dp > 0.1:
            mismatches += 1
            print(f"    cadnano pivot: {[round(x,3) for x in ocn.pivot]}")
            print(f"    nadoc   pivot: {[round(x,3) for x in ond.pivot]}")

    print()
    if mismatches:
        print(f"  ⚠ {mismatches} pivot mismatch(es) > 0.1 nm")
    else:
        print("  ✓ All pivots agree within 0.1 nm")

    # Shared-helix summary
    from collections import defaultdict
    helix_ovhgs: dict[str, list] = defaultdict(list)
    for o in design_nd.overhangs:
        helix_ovhgs[o.helix_id].append(o)

    print("\nShared helices (>1 overhang on same helix):")
    any_shared = False
    for hid, ovhgs in sorted(helix_ovhgs.items()):
        if len(ovhgs) < 2:
            continue
        any_shared = True
        rotated = [o for o in ovhgs if o.rotation != _IDENTITY_QUAT]
        print(f"  {hid}: {len(ovhgs)} overhangs, {len(rotated)} rotated")
        for o in sorted(ovhgs, key=lambda x: x.id):
            tag = "ROT" if o.rotation != _IDENTITY_QUAT else "   "
            print(f"    [{tag}] {o.id}  pivot_z={o.pivot[2]:.2f} nm")
    if not any_shared:
        print("  (none — all helices have exactly 1 overhang)")


# ── Part B: axis bug diagnosis on nadoc ───────────────────────────────────────

def part_b(design_nd: Design) -> None:
    print("\n" + "=" * 70)
    print("PART B — Axis bug diagnosis (current buggy vs expected domain-scoped)")
    print("=" * 70)

    nucs = _geometry_for_design(design_nd)

    # Current (buggy): whole-helix rotation applied
    axes_buggy = deformed_helix_axes(design_nd)
    _apply_ovhg_rotations_to_axes(design_nd, axes_buggy, nucs)
    buggy_by_id = {ax["helix_id"]: ax for ax in axes_buggy}

    # Expected (correct): domain-scoped rotation
    axes_correct = _domain_scoped_axes(design_nd, nucs)
    correct_by_id = {ax["helix_id"]: ax for ax in axes_correct}

    strand_by_id = {s.id: s for s in design_nd.strands}
    helices_by_id = {h.id: h for h in design_nd.helices}

    print(f"  {'ovhg_id':<25} {'helix_id':<22} {'domain_bp':<12} "
          f"{'buggy_end':<30} {'correct_end':<30} {'Δ_nm':>6}")
    print("  " + "-" * 130)

    total_bugs = 0
    for ovhg in sorted(design_nd.overhangs, key=lambda o: o.id):
        if ovhg.rotation == _IDENTITY_QUAT:
            continue

        strand = strand_by_id.get(ovhg.strand_id)
        if not strand:
            continue
        dom_idx = next(
            (i for i, d in enumerate(strand.domains) if d.overhang_id == ovhg.id), None
        )
        if dom_idx is None:
            continue
        domain    = strand.domains[dom_idx]
        domain_min = min(domain.start_bp, domain.end_bp)
        domain_max = max(domain.start_bp, domain.end_bp)
        bp_str    = f"[{domain_min},{domain_max}]"

        ax_b = buggy_by_id.get(ovhg.helix_id)
        ax_c = correct_by_id.get(ovhg.helix_id)
        if not ax_b or not ax_c:
            continue

        for label, key in [("start", "start"), ("end", "end")]:
            b_pt = ax_b[key]
            c_pt = ax_c[key]
            delta = _dist(b_pt, c_pt)
            flag  = "  *** BUG ***" if delta > 0.01 else ""
            b_str = f"[{b_pt[0]:.2f}, {b_pt[1]:.2f}, {b_pt[2]:.2f}]"
            c_str = f"[{c_pt[0]:.2f}, {c_pt[1]:.2f}, {c_pt[2]:.2f}]"
            print(f"  {ovhg.id:<25} {ovhg.helix_id:<22} {bp_str:<12} "
                  f"{b_str:<30} {c_str:<30} {delta:>6.3f}{flag}")
            if delta > 0.01:
                total_bugs += 1

    print()
    if total_bugs:
        print(f"  ⚠ {total_bugs} endpoint(s) where buggy ≠ correct by > 0.01 nm")
    else:
        print("  ✓ No discrepancy — axis rotation is already domain-scoped")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if not CADNANO_PATH.exists():
        print(f"ERROR: {CADNANO_PATH} not found.  Run from the NADOC project root.")
        sys.exit(1)
    if not NADOC_PATH.exists():
        print(f"ERROR: {NADOC_PATH} not found.  Run from the NADOC project root.")
        sys.exit(1)

    print("Loading cadnano design…")
    cn_data   = json.loads(CADNANO_PATH.read_text())
    design_cn, warnings = import_cadnano(cn_data)
    design_cn = _recenter_design(design_cn)
    design_cn = autodetect_all_overhangs(design_cn)
    design_cn = _autodetect_clusters(design_cn)
    print(f"  {len(design_cn.helices)} helices, {len(design_cn.overhangs)} overhangs")

    print("Loading .nadoc design…")
    design_nd = Design.from_json(NADOC_PATH.read_text())
    design_nd = _fix_stale_ovhg_pivots(design_nd)
    design_nd = _recenter_design(design_nd)
    rotated_count = sum(1 for o in design_nd.overhangs if o.rotation != _IDENTITY_QUAT)
    print(f"  {len(design_nd.helices)} helices, {len(design_nd.overhangs)} overhangs "
          f"({rotated_count} rotated)")

    part_a(design_cn, design_nd)
    part_b(design_nd)


if __name__ == "__main__":
    main()
