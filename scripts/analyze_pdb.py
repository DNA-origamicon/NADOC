#!/usr/bin/env python3
"""
Analyze a B-DNA PDB file and extract NADOC atomistic template coordinates.

Usage:
    python scripts/analyze_pdb.py Examples/1zew.pdb
    python scripts/analyze_pdb.py Examples/1zew.pdb --chain-a A --chain-b B --exclude 1
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.pdb_import import (
    ATOM_ELEMENT,
    BASE_ATOMS,
    BASE_BONDS,
    SUGAR_ATOMS,
    SUGAR_BONDS,
    DuplexAnalysis,
    analyze_duplex,
)


def _fmt(v: float) -> str:
    """Format a coordinate value to 4 decimal places, right-aligned."""
    return f"{v: .4f}"


def print_sugar_template(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("SUGAR-PHOSPHATE BACKBONE TEMPLATE (averaged over all inner residues)")
    print("=" * 72)

    print(f"\n{'Atom':<6} {'Element':<4} {'n (nm)':>10} {'y (nm)':>10} {'z (nm)':>10}  "
          f"{'σ_n':>8} {'σ_y':>8} {'σ_z':>8}")
    print("-" * 72)

    for name in SUGAR_ATOMS:
        if name not in analysis.sugar_template:
            continue
        c = analysis.sugar_template[name]
        s = analysis.sugar_std.get(name, np.zeros(3))
        el = ATOM_ELEMENT.get(name, "?")
        print(f"{name:<6} {el:<4} {_fmt(c[0]):>10} {_fmt(c[1]):>10} {_fmt(c[2]):>10}  "
              f"{_fmt(s[0]):>8} {_fmt(s[1]):>8} {_fmt(s[2]):>8}")

    # Print pasteable Python
    print("\n# ── Copy-pasteable _SUGAR template ──")
    print("_SUGAR: tuple[_AtomDef, ...] = (")
    for name in SUGAR_ATOMS:
        if name not in analysis.sugar_template:
            continue
        c = analysis.sugar_template[name]
        el = ATOM_ELEMENT.get(name, "?")
        print(f'    ("{name}",{" " * (4 - len(name))} "{el}", {c[0]: .4f}, {c[1]: .4f}, {c[2]: .4f}),')
    print(")")


def print_base_templates(analysis: DuplexAnalysis) -> None:
    for base_type in ["DT", "DC", "DA", "DG"]:
        if base_type not in analysis.base_templates:
            continue
        template = analysis.base_templates[base_type]
        std = analysis.base_std.get(base_type, {})
        atom_names = BASE_ATOMS[base_type]

        print(f"\n{'=' * 72}")
        print(f"{base_type} BASE TEMPLATE (averaged over {len(analysis.base_instances[base_type])} instances)")
        print("=" * 72)

        print(f"\n{'Atom':<6} {'Element':<4} {'n (nm)':>10} {'y (nm)':>10} {'z (nm)':>10}  "
              f"{'σ_n':>8} {'σ_y':>8} {'σ_z':>8}")
        print("-" * 72)

        for name in atom_names:
            if name not in template:
                continue
            c = template[name]
            s = std.get(name, np.zeros(3))
            el = ATOM_ELEMENT.get(name, "?")
            print(f"{name:<6} {el:<4} {_fmt(c[0]):>10} {_fmt(c[1]):>10} {_fmt(c[2]):>10}  "
                  f"{_fmt(s[0]):>8} {_fmt(s[1]):>8} {_fmt(s[2]):>8}")

        # Pasteable
        var_name = f"_{base_type}_BASE"
        print(f"\n# ── Copy-pasteable {var_name} template ──")
        print(f"{var_name}: tuple[_AtomDef, ...] = (")
        for name in atom_names:
            if name not in template:
                continue
            c = template[name]
            el = ATOM_ELEMENT.get(name, "?")
            print(f'    ("{name}",{" " * (4 - len(name))} "{el}", {c[0]: .4f}, {c[1]: .4f}, {c[2]: .4f}),')
        print(")")


def print_comparison(analysis: DuplexAnalysis) -> None:
    """Compare extracted templates against current hard-coded values from atomistic.py."""
    print("\n" + "=" * 72)
    print("COMPARISON: New (1zew) vs Current (1BNA-derived) templates")
    print("=" * 72)

    # Current values from atomistic.py
    current_sugar = {
        "P":   ( -0.0158,  0.1754,  0.2763),
        "OP1": (  0.0175,  0.2582,  0.3945),
        "OP2": ( -0.1155,  0.2428,  0.1900),
        "O5'": (  0.1166,  0.1473,  0.1923),
        "C5'": (  0.2387,  0.1760,  0.2625),
        "C4'": (  0.3480,  0.1688,  0.1601),
        "O4'": (  0.4507,  0.0727,  0.1371),
        "C3'": (  0.3137,  0.2229,  0.0213),
        "O3'": (  0.3961,  0.3331, -0.0145),
        "C2'": (  0.3454,  0.1044, -0.0699),
        "C1'": (  0.4657,  0.0420,  0.0000),
    }

    current_bases = {
        "DT": {
            "N1": (0.4693, -0.1066, 0.0), "C2": (0.5929, -0.1659, 0.0),
            "O2": (0.6967, -0.1021, 0.0), "N3": (0.5922, -0.3038, 0.0),
            "C4": (0.4808, -0.3853, 0.0), "O4": (0.4929, -0.5078, 0.0),
            "C5": (0.3558, -0.3141, 0.0), "C6": (0.3536, -0.1800, 0.0),
            "C7": (0.2297, -0.3954, 0.0),
        },
        "DC": {
            "N1": (0.4693, -0.1067, 0.0), "C2": (0.5938, -0.1682, 0.0),
            "O2": (0.6952, -0.0975, 0.0), "N3": (0.5991, -0.3036, 0.0),
            "C4": (0.4869, -0.3766, 0.0), "N4": (0.4975, -0.5084, 0.0),
            "C5": (0.3578, -0.3153, 0.0), "C6": (0.3547, -0.1798, 0.0),
        },
        "DA": {
            "N9": (0.4693, -0.1067, 0.0), "C8": (0.3647, -0.1961, 0.0),
            "N7": (0.4013, -0.3202, 0.0), "C5": (0.5397, -0.3138, 0.0),
            "C4": (0.5818, -0.1841, 0.0), "N3": (0.7094, -0.1405, 0.0),
            "C2": (0.7929, -0.2416, 0.0), "N1": (0.7667, -0.3721, 0.0),
            "C6": (0.6387, -0.4129, 0.0), "N6": (0.6117, -0.5441, 0.0),
        },
        "DG": {
            "N9": (0.4693, -0.1067, 0.0), "C8": (0.3648, -0.1965, 0.0),
            "N7": (0.4022, -0.3219, 0.0), "C5": (0.5412, -0.3146, 0.0),
            "C4": (0.5831, -0.1837, 0.0), "N3": (0.7099, -0.1353, 0.0),
            "C2": (0.8005, -0.2324, 0.0), "N2": (0.9306, -0.2035, 0.0),
            "N1": (0.7678, -0.3664, 0.0), "C6": (0.6375, -0.4182, 0.0),
            "O6": (0.6199, -0.5395, 0.0),
        },
    }

    # Sugar comparison
    print(f"\n{'Atom':<6} {'Δn (nm)':>10} {'Δy (nm)':>10} {'Δz (nm)':>10} {'|Δ| (nm)':>10}")
    print("-" * 50)
    for name in SUGAR_ATOMS:
        if name in analysis.sugar_template and name in current_sugar:
            new = analysis.sugar_template[name]
            old = np.array(current_sugar[name])
            delta = new - old
            mag = float(np.linalg.norm(delta))
            print(f"{name:<6} {_fmt(delta[0]):>10} {_fmt(delta[1]):>10} {_fmt(delta[2]):>10} {_fmt(mag):>10}")

    for base_type in ["DT", "DC", "DA", "DG"]:
        if base_type not in analysis.base_templates or base_type not in current_bases:
            continue
        print(f"\n{base_type}:")
        print(f"{'Atom':<6} {'Δn (nm)':>10} {'Δy (nm)':>10} {'Δz (nm)':>10} {'|Δ| (nm)':>10}")
        print("-" * 50)
        for name in BASE_ATOMS[base_type]:
            if name in analysis.base_templates[base_type] and name in current_bases[base_type]:
                new = analysis.base_templates[base_type][name]
                old = np.array(current_bases[base_type][name])
                delta = new - old
                mag = float(np.linalg.norm(delta))
                print(f"{name:<6} {_fmt(delta[0]):>10} {_fmt(delta[1]):>10} {_fmt(delta[2]):>10} {_fmt(mag):>10}")


def print_backbone_steps(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("BACKBONE STEP PARAMETERS (chain A inner residues)")
    print("=" * 72)
    print(f"NADOC constants: rise = 0.334 nm, twist = 34.3 deg")
    print(f"\n{'Step':<12} {'Rise (nm)':>10} {'Twist (deg)':>12} {'Slide (nm)':>10} {'Shift (nm)':>10}")
    print("-" * 58)

    rises = []
    twists = []
    for step in analysis.backbone_steps:
        print(f"{step.label:<12} {step.rise_nm:>10.4f} {step.twist_deg:>12.2f} "
              f"{step.slide_nm:>10.4f} {step.shift_nm:>10.4f}")
        rises.append(step.rise_nm)
        twists.append(step.twist_deg)

    if rises:
        print(f"\n{'Mean':>12} {np.mean(rises):>10.4f} {np.mean(twists):>12.2f}")
        print(f"{'Std':>12} {np.std(rises):>10.4f} {np.std(twists):>12.2f}")


def print_wc_pairs(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("WATSON-CRICK BASE PAIR GEOMETRY")
    print("=" * 72)
    print(f"\n{'Pair':<35} {'C1\'-C1\' (nm)':>12} {'Propeller (deg)':>16}")
    print("-" * 65)

    c1_dists = []
    for wc in analysis.wc_pairs:
        print(f"{wc.pair_label:<35} {wc.c1_c1_distance_nm:>12.4f} {wc.propeller_twist_deg:>16.2f}")
        c1_dists.append(wc.c1_c1_distance_nm)
        if wc.hbond_distances_nm:
            for bond_name, dist in wc.hbond_distances_nm.items():
                print(f"  H-bond {bond_name}: {dist:.4f} nm")

    if c1_dists:
        print(f"\nMean C1'-C1': {np.mean(c1_dists):.4f} nm (expected ~1.085 nm)")


def print_chi_and_pucker(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("GLYCOSIDIC CHI ANGLE AND SUGAR PUCKER")
    print("=" * 72)
    print(f"\n{'Residue':<12} {'Chi (deg)':>10} {'Pucker P (deg)':>15} {'Ampl (deg)':>12} {'Conformation':<15}")
    print("-" * 70)

    for key in sorted(analysis.chi_angles.keys()):
        chi_vals = analysis.chi_angles[key]
        chi = chi_vals[0] if chi_vals else 0.0
        pucker = analysis.sugar_puckers.get(key, (0.0, 0.0, "?"))
        print(f"{key:<12} {chi:>10.1f} {pucker[0]:>15.1f} {pucker[1]:>12.1f} {pucker[2]:<15}")


def print_bond_distances(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("INTRA-RESIDUE BOND DISTANCES (nm)")
    print("=" * 72)

    # Collect all bond distances and average by bond type and residue type
    # Group by residue type
    by_restype: dict[str, dict[tuple[str, str], list[float]]] = {}
    for key, bonds in analysis.bond_distances.items():
        # Determine residue type from the bond set (look for base-specific bonds)
        chain, seq_str = key.split(":")
        # We have sugar + base bonds — group all together
        for (a1, a2), dist in bonds.items():
            by_restype.setdefault("ALL", {}).setdefault((a1, a2), []).append(dist)

    # Print averaged bond distances
    print("\nAveraged across all inner residues:")
    print(f"{'Bond':<14} {'Mean (nm)':>10} {'Std (nm)':>10} {'Mean (Å)':>10} {'N':>4}")
    print("-" * 52)

    # Sugar bonds first
    for a1, a2 in SUGAR_BONDS:
        key = (a1, a2)
        if key in by_restype.get("ALL", {}):
            dists = by_restype["ALL"][key]
            mean = np.mean(dists)
            std = np.std(dists)
            print(f"{a1}-{a2:<10} {mean:>10.4f} {std:>10.4f} {mean*10:>10.3f} {len(dists):>4}")

    # Base bonds by type
    for restype in ["DC", "DT", "DA", "DG"]:
        if restype not in BASE_BONDS:
            continue
        # Collect for this res type
        res_bonds: dict[tuple[str, str], list[float]] = {}
        for key, bonds in analysis.bond_distances.items():
            for (a1, a2), dist in bonds.items():
                if (a1, a2) in [(b1, b2) for b1, b2 in BASE_BONDS[restype]]:
                    res_bonds.setdefault((a1, a2), []).append(dist)

        if res_bonds:
            print(f"\n{restype} base bonds:")
            for a1, a2 in BASE_BONDS[restype]:
                key = (a1, a2)
                if key in res_bonds:
                    dists = res_bonds[key]
                    mean = np.mean(dists)
                    std = np.std(dists)
                    print(f"  {a1}-{a2:<10} {mean:>10.4f} {std:>10.4f} {mean*10:>10.3f} {len(dists):>4}")


def print_ribose_base_rotations(analysis: DuplexAnalysis) -> None:
    print("\n" + "=" * 72)
    print("RIBOSE-TO-BASE ROTATION MATRICES")
    print("=" * 72)

    for key in sorted(analysis.ribose_base_rotations.keys()):
        R = analysis.ribose_base_rotations[key]
        # Compute rotation angle
        trace = float(np.trace(R))
        angle = math.degrees(math.acos(np.clip((trace - 1.0) / 2.0, -1.0, 1.0)))
        print(f"\n{key}: rotation angle = {angle:.1f} deg")
        for row in R:
            print(f"  [{row[0]:>8.4f} {row[1]:>8.4f} {row[2]:>8.4f}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze B-DNA PDB for NADOC atomistic templates")
    parser.add_argument("pdb", help="Path to PDB file")
    parser.add_argument("--chain-a", default="A", help="Chain ID for strand A (default: A)")
    parser.add_argument("--chain-b", default="B", help="Chain ID for strand B (default: B)")
    parser.add_argument("--exclude", type=int, default=1, help="Terminal residues to exclude (default: 1)")
    parser.add_argument("--frame-rot", type=float, default=39.0, help="Frame rotation in degrees (default: 39.0)")
    args = parser.parse_args()

    print(f"Analyzing: {args.pdb}")
    print(f"Chains: {args.chain_a}/{args.chain_b}, excluding {args.exclude} terminal residue(s) per end")
    print(f"Frame rotation: {args.frame_rot} deg")

    analysis = analyze_duplex(
        args.pdb,
        chain_a=args.chain_a,
        chain_b=args.chain_b,
        exclude_terminal=args.exclude,
        frame_rot_rad=math.radians(args.frame_rot),
    )

    print_sugar_template(analysis)
    print_base_templates(analysis)
    print_comparison(analysis)
    print_backbone_steps(analysis)
    print_wc_pairs(analysis)
    print_bond_distances(analysis)
    print_chi_and_pucker(analysis)
    print_ribose_base_rotations(analysis)

    print("\n" + "=" * 72)
    print("ANALYSIS COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
