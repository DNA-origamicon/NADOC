#!/usr/bin/env python3
"""
extract_rev_templates.py — Extract REVERSE strand base templates from 1ZEW chain B.

The FORWARD strand templates in atomistic.py were extracted from chain A (1ZEW).
When the same templates are applied to the REVERSE strand, H-bond donor/acceptor
atoms land on the wrong side of the helix because the FWD and REV strand frames
differ by ~134.5° in azimuth.

This script extracts chain B (REVERSE strand) base atom coordinates in the same
local frame that _atom_frame() would use for a REVERSE strand nucleotide, so that
the resulting templates produce correct WC H-bond geometry when placed in that frame.

Pairing in 1ZEW (CCTCTAGAGG palindrome, 10 bp):
  Chain A residues 1-10 (5'→3') pair with Chain B residues 20-11 (5'→3')
  i.e., A:n pairs with B:(21-n)

  Inner residues (3-8 on each chain):
    A:3  (DT) ↔ B:18 (DA)
    A:4  (DC) ↔ B:17 (DG)
    A:5  (DT) ↔ B:16 (DA)
    A:6  (DA) ↔ B:15 (DT)
    A:7  (DG) ↔ B:14 (DC)
    A:8  (DA) ↔ B:13 (DT)

  Available inner chain B residues by type:
    DT: B:13, B:15
    DC: B:14
    DA: B:16, B:18
    DG: B:17

Frame convention (NADOC _atom_frame, REVERSE strand):
  origin  = P position (radially corrected to _ATOMISTIC_P_RADIUS from axis)
  e_n     = inward radial (after P-P azimuthal correction for B-DNA 208.2°)
  e_z     = +axis_tangent  (3'→5' direction of REVERSE strand)
  e_y     = cross(e_z, e_n)
  Then rotate by _FRAME_ROT_RAD = −37.05° around e_z.
  Template coordinates (n, y, z) satisfy: world = origin + R @ [n, y, z]^T

Usage:
    python scripts/extract_rev_templates.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np

# ── Constants matching atomistic.py ──────────────────────────────────────────

_ATOMISTIC_P_RADIUS: float = 0.886         # nm
_FRAME_ROT_RAD: float = -0.646577          # −37.05°
_ATOMISTIC_PP_SEP_RAD: float = math.radians(208.2)       # CCW FWD→REV in B-DNA
_ATOMISTIC_TOPOLOGY_GROOVE_RAD: float = math.radians(150.0)

# P-P correction for REVERSE strand in a FORWARD helix cell (1ZEW is FWD helix):
_PP_DELTA: float = _ATOMISTIC_PP_SEP_RAD - _ATOMISTIC_TOPOLOGY_GROOVE_RAD  # +58.2°

# ── Parse 1ZEW ──────────────────────────────────────────────────────────────


def parse_pdb(path: str) -> dict[tuple[str, int], dict[str, np.ndarray]]:
    """Returns {(chain, resnum): {atom_name: xyz_nm}} for ATOM records."""
    records: dict[tuple[str, int], dict[str, np.ndarray]] = defaultdict(dict)
    with open(path) as fh:
        for line in fh:
            if not line.startswith("ATOM"):
                continue
            atom_name = line[12:16].strip()
            resname   = line[17:20].strip()  # noqa: F841
            chain     = line[21].strip()
            resnum    = int(line[22:26].strip())
            x = float(line[30:38]) / 10.0  # Å → nm
            y = float(line[38:46]) / 10.0
            z = float(line[46:54]) / 10.0
            records[(chain, resnum)][atom_name] = np.array([x, y, z])
    return dict(records)


# ── Helix axis ───────────────────────────────────────────────────────────────


def compute_helix_axis(records: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute helix axis from midpoints of paired C1' atoms.
    Returns (axis_origin, axis_tangent) where axis_tangent points in the
    direction of increasing residue number along chain A (5'→3').
    """
    # Chain A residues 1-10 pair with chain B residues 20-11
    midpoints = []
    for a_res in range(1, 11):
        b_res = 21 - a_res
        c1_a = records.get(("A", a_res), {}).get("C1'")
        c1_b = records.get(("B", b_res), {}).get("C1'")
        if c1_a is not None and c1_b is not None:
            midpoints.append(0.5 * (c1_a + c1_b))

    pts = np.array(midpoints)  # shape (N, 3)
    center = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - center)
    axis_dir = Vt[0]  # principal component

    # Ensure axis_dir points in direction of increasing A-chain residue (5'→3')
    # Compare direction from midpoint[0] to midpoint[-1]
    dominant = pts[-1] - pts[0]
    if np.dot(axis_dir, dominant) < 0:
        axis_dir = -axis_dir

    return center, axis_dir


# ── Per-residue frame ────────────────────────────────────────────────────────


def rev_strand_frame(
    p_world: np.ndarray,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute (origin, R) for a REVERSE strand nucleotide in a FORWARD helix cell,
    matching the frame that _atom_frame() produces AFTER the P-P azimuthal
    correction.

    The 1ZEW chain B P atoms are already at the real B-DNA azimuth (fwd+208.2°),
    which is exactly where _atom_frame places the corrected origin.  Therefore
    no additional P-P rotation is applied here — the 1ZEW P IS the post-correction
    origin.  Applying the correction again would rotate the frame by an extra 58.2°
    and produce templates that land at the wrong azimuth.

    origin = actual 1ZEW P position (radially clamped to _ATOMISTIC_P_RADIUS)
    R      = 3×3 rotation: template (n,y,z) → world
    """
    # Project P onto axis to find axis_point (foot of perpendicular)
    t_val = np.dot(p_world - axis_origin, axis_tangent)
    axis_pt = axis_origin + t_val * axis_tangent

    # Outward radial from axis to P (perpendicular to axis)
    radial = p_world - axis_pt
    r_norm = np.linalg.norm(radial)
    assert r_norm > 1e-9, f"P is on the axis? r={r_norm}"
    e_radial = radial / r_norm

    # Clamp P to canonical radius (1ZEW inner residues average ~0.886 nm already)
    bb = axis_pt + _ATOMISTIC_P_RADIUS * e_radial

    # Build frame — no P-P correction here; the 1ZEW P is already at the
    # post-correction azimuth that _atom_frame will produce in NADOC.
    e_n = -e_radial                   # inward (same direction as _atom_frame post-correction)
    e_z = +axis_tangent               # REVERSE strand: e_z = +axis_tangent
    e_y = np.cross(e_z, e_n)
    e_y /= np.linalg.norm(e_y)

    origin = bb
    R = np.column_stack([e_n, e_y, e_z])

    # Cancel template pre-compensation (+37.05° baked in to all templates)
    c, s = math.cos(_FRAME_ROT_RAD), math.sin(_FRAME_ROT_RAD)
    R = R @ np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])

    return origin, R


# ── Template extraction ──────────────────────────────────────────────────────

# Chain B residue definitions (inner residues only)
_CHAIN_B_INNER = {
    13: "DT",
    14: "DC",
    15: "DT",
    16: "DA",
    17: "DG",
    18: "DA",
}

_BASE_ATOMS: dict[str, list[str]] = {
    "DT": ["N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"],
    "DC": ["N1", "C2", "O2", "N3", "C4", "N4", "C5", "C6"],
    "DA": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6", "N6"],
    "DG": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N2", "N1", "C6", "O6"],
}

_BASE_ELEMS: dict[str, list[str]] = {
    "DT": ["N", "C", "O", "N", "C", "O", "C", "C", "C"],
    "DC": ["N", "C", "O", "N", "C", "N", "C", "C"],
    "DA": ["N", "C", "N", "C", "C", "N", "C", "N", "C", "N"],
    "DG": ["N", "C", "N", "C", "C", "N", "C", "N", "N", "C", "O"],
}


def extract_templates(
    records: dict,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> dict[str, list[tuple[str, str, float, float, float]]]:
    """
    For each inner chain B residue, compute the REVERSE strand frame and express
    base atom world positions in template (n, y, z) coordinates.
    Returns averaged templates per residue type.
    """
    # Accumulate per-type template coords
    accum: dict[str, list[dict[str, np.ndarray]]] = defaultdict(list)

    for resnum, restype in sorted(_CHAIN_B_INNER.items()):
        atoms = records.get(("B", resnum))
        if atoms is None:
            print(f"  WARNING: B:{resnum} not found in PDB")
            continue

        p_world = atoms.get("P")
        if p_world is None:
            print(f"  WARNING: B:{resnum} has no P atom")
            continue

        origin, R = rev_strand_frame(p_world, axis_origin, axis_tangent)

        # Express base atoms in template frame: t = R^T @ (world - origin)
        atom_tmpl: dict[str, np.ndarray] = {}
        for aname in _BASE_ATOMS[restype]:
            w = atoms.get(aname)
            if w is None:
                print(f"  WARNING: B:{resnum} {restype} missing {aname}")
                continue
            atom_tmpl[aname] = R.T @ (w - origin)

        # Also extract C1' template coords (for z=0 convention check)
        c1p = atoms.get("C1'")
        if c1p is not None:
            atom_tmpl["C1'"] = R.T @ (c1p - origin)

        accum[restype].append(atom_tmpl)

        # Diagnostics
        c1p_tmpl = atom_tmpl.get("C1'")
        z_offset = c1p_tmpl[2] if c1p_tmpl is not None else float("nan")
        print(f"  B:{resnum} {restype}  C1' template z={z_offset:.4f} nm  "
              f"(should be near 0 after shift)")

    # Average and apply C1' z=0 shift
    result: dict[str, list[tuple[str, str, float, float, float]]] = {}
    for restype, instances in accum.items():
        # Average each atom across instances
        all_atoms = _BASE_ATOMS[restype]
        avg: dict[str, np.ndarray] = {}
        for aname in all_atoms:
            coords_list = [inst[aname] for inst in instances if aname in inst]
            if coords_list:
                avg[aname] = np.mean(coords_list, axis=0)

        # Compute average C1' z (from sugar — take from the instances dict)
        c1p_zs = [inst["C1'"][2] for inst in instances if "C1'" in inst]
        z_shift = float(np.mean(c1p_zs)) if c1p_zs else 0.0
        print(f"  {restype}: applying z_shift = {z_shift:.4f} nm to base atoms")

        result[restype] = []
        for i, aname in enumerate(all_atoms):
            if aname not in avg:
                print(f"  WARNING: {restype} missing averaged {aname}")
                continue
            n_val, y_val, z_val = avg[aname]
            z_val -= z_shift
            elem = _BASE_ELEMS[restype][i]
            result[restype].append((aname, elem, float(n_val), float(y_val), float(z_val)))

    return result


def print_template(restype: str, atoms: list[tuple]) -> None:
    """Print a template in the atomistic.py format."""
    print(f"\n_{restype}_BASE_REV: tuple[_AtomDef, ...] = (")
    print(f"    # Extracted from 1ZEW chain B inner residues {sorted(_CHAIN_B_INNER.keys())}.")
    print(f"    # REVERSE strand frame: e_z=+axis_tangent, P-P correction +58.2° (FWD helix).")
    for name, elem, n, y, z in atoms:
        print(f'    ("{name}", "{elem}", {n:8.4f}, {y:8.4f}, {z:8.4f}),')
    print(")")


def main():
    pdb_path = Path(__file__).resolve().parent.parent / "Examples" / "1zew.pdb"
    if not pdb_path.exists():
        print(f"ERROR: {pdb_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {pdb_path} ...")
    records = parse_pdb(str(pdb_path))
    print(f"  Found {len(records)} residues")

    print("\nComputing helix axis from C1' midpoints ...")
    axis_origin, axis_tangent = compute_helix_axis(records)
    print(f"  axis_tangent = [{axis_tangent[0]:.4f}, {axis_tangent[1]:.4f}, {axis_tangent[2]:.4f}]")

    print("\nExtracting REVERSE strand templates from chain B inner residues ...")
    templates = extract_templates(records, axis_origin, axis_tangent)

    print("\n" + "=" * 60)
    print("REVERSE STRAND BASE TEMPLATES")
    print("=" * 60)
    for restype in ["DT", "DC", "DA", "DG"]:
        if restype in templates:
            print_template(restype, templates[restype])
        else:
            print(f"\n  WARNING: no template extracted for {restype}")

    # Also print H-bond atom positions for verification
    print("\n" + "=" * 60)
    print("TEMPLATE H-BOND ATOMS (verification)")
    print("=" * 60)
    hbond_atoms = {
        "DT": ["O4", "N3", "O2"],
        "DC": ["N4", "N3", "O2"],
        "DA": ["N6", "N1"],
        "DG": ["O6", "N1", "N2"],
    }
    for restype, atoms_of_interest in hbond_atoms.items():
        if restype not in templates:
            continue
        print(f"\n{restype} REV template H-bond atoms:")
        tmpl_dict = {a: (n, y, z) for a, _, n, y, z in templates[restype]}
        for aname in atoms_of_interest:
            if aname in tmpl_dict:
                n, y, z = tmpl_dict[aname]
                print(f"  {aname:4s}: n={n:7.4f}  y={y:7.4f}  z={z:7.4f}")


if __name__ == "__main__":
    main()
