#!/usr/bin/env python3
"""
Validate domain-scoped axis rotation for shared overhang helices.

Applies controlled Ry rotations to ALL overhangs on two shared helices:
  - h_XY_6_3 (label 30): all overhangs → 45° Ry
  - h_XY_6_4 (label 31): all overhangs → 135° Ry

For each overhang's helix endpoint, prints three values:
  BUGGY    — what the code produced before the domain-scoping fix
             (all axis samples rotated by every overhang on the helix)
  CURRENT  — what _apply_ovhg_rotations_to_axes produces now (fixed)
  EXPECTED — reference domain-scoped math (independent of production code)

If the fix is correct: CURRENT ≈ EXPECTED (Δ ≈ 0), BUGGY ≠ EXPECTED.

Usage: cd /home/joshua/NADOC && uv run scripts/validate_domain_axis_rotation.py
"""
from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.models import Design, Direction
from backend.core.cadnano import import_cadnano
from backend.core.lattice import autodetect_all_overhangs
from backend.core.deformation import (
    _rot_from_quaternion,
    _apply_ovhg_rotations_to_axes,
    _sample_bp_list_for_axis,
    deformed_helix_axes,
    _AXIS_SAMPLE_STEP,
)
from backend.api.crud import (
    _recenter_design,
    _autodetect_clusters,
    _geometry_for_design,
)

CADNANO_PATH = Path("Examples/cadnano/Ultimate Polymer Hinge 191016.json")
HELIX_30_ID  = "h_XY_6_3"   # 5 overhangs → 45° Ry
HELIX_31_ID  = "h_XY_6_4"   # 5 overhangs → 135° Ry

_IDENTITY_QUAT = [0.0, 0.0, 0.0, 1.0]

RY_45  = [0.0, math.sin(math.radians(22.5)), 0.0, math.cos(math.radians(22.5))]
RY_135 = [0.0, math.sin(math.radians(67.5)), 0.0, math.cos(math.radians(67.5))]


# ── helpers ────────────────────────────────────────────────────────────────────

def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _apply_rotations(design: Design) -> Design:
    """Return a copy with 45°Ry on h_XY_6_3 and 135°Ry on h_XY_6_4."""
    quat_map = {HELIX_30_ID: RY_45, HELIX_31_ID: RY_135}
    new_overhangs = []
    for ovhg in design.overhangs:
        q = quat_map.get(ovhg.helix_id)
        if q is not None:
            new_overhangs.append(ovhg.model_copy(update={"rotation": q}))
        else:
            new_overhangs.append(ovhg)
    return design.model_copy(update={"overhangs": new_overhangs})


def _buggy_axes(design: Design, nucleotides: list[dict]) -> list[dict]:
    """What the code produced BEFORE the domain-scoping fix.

    Rotates ALL axis samples for each helix by every overhang's rotation,
    using nucleotide-derived pivot (the pre-fix behaviour).
    """
    from backend.core.models import StrandType as _ST

    nuc_lookup = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in nucleotides
    }
    scaffold_helix_ids: set[str] = {
        dom.helix_id
        for s in design.strands if s.strand_type == _ST.SCAFFOLD
        for dom in s.domains
    }
    strand_by_id = {s.id: s for s in design.strands}
    axes = deformed_helix_axes(design)
    axes_by_id = {ax["helix_id"]: ax for ax in axes}

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
        domain = strand.domains[dom_idx]
        is_first = dom_idx == 0
        junc_bp = domain.end_bp if is_first else domain.start_bp
        dir_str = "FORWARD" if domain.direction == Direction.FORWARD else "REVERSE"

        pivot_raw = nuc_lookup.get((ovhg.helix_id, junc_bp, dir_str))
        pivot = np.array(pivot_raw if pivot_raw is not None else ovhg.pivot, dtype=float)
        R = _rot_from_quaternion(*ovhg.rotation)
        ax = axes_by_id.get(ovhg.helix_id)
        if ax is None:
            continue

        old_samples = ax.get("samples") or [ax["start"], ax["end"]]
        # BUG: rotate ALL samples regardless of domain
        new_samples = [(R @ (np.array(pt) - pivot) + pivot).tolist() for pt in old_samples]
        ax["start"]   = new_samples[0]
        ax["end"]     = new_samples[-1]
        ax["samples"] = new_samples

    return axes


def _expected_axes(design: Design, nucleotides: list[dict]) -> list[dict]:
    """Reference domain-scoped implementation (independent of production code)."""
    from backend.core.models import StrandType as _ST

    nuc_lookup = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in nucleotides
    }
    scaffold_helix_ids: set[str] = {
        dom.helix_id
        for s in design.strands if s.strand_type == _ST.SCAFFOLD
        for dom in s.domains
    }
    strand_by_id  = {s.id: s for s in design.strands}
    helices_by_id = {h.id: h for h in design.helices}
    axes = deformed_helix_axes(design)
    axes_by_id = {ax["helix_id"]: ax for ax in axes}

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
        domain = strand.domains[dom_idx]
        is_first = dom_idx == 0
        junc_bp = domain.end_bp if is_first else domain.start_bp
        dir_str = "FORWARD" if domain.direction == Direction.FORWARD else "REVERSE"

        pivot_raw = nuc_lookup.get((ovhg.helix_id, junc_bp, dir_str))
        pivot = np.array(pivot_raw if pivot_raw is not None else ovhg.pivot, dtype=float)
        R = _rot_from_quaternion(*ovhg.rotation)
        ax = axes_by_id.get(ovhg.helix_id)
        h  = helices_by_id.get(ovhg.helix_id)
        if ax is None or h is None:
            continue

        domain_min = min(domain.start_bp, domain.end_bp)
        domain_max = max(domain.start_bp, domain.end_bp)
        old_samples = ax.get("samples") or [ax["start"], ax["end"]]
        n = len(old_samples)

        # Build sample-bp list the same way _sample_bp_list_for_axis does
        if n == 2:
            sample_bps = [h.bp_start, h.bp_start + h.length_bp - 1]
        else:
            local = list(range(0, h.length_bp, _AXIS_SAMPLE_STEP))
            if not local or local[-1] != h.length_bp - 1:
                local.append(h.length_bp - 1)
            sample_bps = [h.bp_start + lbp for lbp in local]

        new_samples = [
            (R @ (np.array(pt) - pivot) + pivot).tolist()
            if domain_min <= sample_bps[i] <= domain_max
            else pt
            for i, pt in enumerate(old_samples)
        ]
        ax["start"]   = new_samples[0]
        ax["end"]     = new_samples[-1]
        ax["samples"] = new_samples

    return axes


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if not CADNANO_PATH.exists():
        print(f"ERROR: {CADNANO_PATH} not found.  Run from project root.")
        sys.exit(1)

    print("Loading cadnano design…")
    cn_data = json.loads(CADNANO_PATH.read_text())
    design, _ = import_cadnano(cn_data)
    design = _recenter_design(design)
    design = autodetect_all_overhangs(design)
    design = _autodetect_clusters(design)
    design = _apply_rotations(design)

    rotated = [o for o in design.overhangs if o.rotation != _IDENTITY_QUAT]
    print(f"  {len(design.helices)} helices, {len(design.overhangs)} overhangs "
          f"({len(rotated)} rotated)")
    for h_id, label, quat in [
        (HELIX_30_ID, "h_XY_6_3", "45° Ry"),
        (HELIX_31_ID, "h_XY_6_4", "135° Ry"),
    ]:
        cnt = sum(1 for o in design.overhangs if o.helix_id == h_id)
        print(f"  {label}: {cnt} overhangs → {quat}")

    nucs = _geometry_for_design(design)

    # Three axis computations
    axes_buggy   = _buggy_axes(design, nucs)
    buggy_by_id  = {ax["helix_id"]: ax for ax in axes_buggy}

    axes_current = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes_current, nucs)
    current_by_id = {ax["helix_id"]: ax for ax in axes_current}

    axes_expected = _expected_axes(design, nucs)
    expected_by_id = {ax["helix_id"]: ax for ax in axes_expected}

    # --- Table: all overhangs on target helices ---
    target_helices = {HELIX_30_ID, HELIX_31_ID}
    strand_by_id   = {s.id: s for s in design.strands}

    print()
    print("=" * 128)
    print(f"HELIX AXIS START/END — current code vs expected (domain-scoped) vs buggy (old code)")
    print(f"  {HELIX_30_ID}: 45° Ry applied to all {sum(1 for o in design.overhangs if o.helix_id == HELIX_30_ID)} overhangs")
    print(f"  {HELIX_31_ID}: 135° Ry applied to all {sum(1 for o in design.overhangs if o.helix_id == HELIX_31_ID)} overhangs")
    print("=" * 128)

    col_w = 28
    print(f"  {'ovhg_id':<26} {'helix':<12} {'domain_bp':<12} {'endpt':<6} "
          f"{'CURRENT':<{col_w}} {'EXPECTED':<{col_w}} {'Δ cur-exp':>9}  "
          f"{'BUGGY':<{col_w}} {'Δ bug-exp':>9}")
    print("  " + "-" * 126)

    total_cur_bugs = 0
    total_bug_bugs = 0
    for ovhg in sorted(design.overhangs, key=lambda o: o.id):
        if ovhg.helix_id not in target_helices:
            continue
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
        domain = strand.domains[dom_idx]
        domain_min = min(domain.start_bp, domain.end_bp)
        domain_max = max(domain.start_bp, domain.end_bp)
        bp_str = f"[{domain_min},{domain_max}]"

        ax_c = current_by_id.get(ovhg.helix_id)
        ax_e = expected_by_id.get(ovhg.helix_id)
        ax_b = buggy_by_id.get(ovhg.helix_id)
        if not ax_c or not ax_e or not ax_b:
            continue

        for label, key in [("start", "start"), ("end", "end")]:
            c_pt = ax_c[key]
            e_pt = ax_e[key]
            b_pt = ax_b[key]
            d_ce = _dist(c_pt, e_pt)
            d_be = _dist(b_pt, e_pt)

            flag_c = " *** BUG" if d_ce > 0.01 else ""
            c_str = f"[{c_pt[0]:.2f},{c_pt[1]:.2f},{c_pt[2]:.2f}]"
            e_str = f"[{e_pt[0]:.2f},{e_pt[1]:.2f},{e_pt[2]:.2f}]"
            b_str = f"[{b_pt[0]:.2f},{b_pt[1]:.2f},{b_pt[2]:.2f}]"

            print(f"  {ovhg.id:<26} {ovhg.helix_id:<12} {bp_str:<12} {label:<6} "
                  f"{c_str:<{col_w}} {e_str:<{col_w}} {d_ce:>9.3f}{flag_c}  "
                  f"{b_str:<{col_w}} {d_be:>9.3f}")
            if d_ce > 0.01:
                total_cur_bugs += 1
            if d_be > 0.01:
                total_bug_bugs += 1

    print()
    print(f"  Current code vs expected:  {total_cur_bugs} endpoint(s) disagree > 0.01 nm  "
          f"{'⚠ FIX NEEDED' if total_cur_bugs else '✓ correct'}")
    print(f"  Buggy code vs expected:    {total_bug_bugs} endpoint(s) disagree > 0.01 nm  "
          f"(magnitude of the old bug)")


if __name__ == "__main__":
    main()
