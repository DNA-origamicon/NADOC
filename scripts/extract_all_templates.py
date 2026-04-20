#!/usr/bin/env python3
"""
extract_all_templates.py — Extract ALL base + sugar templates from 1ZEW in the
                           production _atom_frame radial frame convention.

MOTIVATION
----------
The original SUGAR and FWD BASE templates were extracted using the cross-strand
C1'→C1' direction as e_n.  The production _atom_frame() uses the helix-axis
inward radial (-e_radial) as e_n.  These two directions differ, causing chi
angles to be inconsistent and H-bond geometry to be wrong.

This script uses the same radial frame as _atom_frame() for ALL templates (SUGAR,
FWD BASE, REV BASE), ensuring self-consistency.

FRAME CONVENTION (matching _atom_frame exactly)
-----------------------------------------------
For a FWD strand residue (chain A):
  origin  = P position, radially clamped to _ATOMISTIC_P_RADIUS from helix axis
  e_n     = -e_radial  (inward; P-P correction NOT applied for FWD strand)
  e_z     = -axis_tangent  (FWD strand: template z points 3'→5' = against +axis)
  e_y     = cross(e_z, e_n)
  Then rotate by _FRAME_ROT_RAD = −37.05° around e_z.

For a REV strand residue (chain B in a FWD helix):
  origin  = P position, radially clamped (1ZEW chain B P is already at
            fwd+208.2° — the post-correction target — so no extra rotation needed)
  e_n     = -e_radial  (inward from the 208.2° position)
  e_z     = +axis_tangent  (REV strand: template z points 3'→5' = with +axis)
  e_y     = cross(e_z, e_n)
  Then rotate by _FRAME_ROT_RAD = −37.05° around e_z.

All atom coordinates (n, y, z) satisfy: world = origin + R @ [n, y, z]^T.
C1' z is shifted to 0 in all templates (base coplanarity convention).

SUGAR: extracted from chain A residue 5 (DT), single residue — averaging is
valid in the radial frame but single reference gives exact bond lengths.

FWD BASE: averaged over inner chain A residues (A:3–A:8) by residue type.
REV BASE: averaged over inner chain B residues (B:13–B:18) by residue type.

Usage:
    python scripts/extract_all_templates.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np

# ── Constants matching atomistic.py ──────────────────────────────────────────

_ATOMISTIC_P_RADIUS: float = 0.886          # nm
_FRAME_ROT_RAD: float = -0.646577           # −37.05°

# ── Residue definitions ───────────────────────────────────────────────────────

_CHAIN_A_INNER = {
    3: "DT",
    4: "DC",
    5: "DT",
    6: "DA",
    7: "DG",
    8: "DA",
}

_CHAIN_B_INNER = {
    13: "DT",
    14: "DC",
    15: "DT",
    16: "DA",
    17: "DG",
    18: "DA",
}

_SUGAR_ATOMS: list[str] = ["P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'",
                            "C3'", "O3'", "C2'", "C1'"]
_SUGAR_ELEMS: list[str] = ["P", "O",   "O",   "O",   "C",   "C",   "O",
                            "C",   "O",   "C",   "C"]

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


# ── PDB parser ────────────────────────────────────────────────────────────────

def parse_pdb(path: str) -> dict[tuple[str, int], dict[str, np.ndarray]]:
    """Returns {(chain, resnum): {atom_name: xyz_nm}} for ATOM records."""
    records: dict[tuple[str, int], dict[str, np.ndarray]] = defaultdict(dict)
    with open(path) as fh:
        for line in fh:
            if not line.startswith("ATOM"):
                continue
            atom_name = line[12:16].strip()
            chain     = line[21].strip()
            resnum    = int(line[22:26].strip())
            x = float(line[30:38]) / 10.0
            y = float(line[38:46]) / 10.0
            z = float(line[46:54]) / 10.0
            records[(chain, resnum)][atom_name] = np.array([x, y, z])
    return dict(records)


# ── Helix axis ────────────────────────────────────────────────────────────────

def compute_helix_axis(records: dict) -> tuple[np.ndarray, np.ndarray]:
    """SVD of C1' midpoints; axis_tangent points in increasing chain-A residue direction."""
    midpoints = []
    for a_res in range(1, 11):
        b_res = 21 - a_res
        c1_a = records.get(("A", a_res), {}).get("C1'")
        c1_b = records.get(("B", b_res), {}).get("C1'")
        if c1_a is not None and c1_b is not None:
            midpoints.append(0.5 * (c1_a + c1_b))
    pts = np.array(midpoints)
    center = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - center)
    axis_dir = Vt[0]
    dominant = pts[-1] - pts[0]
    if np.dot(axis_dir, dominant) < 0:
        axis_dir = -axis_dir
    return center, axis_dir


# ── Frame builder ─────────────────────────────────────────────────────────────

_PP_SEP_RAD: float = math.radians(208.2)  # canonical FWD→REV P-P azimuthal separation


def build_frame_fwd(
    p_world: np.ndarray,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    FWD strand frame: origin at actual A:n P (clamped to canonical radius).
    e_n = -e_radial (inward), e_z = -axis_tangent, e_y = cross(e_z, e_n).
    Then _FRAME_ROT_RAD applied.  Matches _atom_frame(direction=FORWARD).
    """
    t_val = np.dot(p_world - axis_origin, axis_tangent)
    axis_pt = axis_origin + t_val * axis_tangent
    radial = p_world - axis_pt
    r_norm = np.linalg.norm(radial)
    assert r_norm > 1e-9
    e_radial = radial / r_norm
    origin = axis_pt + _ATOMISTIC_P_RADIUS * e_radial

    e_n = -e_radial
    e_z = -axis_tangent          # FWD: e_z = 3'→5' = -axis_tangent
    e_y = np.cross(e_z, e_n)
    e_y /= np.linalg.norm(e_y)
    R = np.column_stack([e_n, e_y, e_z])
    c, s = math.cos(_FRAME_ROT_RAD), math.sin(_FRAME_ROT_RAD)
    R = R @ np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    return origin, R


def build_frame_rev(
    fwd_p_world: np.ndarray,
    rev_p_world: np.ndarray,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    REV strand frame using the CANONICAL P-P geometry that _atom_frame produces.

    In production, _atom_frame(direction=REVERSE) places the REV P at:
      FWD_azimuth + 208.2°, canonical radius.
    We reproduce that here by rotating the FWD e_radial by +208.2° around
    axis_tangent and using the REV P's axial height.

    This ensures FWD+REV templates extracted together reproduce the crystal
    H-bond distances when placed in the production model, regardless of the
    actual 1ZEW P-P angle (which varies ±10° due to Holliday junction distortion).
    """
    # FWD P azimuth → e_radial_fwd
    t_fwd = np.dot(fwd_p_world - axis_origin, axis_tangent)
    foot_fwd = axis_origin + t_fwd * axis_tangent
    rad_fwd = fwd_p_world - foot_fwd
    r_fwd = np.linalg.norm(rad_fwd)
    assert r_fwd > 1e-9
    e_radial_fwd = rad_fwd / r_fwd

    # Rotate FWD azimuth by +208.2° to get canonical REV azimuth
    cd, sd = math.cos(_PP_SEP_RAD), math.sin(_PP_SEP_RAD)
    e_radial_rev = cd * e_radial_fwd + sd * np.cross(axis_tangent, e_radial_fwd)

    # REV P axial height
    t_rev = np.dot(rev_p_world - axis_origin, axis_tangent)
    foot_rev = axis_origin + t_rev * axis_tangent

    # Canonical REV origin
    origin = foot_rev + _ATOMISTIC_P_RADIUS * e_radial_rev

    e_n = -e_radial_rev
    e_z = +axis_tangent          # REV: e_z = 3'→5' = +axis_tangent
    e_y = np.cross(e_z, e_n)
    e_y /= np.linalg.norm(e_y)
    R = np.column_stack([e_n, e_y, e_z])
    c, s = math.cos(_FRAME_ROT_RAD), math.sin(_FRAME_ROT_RAD)
    R = R @ np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    return origin, R


# ── Extraction helpers ────────────────────────────────────────────────────────

def world_to_tmpl(world: np.ndarray, origin: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Express a world position in template (n,y,z) coordinates."""
    return R.T @ (world - origin)


def extract_tmpl_atoms(
    atoms: dict[str, np.ndarray],
    atom_names: list[str],
    origin: np.ndarray,
    R: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return {name: (n,y,z)} for each named atom, in template frame."""
    result = {}
    for name in atom_names:
        w = atoms.get(name)
        if w is None:
            print(f"    WARNING: missing {name}")
        else:
            result[name] = world_to_tmpl(w, origin, R)
    return result


# ── SUGAR extraction ─────────────────────────────────────────────────────────

def extract_sugar(
    records: dict,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
    ref_resnum: int = 5,
) -> list[tuple[str, str, float, float, float]]:
    """
    Extract the sugar-phosphate backbone from chain A residue ref_resnum.
    Single-residue extraction (not averaged) — exact bond lengths.
    Returns z-shifted list so C1' z = 0.
    """
    atoms = records[("A", ref_resnum)]
    p_world = atoms["P"]
    origin, R = build_frame_fwd(p_world, axis_origin, axis_tangent)

    tmpl = extract_tmpl_atoms(atoms, _SUGAR_ATOMS, origin, R)

    # C1' z shift
    z_shift = float(tmpl["C1'"][2])
    print(f"  Sugar (A:{ref_resnum}): C1' z = {z_shift:.4f} nm → shifting to 0")

    result = []
    for name, elem in zip(_SUGAR_ATOMS, _SUGAR_ELEMS):
        if name not in tmpl:
            continue
        n, y, z = tmpl[name]
        result.append((name, elem, float(n), float(y), float(z - z_shift)))
    return result


# ── Base template extraction ──────────────────────────────────────────────────

def extract_bases(
    records: dict,
    inner_residues: dict[int, str],
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
    is_fwd: bool,
) -> dict[str, list[tuple[str, str, float, float, float]]]:
    """
    Extract base atom templates for all inner residues.
    Averages per residue type.  C1' z shift applied per residue before averaging.
    Returns {restype: [(name, elem, n, y, z), ...]}.

    For REV (chain B), the frame uses the CANONICAL P-P geometry: the REV P
    origin is placed at FWD_partner_azimuth + 208.2°, matching _atom_frame().
    """
    chain = "A" if is_fwd else "B"
    accum: dict[str, list[dict[str, np.ndarray]]] = defaultdict(list)

    for resnum, restype in sorted(inner_residues.items()):
        atoms = records.get((chain, resnum))
        if atoms is None:
            print(f"    WARNING: {chain}:{resnum} not found")
            continue
        p_world = atoms.get("P")
        if p_world is None:
            print(f"    WARNING: {chain}:{resnum} has no P atom")
            continue

        if is_fwd:
            origin, R = build_frame_fwd(p_world, axis_origin, axis_tangent)
        else:
            # For REV, use canonical P-P geometry from paired FWD P azimuth
            fwd_partner = 21 - resnum          # A:(21-n) pairs with B:n
            fwd_atoms = records.get(("A", fwd_partner), {})
            fwd_p = fwd_atoms.get("P")
            if fwd_p is None:
                print(f"    WARNING: A:{fwd_partner} P not found for pairing B:{resnum}")
                continue
            origin, R = build_frame_rev(fwd_p, p_world, axis_origin, axis_tangent)

        # Extract base atoms
        tmpl = extract_tmpl_atoms(atoms, _BASE_ATOMS[restype], origin, R)

        # C1' for z-shift
        c1p = atoms.get("C1'")
        if c1p is None:
            print(f"    WARNING: {chain}:{resnum} has no C1' atom")
            continue
        c1p_tmpl = world_to_tmpl(c1p, origin, R)
        z_shift = float(c1p_tmpl[2])

        # Apply z-shift to base atoms
        shifted = {name: coords - np.array([0., 0., z_shift])
                   for name, coords in tmpl.items()}

        r_actual = np.linalg.norm(p_world - (axis_origin + np.dot(p_world - axis_origin, axis_tangent) * axis_tangent))
        print(f"  {chain}:{resnum} {restype}  C1' z={z_shift:.4f} nm  P-to-axis r={r_actual:.4f} nm")

        accum[restype].append(shifted)

    # Average per residue type
    result: dict[str, list[tuple[str, str, float, float, float]]] = {}
    for restype, instances in accum.items():
        all_atoms = _BASE_ATOMS[restype]
        avg: dict[str, np.ndarray] = {}
        for aname in all_atoms:
            coords_list = [inst[aname] for inst in instances if aname in inst]
            if coords_list:
                avg[aname] = np.mean(coords_list, axis=0)

        result[restype] = []
        for i, aname in enumerate(all_atoms):
            if aname not in avg:
                print(f"    WARNING: {restype} missing averaged {aname}")
                continue
            n, y, z = avg[aname]
            elem = _BASE_ELEMS[restype][i]
            result[restype].append((aname, elem, float(n), float(y), float(z)))

    return result


# ── Chi measurement (verify) ──────────────────────────────────────────────────

def dihedral(p0, p1, p2, p3) -> float:
    """Dihedral angle p0-p1-p2-p3 in degrees."""
    b1 = np.array(p1) - np.array(p0)
    b2 = np.array(p2) - np.array(p1)
    b3 = np.array(p3) - np.array(p2)
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    n1n = np.linalg.norm(n1)
    n2n = np.linalg.norm(n2)
    if n1n < 1e-10 or n2n < 1e-10:
        return float("nan")
    n1 /= n1n
    n2 /= n2n
    m1 = np.cross(n1, b2 / np.linalg.norm(b2))
    return math.degrees(math.atan2(np.dot(m1, n2), np.dot(n1, n2)))


def measure_chi_from_templates(
    sugar: list[tuple],
    base: list[tuple],
    is_purine: bool,
) -> float:
    """Measure chi from template coordinates using SUGAR + BASE."""
    s = {name: np.array([n, y, z]) for name, _, n, y, z in sugar}
    b = {name: np.array([n, y, z]) for name, _, n, y, z in base}
    o4p = s.get("O4'")
    c1p = s.get("C1'")
    if is_purine:
        n_atom = b.get("N9")
        c_atom = b.get("C4")
    else:
        n_atom = b.get("N1")
        c_atom = b.get("C2")
    if any(x is None for x in [o4p, c1p, n_atom, c_atom]):
        return float("nan")
    return dihedral(o4p, c1p, n_atom, c_atom)


# ── Printer ───────────────────────────────────────────────────────────────────

def print_sugar(atoms: list[tuple]) -> None:
    print("\n_SUGAR: tuple[_AtomDef, ...] = (")
    print("    # Extracted from 1ZEW chain A residue 5 (DT) in the production")
    print("    # radial frame: e_n = -e_radial, e_z = -axis_tangent (FWD), e_y = cross(e_z, e_n).")
    print("    # Pre-rotated by +37.05° to compensate for _FRAME_ROT_RAD (−37.05°) in _atom_frame().")
    print("    # C1′ z = 0 (base coplanarity shift applied).")
    for name, elem, n, y, z in atoms:
        print(f'    ("{name:<4}", "{elem}", {n:8.4f}, {y:8.4f}, {z:8.4f}),')
    print(")")


def print_base_template(restype: str, atoms: list[tuple], is_rev: bool,
                        fwd_resids: dict | None, rev_resids: dict | None) -> None:
    if is_rev:
        var = f"_{restype}_BASE_REV"
        src = f"1ZEW chain B inner residues {sorted(rev_resids.keys())}"
        frame = "REVERSE strand frame: e_z = +axis_tangent"
    else:
        var = f"_{restype}_BASE"
        src = f"1ZEW chain A inner residues {sorted(fwd_resids.keys())}"
        frame = "FORWARD strand frame: e_z = -axis_tangent"
    print(f"\n{var}: tuple[_AtomDef, ...] = (")
    print(f"    # Extracted from {src}.")
    print(f"    # {frame}, e_n = -e_radial (production radial frame).")
    for name, elem, n, y, z in atoms:
        print(f'    ("{name}", "{elem}", {n:8.4f}, {y:8.4f}, {z:8.4f}),')
    print(")")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pdb_path = Path(__file__).resolve().parent.parent / "Examples" / "1zew.pdb"
    if not pdb_path.exists():
        print(f"ERROR: {pdb_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {pdb_path} ...")
    records = parse_pdb(str(pdb_path))
    print(f"  Found {len(records)} residues")

    print("\nComputing helix axis ...")
    axis_origin, axis_tangent = compute_helix_axis(records)
    print(f"  axis_tangent = [{axis_tangent[0]:.4f}, {axis_tangent[1]:.4f}, {axis_tangent[2]:.4f}]")

    # ── SUGAR ────────────────────────────────────────────────────────────────
    print("\nExtracting SUGAR template from chain A residue 5 (DT) ...")
    sugar = extract_sugar(records, axis_origin, axis_tangent, ref_resnum=5)

    # ── FWD BASE ─────────────────────────────────────────────────────────────
    print("\nExtracting FWD BASE templates from chain A inner residues ...")
    fwd_bases = extract_bases(records, _CHAIN_A_INNER, axis_origin, axis_tangent, is_fwd=True)

    # ── REV BASE ─────────────────────────────────────────────────────────────
    print("\nExtracting REV BASE templates from chain B inner residues ...")
    rev_bases = extract_bases(records, _CHAIN_B_INNER, axis_origin, axis_tangent, is_fwd=False)

    # ── Chi check ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CHI ANGLES (template-derived vs 1ZEW target)")
    print("=" * 60)
    chi_targets = {"DT": 107.2, "DC": 108.7, "DA": 94.7, "DG": 102.0}
    for restype in ["DT", "DC", "DA", "DG"]:
        is_purine = restype in ("DA", "DG")
        if restype in fwd_bases:
            chi_fwd = measure_chi_from_templates(sugar, fwd_bases[restype], is_purine)
            tgt = chi_targets[restype]
            print(f"  FWD {restype}: chi = {chi_fwd:7.2f}°  (target {tgt:.1f}°, "
                  f"err = {chi_fwd - tgt:+.2f}°)")
        if restype in rev_bases:
            chi_rev = measure_chi_from_templates(sugar, rev_bases[restype], is_purine)
            tgt = chi_targets[restype]
            print(f"  REV {restype}: chi = {chi_rev:7.2f}°  (target {tgt:.1f}°, "
                  f"err = {chi_rev - tgt:+.2f}°)")

    # ── H-bond distances (DT-DA pair check) ──────────────────────────────────
    # We can't measure actual world H-bond distances here without a full design,
    # but we can print key atom positions for visual inspection.
    print("\n" + "=" * 60)
    print("KEY ATOM POSITIONS (template space, n/y/z in nm)")
    print("=" * 60)
    hbond_atoms = {
        "DT": ["N3", "O2", "O4"],
        "DC": ["N3", "O2", "N4"],
        "DA": ["N1", "N6"],
        "DG": ["N1", "N2", "O6"],
    }
    for restype in ["DT", "DC", "DA", "DG"]:
        for strand, bases in [("FWD", fwd_bases), ("REV", rev_bases)]:
            if restype not in bases:
                continue
            tmpl = {name: (n, y, z) for name, _, n, y, z in bases[restype]}
            print(f"  {strand} {restype}:")
            for aname in hbond_atoms.get(restype, []):
                if aname in tmpl:
                    n, y, z = tmpl[aname]
                    print(f"    {aname:4s}: ({n:7.4f}, {y:7.4f}, {z:7.4f})")

    # ── Output ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEMPLATE CODE (paste into atomistic.py)")
    print("=" * 60)

    print_sugar(sugar)

    for restype in ["DT", "DC", "DA", "DG"]:
        if restype in fwd_bases:
            print_base_template(restype, fwd_bases[restype], is_rev=False,
                                fwd_resids=_CHAIN_A_INNER, rev_resids=None)

    for restype in ["DT", "DC", "DA", "DG"]:
        if restype in rev_bases:
            print_base_template(restype, rev_bases[restype], is_rev=True,
                                fwd_resids=None, rev_resids=_CHAIN_B_INNER)


if __name__ == "__main__":
    main()
