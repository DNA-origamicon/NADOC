#!/usr/bin/env python3
"""Derive optimal atomistic frame constants from a B-DNA PDB crystal structure.

Usage:
    uv run python scripts/calibrate_pdb.py Examples/1zew.pdb
    uv run python scripts/calibrate_pdb.py Examples/1zew.pdb --templates
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.pdb_import import (
    SUGAR_ATOMS,
    BASE_ATOMS,
    calibrate_from_pdb,
    analyze_duplex,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate atomistic frame constants from a PDB file.")
    parser.add_argument("pdb", help="Path to PDB file")
    parser.add_argument("--chain-a", default="A", help="Chain ID for strand A")
    parser.add_argument("--chain-b", default="B", help="Chain ID for strand B")
    parser.add_argument("--exclude-terminal", type=int, default=1, help="Terminal residues to exclude")
    parser.add_argument("--templates", action="store_true", help="Also print re-extracted templates")
    args = parser.parse_args()

    # ── Run calibration ───────────────────────────────────────────────────
    result = calibrate_from_pdb(
        args.pdb,
        chain_a=args.chain_a,
        chain_b=args.chain_b,
        exclude_terminal=args.exclude_terminal,
    )

    from backend.core.atomistic import _FRAME_ROT_RAD, _FRAME_SHIFT_N, _FRAME_SHIFT_Y, _FRAME_SHIFT_Z
    from backend.core.constants import HELIX_RADIUS, BDNA_TWIST_PER_BP_DEG, BDNA_RISE_PER_BP

    # ── Print results ─────────────────────────────────────────────────────
    print("=" * 70)
    print("  PDB Atomistic Calibration Report")
    print(f"  Source: {args.pdb}")
    print("=" * 70)

    print("\n── Frame Constants ────────────────────────────────────────")
    print(f"  {'Constant':<20s} {'Current':>12s} {'Calibrated':>12s} {'Delta':>12s}")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 12}")
    rows = [
        ("frame_rot (deg)", math.degrees(_FRAME_ROT_RAD), math.degrees(result.frame_rot_rad)),
        ("frame_shift_n (nm)", _FRAME_SHIFT_N, result.frame_shift_n),
        ("frame_shift_y (nm)", _FRAME_SHIFT_Y, result.frame_shift_y),
        ("frame_shift_z (nm)", _FRAME_SHIFT_Z, result.frame_shift_z),
    ]
    for name, cur, cal in rows:
        print(f"  {name:<20s} {cur:>12.4f} {cal:>12.4f} {cal - cur:>+12.4f}")

    print("\n── Helix Parameters ───────────────────────────────────────")
    print(f"  {'Parameter':<25s} {'NADOC':>12s} {'PDB':>12s} {'Delta':>12s}")
    print(f"  {'─' * 25} {'─' * 12} {'─' * 12} {'─' * 12}")
    hrows = [
        ("Helix radius (nm)", HELIX_RADIUS, result.measured_helix_radius),
        ("Twist (deg/bp)", BDNA_TWIST_PER_BP_DEG, result.measured_twist_deg),
        ("Rise (nm/bp)", BDNA_RISE_PER_BP, result.measured_rise_nm),
    ]
    for name, nadoc, pdb in hrows:
        print(f"  {name:<25s} {nadoc:>12.4f} {pdb:>12.4f} {pdb - nadoc:>+12.4f}")

    print("\n── P-atom RMSD ────────────────────────────────────────────")
    print(f"  Before calibration: {result.rmsd_before:.4f} nm  ({result.rmsd_before * 10:.2f} Å)")
    print(f"  After calibration:  {result.rmsd_after:.4f} nm  ({result.rmsd_after * 10:.2f} Å)")

    print("\n── Per-nucleotide Residuals ────────────────────────────────")
    print(f"  {'Chain':>5s} {'Seq':>4s} {'BP':>3s} {'Dir':>7s} {'Δn':>8s} {'Δy':>8s} {'Δz':>8s} {'Rot°':>7s} {'P→ax':>7s}")
    print(f"  {'─' * 5} {'─' * 4} {'─' * 3} {'─' * 7} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 7} {'─' * 7}")
    for entry in result.per_nucleotide:
        print(f"  {entry['chain']:>5s} {entry['seq']:>4d} {entry['bp']:>3d} "
              f"{entry['direction']:>7s} "
              f"{entry['shift_n']:>8.4f} {entry['shift_y']:>8.4f} {entry['shift_z']:>8.4f} "
              f"{entry['rot_deg']:>7.2f} {entry['p_to_axis_nm']:>7.4f}")

    # ── Copy-pasteable Python ─────────────────────────────────────────────
    print("\n── Copy-pasteable Python for atomistic.py ──────────────────")
    print(f"_FRAME_ROT_RAD: float = {result.frame_rot_rad:.6f}  "
          f"# {math.degrees(result.frame_rot_rad):.2f}°  (calibrated from {Path(args.pdb).name})")
    print(f"_FRAME_SHIFT_N: float = {result.frame_shift_n:>8.4f}   # nm along e_n")
    print(f"_FRAME_SHIFT_Y: float = {result.frame_shift_y:>8.4f}   # nm along e_y")
    print(f"_FRAME_SHIFT_Z: float = {result.frame_shift_z:>8.4f}   # nm along e_z")

    # ── Re-extracted templates ────────────────────────────────────────────
    if args.templates:
        print("\n── Re-extracted Templates (with calibrated frame_rot) ─────")
        analysis = analyze_duplex(
            args.pdb,
            chain_a=args.chain_a,
            chain_b=args.chain_b,
            exclude_terminal=args.exclude_terminal,
            frame_rot_rad=result.frame_rot_rad,
        )

        def _print_template(name: str, template: dict, atom_names: list[str]) -> None:
            print(f"\n{name} = (")
            for aname in atom_names:
                if aname in template:
                    c = template[aname]
                    from backend.core.pdb_import import ATOM_ELEMENT
                    elem = ATOM_ELEMENT.get(aname, aname[0])
                    print(f'    ("{aname}", "{elem}", {c[0]:>8.4f}, {c[1]:>8.4f}, {c[2]:>8.4f}),')
            print(")")

        _print_template("_SUGAR", analysis.sugar_template, SUGAR_ATOMS)
        for base_type in ["DA", "DT", "DG", "DC"]:
            if base_type in analysis.base_templates:
                _print_template(f"_{base_type}_BASE", analysis.base_templates[base_type], BASE_ATOMS[base_type])


if __name__ == "__main__":
    main()
