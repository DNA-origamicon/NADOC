#!/usr/bin/env python3
"""
reextract_nadoc_templates.py — Extract templates using NADOC's ACTUAL frame positions.

MOTIVATION
----------
extract_all_templates.py uses 1ZEW P positions as frame origins (36°/bp twist,
0.332 nm rise from 1ZEW).  NADOC production uses 34.3°/bp and 0.334 nm rise.
This mismatch causes the inter-residue O3'→P(next) vector to land at ~91° instead
of 119.35° for the C3'–O3'–P angle.

The fix: extract templates using the NADOC synthetic frame positions (not raw 1ZEW
P positions).  For each inner 1ZEW residue, we:

  1. Build a synthetic NADOC helix matching 1ZEW's axis and phase, but using
     NADOC's BDNA_TWIST_PER_BP_RAD (34.3°/bp) and BDNA_RISE_PER_BP (0.334 nm).
  2. Call _atom_frame(nuc_pos, direction, axis_origin) to get the production frame.
  3. Express 1ZEW world atom positions in that frame.
  4. Apply C1'→z=0 shift.  Average per residue type.

This guarantees that when NADOC places consecutive residues at (N*34.3°, N*0.334 nm),
the O3'(N) and P(N+1) template coordinates produce the crystallographic inter-residue
geometry.

For REV strand: `_atom_frame` applies the built-in +58.2° P-P correction, so the
REV frame origin is at FWD+208.2° — same canonical geometry as the current templates.

Usage:
    python scripts/reextract_nadoc_templates.py [--measure-o3]
    python scripts/reextract_nadoc_templates.py --measure-o3   # print expected angle
"""

from __future__ import annotations

import math
import sys
import argparse
from pathlib import Path
from collections import defaultdict

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.atomistic import _atom_frame, _ATOMISTIC_P_RADIUS, _FRAME_ROT_RAD, _ATOMISTIC_PP_SEP_RAD
from backend.core.constants import BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD, HELIX_RADIUS
from backend.core.geometry import nucleotide_positions, _frame_from_helix_axis
from backend.core.models import Direction, Helix, Vec3

# ── Residue definitions ───────────────────────────────────────────────────────

_CHAIN_A_INNER = {3: "DT", 4: "DC", 5: "DT", 6: "DA", 7: "DG", 8: "DA"}
_CHAIN_B_INNER = {13: "DT", 14: "DC", 15: "DT", 16: "DA", 17: "DG", 18: "DA"}

# Pairing: A:n ↔ B:(21-n)
# In terms of bp_index (0-based from A:3): bp_index i = A:(i+3), B:(18-i)
# bp 0: A:3 ↔ B:18   (A:3 = DT, B:18 = DA)
# bp 1: A:4 ↔ B:17   (A:4 = DC, B:17 = DG)
# bp 2: A:5 ↔ B:16   (A:5 = DT, B:16 = DA)
# bp 3: A:6 ↔ B:15   (A:6 = DA, B:15 = DT)
# bp 4: A:7 ↔ B:14   (A:7 = DG, B:14 = DC)
# bp 5: A:8 ↔ B:13   (A:8 = DA, B:13 = DT)

_BP_TO_A = {i: i + 3 for i in range(6)}   # bp_index → chain A resnum
_BP_TO_B = {i: 18 - i for i in range(6)}   # bp_index → chain B resnum

_SUGAR_ATOMS = ["P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'",
                "C3'", "O3'", "C2'", "C1'"]
_SUGAR_ELEMS = ["P", "O",   "O",   "O",   "C",   "C",   "O",
                "C",  "O",  "C",   "C"]

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
    records: dict[tuple[str, int], dict[str, np.ndarray]] = defaultdict(dict)
    with open(path) as fh:
        for line in fh:
            if not line.startswith("ATOM"):
                continue
            name  = line[12:16].strip()
            chain = line[21].strip()
            resnum = int(line[22:26].strip())
            x = float(line[30:38]) / 10.0
            y = float(line[38:46]) / 10.0
            z = float(line[46:54]) / 10.0
            records[(chain, resnum)][name] = np.array([x, y, z])
    return dict(records)


# ── Helix axis (same as extract_all_templates.py) ─────────────────────────────

def compute_helix_axis(records: dict) -> tuple[np.ndarray, np.ndarray]:
    """SVD of C1' midpoints; axis_tangent points in direction of increasing A residue."""
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


# ── Build synthetic NADOC helix matched to 1ZEW ───────────────────────────────

def build_synthetic_helix(
    records: dict,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> tuple[Helix, np.ndarray]:
    """
    Build a synthetic Helix object with:
    - axis matching 1ZEW (from compute_helix_axis)
    - phase_offset from A:3's P azimuth (first inner residue = bp_index 0)
    - NADOC twist (34.3°/bp) and rise (0.334 nm/bp)
    - length_bp = 6 (inner residues only)
    - bp_start = 0

    Returns (helix, axis_origin).
    """
    n_bp = 6

    # Axis endpoints: span the 6 inner base pairs
    # The first inner bp (A:3) is at some t along the axis; place bp_start at t_first - 0.5*rise
    t_first = float(np.dot(records[("A", 3)]["P"] - axis_origin, axis_tangent))
    t_last  = float(np.dot(records[("A", 8)]["P"] - axis_origin, axis_tangent))

    ax_start = axis_origin + (t_first - BDNA_RISE_PER_BP * 0.5) * axis_tangent
    ax_end   = axis_origin + (t_last  + BDNA_RISE_PER_BP * 0.5) * axis_tangent

    # Phase: project A:3's P onto the axis frame to get its azimuth
    # Use the same method as calibrate_from_pdb
    frame = _frame_from_helix_axis(axis_tangent)
    bp0_axis_pt = ax_start + BDNA_RISE_PER_BP * axis_tangent  # axis point at bp_index 0
    # Correct bp0_axis_pt: since ax_start is 0.5*rise before bp0, bp0 is at ax_start + 0.5*rise + 0.5*rise
    # Actually: axis_start + bp_index * rise * axis_hat = bp_axis_point
    # bp_index 0 → axis_point = ax_start  (by definition in nucleotide_positions)
    # So: bp0_axis_pt = ax_start
    bp0_axis_pt = ax_start

    p_A3 = records[("A", 3)]["P"]
    radial_A3 = p_A3 - bp0_axis_pt
    radial_A3 -= np.dot(radial_A3, axis_tangent) * axis_tangent  # perp to axis
    radial_A3 /= np.linalg.norm(radial_A3)

    # Phase in the geometry frame: atan2(y-component, x-component)
    pdb_phase = math.atan2(
        float(np.dot(radial_A3, frame[:, 1])),
        float(np.dot(radial_A3, frame[:, 0])),
    )

    helix = Helix(
        id="__reextract__",
        axis_start=Vec3.from_array(ax_start),
        axis_end=Vec3.from_array(ax_end),
        phase_offset=pdb_phase,
        twist_per_bp_rad=BDNA_TWIST_PER_BP_RAD,  # NADOC's 34.3°/bp
        length_bp=n_bp,
        bp_start=0,
        direction=Direction.FORWARD,
    )
    return helix, ax_start


# ── DIAGNOSTIC: measure expected O3' angle ───────────────────────────────────

def measure_expected_o3_angle(
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
    axis_tangent: np.ndarray,
) -> None:
    """
    Reconstruct O3'(N) and P(N+1) world positions using the NEW NADOC frames,
    and report C3'-O3'-P angle for each consecutive inner pair.
    This is what we'll GET after updating templates.
    """
    nuc_list = nucleotide_positions(helix)
    nuc_map: dict[tuple[int, str], object] = {}
    for nuc in nuc_list:
        nuc_map[(nuc.bp_index, nuc.direction.value)] = nuc

    def _atom_frame_fwd(bp_idx: int):
        nuc = nuc_map.get((bp_idx, "FORWARD"))
        if nuc is None:
            return None, None
        return _atom_frame(nuc, Direction.FORWARD, axis_origin,
                           helix_direction=Direction.FORWARD)

    print("\n=== Expected C3'-O3'-P angles with NADOC-frame templates ===")
    print("(These are the angles the new templates should produce in production)")

    for bp_N in range(5):  # pairs bp_N and bp_N+1
        a_resN  = _BP_TO_A[bp_N]
        a_resN1 = _BP_TO_A[bp_N + 1]

        origin_N, R_N = _atom_frame_fwd(bp_N)
        origin_N1, R_N1 = _atom_frame_fwd(bp_N + 1)
        if origin_N is None or origin_N1 is None:
            continue

        atoms_N  = records.get(("A", a_resN),  {})
        atoms_N1 = records.get(("A", a_resN1), {})

        C3_1ZEW = atoms_N.get("C3'")
        O3_1ZEW = atoms_N.get("O3'")
        P_1ZEW  = atoms_N1.get("P")
        if C3_1ZEW is None or O3_1ZEW is None or P_1ZEW is None:
            continue

        # Express in NADOC frame N to get template coords
        C3_tmpl = R_N.T @ (C3_1ZEW - origin_N)
        O3_tmpl = R_N.T @ (O3_1ZEW - origin_N)
        P_tmpl  = R_N1.T @ (P_1ZEW  - origin_N1)

        # Reconstruct from template
        C3_world = origin_N + R_N @ C3_tmpl
        O3_world = origin_N + R_N @ O3_tmpl
        P_world  = origin_N1 + R_N1 @ P_tmpl

        v1 = C3_world - O3_world
        v2 = P_world  - O3_world
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

        # Also check: C3'-O3'-P for the 1ZEW raw positions
        v1r = C3_1ZEW - O3_1ZEW
        v2r = P_1ZEW  - O3_1ZEW
        cos_r = float(np.dot(v1r, v2r) / (np.linalg.norm(v1r) * np.linalg.norm(v2r) + 1e-12))
        angle_raw = math.degrees(math.acos(max(-1.0, min(1.0, cos_r))))

        print(f"  bp {bp_N}→{bp_N+1}  (A:{a_resN}→A:{a_resN1}): "
              f"angle={angle:.2f}°  (1ZEW raw: {angle_raw:.2f}°)")


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_sugar(
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
    ref_bp: int = 2,  # A:5 = bp_index 2 (A:3 is bp_index 0)
) -> list[tuple[str, str, float, float, float]]:
    """
    Extract SUGAR from chain A residue at ref_bp using the NADOC synthetic frame.
    Single-residue (A:5, bp_index 2).
    """
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}

    nuc = nuc_map.get((ref_bp, "FORWARD"))
    if nuc is None:
        raise RuntimeError(f"bp_index {ref_bp} FORWARD not found in synthetic helix")

    a_res = _BP_TO_A[ref_bp]  # A:5 for ref_bp=2
    atoms = records[("A", a_res)]

    origin, R = _atom_frame(nuc, Direction.FORWARD, axis_origin,
                             helix_direction=Direction.FORWARD)

    tmpl: dict[str, np.ndarray] = {}
    for name in _SUGAR_ATOMS:
        w = atoms.get(name)
        if w is None:
            print(f"  WARNING: A:{a_res} missing {name}")
        else:
            tmpl[name] = R.T @ (w - origin)

    c1p_z = float(tmpl["C1'"][2])
    print(f"  Sugar (A:{a_res}, bp_index={ref_bp}): C1' z = {c1p_z:.4f} nm → shifting to 0")

    result = []
    for name, elem in zip(_SUGAR_ATOMS, _SUGAR_ELEMS):
        if name not in tmpl:
            continue
        n, y, z = tmpl[name]
        result.append((name, elem, float(n), float(y), float(z - c1p_z)))
    return result


def extract_bases(
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
) -> dict[str, dict[str, list[tuple[str, str, float, float, float]]]]:
    """
    Extract FWD and REV base templates using NADOC synthetic frames.
    Returns {'FWD': {restype: [atoms]}, 'REV': {restype: [atoms]}}.
    """
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}

    accum_fwd: dict[str, list[dict[str, np.ndarray]]] = defaultdict(list)
    accum_rev: dict[str, list[dict[str, np.ndarray]]] = defaultdict(list)

    for bp_idx in range(6):
        a_res = _BP_TO_A[bp_idx]
        b_res = _BP_TO_B[bp_idx]

        # --- FWD ---
        nuc_fwd = nuc_map.get((bp_idx, "FORWARD"))
        if nuc_fwd is not None:
            atoms_a = records.get(("A", a_res), {})
            restype = _CHAIN_A_INNER.get(a_res)
            if restype and atoms_a:
                origin, R = _atom_frame(nuc_fwd, Direction.FORWARD, axis_origin,
                                         helix_direction=Direction.FORWARD)
                tmpl = {}
                c1p = atoms_a.get("C1'")
                if c1p is None:
                    print(f"  WARNING: A:{a_res} missing C1'")
                    continue
                c1p_local = R.T @ (c1p - origin)
                c1p_n, c1p_y, c1p_z = float(c1p_local[0]), float(c1p_local[1]), float(c1p_local[2])
                # C1'-referenced extraction: re-anchor base atoms relative to SUGAR's C1'.
                # A_corrected_n = C1'_sugar_n + (A_local_n - C1'_local_n), z unchanged.
                # This eliminates the error caused by combining SUGAR C1' (frame 2) with
                # base atoms extracted at different bp_indices (different frame rotations).
                _c1p_ref_n, _c1p_ref_y = 0.2248, 0.4334  # SUGAR C1' template position
                for aname in _BASE_ATOMS[restype]:
                    w = atoms_a.get(aname)
                    if w is not None:
                        v = R.T @ (w - origin)
                        tmpl[aname] = np.array([
                            _c1p_ref_n + (float(v[0]) - c1p_n),
                            _c1p_ref_y + (float(v[1]) - c1p_y),
                            float(v[2]) - c1p_z,
                        ])
                r_actual = float(np.linalg.norm(
                    atoms_a["P"] - (axis_origin + np.dot(atoms_a["P"] - axis_origin, nuc_fwd.axis_tangent) * nuc_fwd.axis_tangent)
                )) if "P" in atoms_a else float("nan")
                print(f"  FWD A:{a_res} {restype} bp{bp_idx}  C1' z_shift={c1p_z:.4f}  P→axis={r_actual:.4f}")
                accum_fwd[restype].append(tmpl)

        # --- REV ---
        nuc_rev = nuc_map.get((bp_idx, "REVERSE"))
        if nuc_rev is not None:
            atoms_b = records.get(("B", b_res), {})
            restype = _CHAIN_B_INNER.get(b_res)
            if restype and atoms_b:
                # _atom_frame for REVERSE applies built-in +58.2° P-P correction
                origin, R = _atom_frame(nuc_rev, Direction.REVERSE, axis_origin,
                                         helix_direction=Direction.FORWARD)
                tmpl = {}
                c1p = atoms_b.get("C1'")
                if c1p is None:
                    print(f"  WARNING: B:{b_res} missing C1'")
                    continue
                c1p_local = R.T @ (c1p - origin)
                c1p_n, c1p_y, c1p_z = float(c1p_local[0]), float(c1p_local[1]), float(c1p_local[2])
                # C1'-referenced extraction: same approach as FWD, using SUGAR C1' as anchor.
                # SUGAR C1' = (0.2248, 0.4334, 0.0) is used for BOTH forward and reverse
                # nucleotides; REV base atoms must be expressed relative to this same anchor.
                _c1p_ref_n, _c1p_ref_y = 0.2248, 0.4334
                for aname in _BASE_ATOMS[restype]:
                    w = atoms_b.get(aname)
                    if w is not None:
                        v = R.T @ (w - origin)
                        tmpl[aname] = np.array([
                            _c1p_ref_n + (float(v[0]) - c1p_n),
                            _c1p_ref_y + (float(v[1]) - c1p_y),
                            float(v[2]) - c1p_z,
                        ])
                r_actual = float(np.linalg.norm(
                    atoms_b["P"] - (axis_origin + np.dot(atoms_b["P"] - axis_origin, nuc_rev.axis_tangent) * nuc_rev.axis_tangent)
                )) if "P" in atoms_b else float("nan")
                print(f"  REV B:{b_res} {restype} bp{bp_idx}  C1' z_shift={c1p_z:.4f}  P→axis={r_actual:.4f}")
                accum_rev[restype].append(tmpl)

    def _average(accum: dict, strand: str) -> dict[str, list[tuple]]:
        result = {}
        for restype, instances in accum.items():
            all_atoms = _BASE_ATOMS[restype]
            elems = _BASE_ELEMS[restype]
            avg: dict[str, np.ndarray] = {}
            for aname in all_atoms:
                clist = [inst[aname] for inst in instances if aname in inst]
                if clist:
                    avg[aname] = np.mean(clist, axis=0)
            result[restype] = []
            for aname, elem in zip(all_atoms, elems):
                if aname not in avg:
                    print(f"  WARNING: {strand} {restype} missing {aname}")
                    continue
                n, y, z = avg[aname]
                result[restype].append((aname, elem, float(n), float(y), float(z)))
        return result

    return {"FWD": _average(accum_fwd, "FWD"), "REV": _average(accum_rev, "REV")}


# ── O3' angle prediction ──────────────────────────────────────────────────────

def predict_o3_angle(
    sugar: list[tuple],
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
) -> None:
    """
    Using the NEW sugar template and NADOC frames, compute the expected
    C3'-O3'-P angle for consecutive residue pairs in the synthetic helix.
    """
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}

    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar}

    # Find C1' z-shift (should be 0 already, but record it)
    c1p_z = float(sugar_dict["C1'"][2])

    print("\n=== Predicted C3'-O3'-P angle with NEW templates ===")
    for bp_N in range(5):
        nuc_N  = nuc_map.get((bp_N,     "FORWARD"))
        nuc_N1 = nuc_map.get((bp_N + 1, "FORWARD"))
        if nuc_N is None or nuc_N1 is None:
            continue

        origin_N,  R_N  = _atom_frame(nuc_N,  Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)
        origin_N1, R_N1 = _atom_frame(nuc_N1, Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)

        C3_world  = origin_N  + R_N  @ sugar_dict["C3'"]
        O3_world  = origin_N  + R_N  @ sugar_dict["O3'"]
        P_world   = origin_N1 + R_N1 @ sugar_dict["P"]

        v1 = C3_world - O3_world
        v2 = P_world  - O3_world
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

        a_N  = _BP_TO_A[bp_N]
        a_N1 = _BP_TO_A[bp_N + 1]
        print(f"  bp {bp_N}→{bp_N+1}  (A:{a_N}→A:{a_N1}): C3'-O3'-P = {angle:.2f}°")


# ── Corrected O3' computation ─────────────────────────────────────────────────

def _find_o3prime_on_circle(
    C3: np.ndarray,
    P_target: np.ndarray,
    O3_crystal: np.ndarray,
    r1: float = 0.152,   # C3'–O3' bond length (nm)
    r2: float = 0.161,   # O3'–P bond length (nm)
) -> np.ndarray:
    """
    Find the O3' position that:
      - lies on the sphere of radius r1 centred on C3'
      - lies on the sphere of radius r2 centred on P_target
      - is closest to O3_crystal (to preserve the ε dihedral)

    All coordinates are in the same local frame.
    Returns the best O3' position in that frame.
    """
    CP = P_target - C3
    d_CP = float(np.linalg.norm(CP))
    if d_CP < 1e-9:
        return O3_crystal.copy()

    # Projection parameter of the circle centre along C→P
    t = (r1**2 - r2**2 + d_CP**2) / (2.0 * d_CP**2)
    circle_centre = C3 + t * CP

    # Radius of the intersection circle
    r_circle_sq = r1**2 - (t * d_CP)**2
    if r_circle_sq < 0:
        # Bond lengths incompatible with C-P distance; clamp gracefully
        print(f"  WARNING: no O3' circle (d_CP={d_CP*10:.2f} Å, r1={r1*10:.2f} Å, r2={r2*10:.2f} Å); "
              "returning circle centre")
        return circle_centre

    r_circle = math.sqrt(r_circle_sq)

    # Direction from circle centre toward crystal O3' (projected perpendicular to C-P axis)
    CP_hat = CP / d_CP
    d = O3_crystal - circle_centre
    d_perp = d - np.dot(d, CP_hat) * CP_hat
    norm_perp = float(np.linalg.norm(d_perp))

    if norm_perp < 1e-10:
        # Crystal O3' is exactly on the axis; choose any perpendicular
        arbitrary = np.array([1., 0., 0.]) if abs(CP_hat[0]) < 0.9 else np.array([0., 1., 0.])
        u = arbitrary - np.dot(arbitrary, CP_hat) * CP_hat
        u /= np.linalg.norm(u)
    else:
        u = d_perp / norm_perp

    return circle_centre + r_circle * u


def compute_corrected_p_and_o3prime(
    sugar: list[tuple],
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
    target_angle_deg: float = 119.35,
    r_C3_O3: float = 0.152,   # C3'–O3' bond length nm
    r_O3_P:  float = 0.161,   # O3'–P bond length nm
) -> list[tuple]:
    """
    Fix the inter-residue C3'(N)–O3'(N)–P(N+1) geometry.

    ROOT CAUSE: In the single-template model P(N+1) is placed at
        origin_{N+1} + R_{N+1} @ P_tmpl
    The frame-to-frame transform puts this P only ~2.05 Å from C3'(N),
    but the target C3'–P distance for a 119.35° angle at canonical bond
    lengths is ~2.70 Å.  Repositioning O3' alone can't span this gap.

    FIX: Compute the minimal shift to P_tmpl so that T(P_tmpl_new) lands
    exactly 2.70 Å from C3'(N) — in the same direction as the current
    P(N+1), preserving the n/y/z ratios.  Then re-derive O3' on the
    intersection circle, biased toward the crystal O3' orientation.

    Let T be the frame-to-frame transform in local frame_N coordinates:
        T(v) = ΔO + M @ v
    where ΔO = R_N^T @ (origin_{N+1} − origin_N)  and  M = R_N^T @ R_{N+1}.

    Then:
        P_tmpl_new = P_tmpl + t · M^T @ dir
    where dir = (T(P_tmpl) − C3'_tmpl).normalized()
    and   t   = d_target − d_current

    This shifts P by exactly t in the C3'→P direction, moving it onto
    the correct inter-residue sphere with a single scalar t.

    Returns updated SUGAR atom list (P and O3' changed; all others unchanged).
    """
    # Canonical C3'–P distance for target angle
    theta = math.radians(target_angle_deg)
    d_C3_P_target = math.sqrt(
        r_C3_O3**2 + r_O3_P**2 - 2.0 * r_C3_O3 * r_O3_P * math.cos(theta)
    )

    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}

    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar}
    P_tmpl  = sugar_dict["P"].copy()
    C3_tmpl = sugar_dict["C3'"]
    O3_tmpl = sugar_dict["O3'"]

    # Accumulate per-pair corrections
    p_shifts:  list[np.ndarray] = []
    o3_results: list[np.ndarray] = []

    print(f"\n=== Correcting P and O3' for inter-residue geometry ===")
    print(f"  Target angle = {target_angle_deg}°,  "
          f"d(C3'–P) target = {d_C3_P_target*10:.3f} Å")

    for bp_N in range(5):
        nuc_N  = nuc_map.get((bp_N,     "FORWARD"))
        nuc_N1 = nuc_map.get((bp_N + 1, "FORWARD"))
        if nuc_N is None or nuc_N1 is None:
            continue

        origin_N,  R_N  = _atom_frame(nuc_N,  Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)
        origin_N1, R_N1 = _atom_frame(nuc_N1, Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)

        # Frame-to-frame transform components (in local frame_N coords)
        delta_O = R_N.T @ (origin_N1 - origin_N)   # ΔO
        M       = R_N.T @ R_N1                       # rotation component

        # Current P(N+1) in frame_N local coords
        P_in_N = delta_O + M @ P_tmpl
        d_current = float(np.linalg.norm(P_in_N - C3_tmpl))

        # Direction (C3' → P_in_N) in frame_N coords
        if d_current < 1e-9:
            print(f"  bp {bp_N}: degenerate — skipping")
            continue
        dir_hat = (P_in_N - C3_tmpl) / d_current

        # Required shift t in the dir_hat direction (in nm)
        t = d_C3_P_target - d_current

        # New P(N+1) in frame_N coords (farther along dir_hat)
        P_in_N_new = P_in_N + t * dir_hat

        # Corresponding P_tmpl shift: δP_tmpl = M^T @ (t * dir_hat)
        dP_tmpl = M.T @ (t * dir_hat)
        p_shifts.append(dP_tmpl)

        # New P_tmpl (for this pair)
        P_tmpl_new = P_tmpl + dP_tmpl
        d_new = float(np.linalg.norm(P_in_N_new - C3_tmpl))

        # Crystal O3' in frame_N local coords
        a_resN = _BP_TO_A[bp_N]
        O3_crystal_world = records.get(("A", a_resN), {}).get("O3'")
        O3_crystal_local = (R_N.T @ (O3_crystal_world - origin_N)
                            if O3_crystal_world is not None else O3_tmpl)

        # Find O3' on the intersection circle
        O3_new = _find_o3prime_on_circle(C3_tmpl, P_in_N_new, O3_crystal_local,
                                          r1=r_C3_O3, r2=r_O3_P)
        o3_results.append(O3_new)

        # Verify achieved angle
        v1 = C3_tmpl - O3_new
        v2 = P_in_N_new - O3_new
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

        print(f"  bp {bp_N}→{bp_N+1}: d_C3P {d_current*10:.2f}→{d_new*10:.2f}Å  "
              f"t={t*10:.3f}Å  angle={angle:.2f}°")

    if not p_shifts:
        print("  ERROR: no pairs computed")
        return sugar

    dP_mean  = np.mean(p_shifts,  axis=0)
    O3_mean  = np.mean(o3_results, axis=0)
    dP_std   = np.std(p_shifts, axis=0)
    O3_std   = np.std(o3_results, axis=0)

    P_tmpl_new = P_tmpl + dP_mean

    print(f"\n  ΔP_tmpl mean = ({dP_mean[0]:.4f}, {dP_mean[1]:.4f}, {dP_mean[2]:.4f})")
    print(f"  ΔP_tmpl std  = ({dP_std[0]:.5f}, {dP_std[1]:.5f}, {dP_std[2]:.5f})")
    print(f"  P_tmpl new   = ({P_tmpl_new[0]:.4f}, {P_tmpl_new[1]:.4f}, {P_tmpl_new[2]:.4f})")
    print(f"  P_tmpl old   = ({P_tmpl[0]:.4f}, {P_tmpl[1]:.4f}, {P_tmpl[2]:.4f})")
    print(f"  O3'_tmpl new = ({O3_mean[0]:.4f}, {O3_mean[1]:.4f}, {O3_mean[2]:.4f})")
    print(f"  O3'_tmpl old = ({O3_tmpl[0]:.4f}, {O3_tmpl[1]:.4f}, {O3_tmpl[2]:.4f})")
    print(f"  O3'_tmpl std = ({O3_std[0]:.5f}, {O3_std[1]:.5f}, {O3_std[2]:.5f})")

    # Build updated SUGAR list
    updated = []
    for name, elem, n, y, z in sugar:
        if name == "P":
            updated.append((name, elem, float(P_tmpl_new[0]),
                             float(P_tmpl_new[1]), float(P_tmpl_new[2])))
        elif name == "O3'":
            updated.append((name, elem, float(O3_mean[0]),
                             float(O3_mean[1]), float(O3_mean[2])))
        else:
            updated.append((name, elem, n, y, z))
    return updated


def compute_corrected_o3prime(
    sugar: list[tuple],
    records: dict,
    helix: Helix,
    axis_origin: np.ndarray,
) -> list[tuple]:
    """
    [DEPRECATED — kept for reference]
    Fix O3' only (without adjusting P).  Max achievable angle ~82° because
    C3'→P(N+1) is only 2.05 Å.  Use compute_corrected_p_and_o3prime instead.
    """
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}

    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar}
    P_tmpl  = sugar_dict["P"]
    C3_tmpl = sugar_dict["C3'"]
    O3_tmpl = sugar_dict["O3'"]

    o3_candidates: list[np.ndarray] = []

    print("\n=== [deprecated] O3'-only correction (max ~82°) ===")
    for bp_N in range(5):
        nuc_N  = nuc_map.get((bp_N,     "FORWARD"))
        nuc_N1 = nuc_map.get((bp_N + 1, "FORWARD"))
        if nuc_N is None or nuc_N1 is None:
            continue
        origin_N,  R_N  = _atom_frame(nuc_N,  Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)
        origin_N1, R_N1 = _atom_frame(nuc_N1, Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)
        P_world_N1   = origin_N1 + R_N1 @ P_tmpl
        P_local_in_N = R_N.T @ (P_world_N1 - origin_N)
        d_C3_P = float(np.linalg.norm(P_local_in_N - C3_tmpl))
        a_resN = _BP_TO_A[bp_N]
        O3_crystal_world = records.get(("A", a_resN), {}).get("O3'")
        O3_crystal_local = (R_N.T @ (O3_crystal_world - origin_N)
                            if O3_crystal_world is not None else O3_tmpl)
        o3_new = _find_o3prime_on_circle(C3_tmpl, P_local_in_N, O3_crystal_local)
        o3_candidates.append(o3_new)
        v1 = C3_tmpl - o3_new
        v2 = P_local_in_N - o3_new
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
        print(f"  bp {bp_N}→{bp_N+1}: d_C3P={d_C3_P*10:.2f}Å  angle={angle:.2f}°")

    o3_mean = np.mean(o3_candidates, axis=0)
    updated = []
    for name, elem, n, y, z in sugar:
        if name == "O3'":
            updated.append((name, elem, float(o3_mean[0]), float(o3_mean[1]), float(o3_mean[2])))
        else:
            updated.append((name, elem, n, y, z))
    return updated


def verify_corrected_o3prime(
    sugar_corrected: list[tuple],
    helix: Helix,
    axis_origin: np.ndarray,
) -> None:
    """Verify that the corrected SUGAR template gives ~119° C3'-O3'-P angles."""
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}
    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar_corrected}

    print("\n=== Verification: C3'-O3'-P with CORRECTED O3' template ===")
    for bp_N in range(5):
        nuc_N  = nuc_map.get((bp_N,     "FORWARD"))
        nuc_N1 = nuc_map.get((bp_N + 1, "FORWARD"))
        if nuc_N is None or nuc_N1 is None:
            continue
        origin_N,  R_N  = _atom_frame(nuc_N,  Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)
        origin_N1, R_N1 = _atom_frame(nuc_N1, Direction.FORWARD, axis_origin,
                                       helix_direction=Direction.FORWARD)

        C3_world = origin_N  + R_N  @ sugar_dict["C3'"]
        O3_world = origin_N  + R_N  @ sugar_dict["O3'"]
        P_world  = origin_N1 + R_N1 @ sugar_dict["P"]

        v1 = C3_world - O3_world
        v2 = P_world  - O3_world
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
        print(f"  bp {bp_N}→{bp_N+1}: C3'-O3'-P = {angle:.2f}°  "
              f"(target 119.35°, error {angle - 119.35:+.2f}°)")


# ── OP1/OP2 correction ───────────────────────────────────────────────────────

def compute_corrected_op1_op2(
    sugar_original: list[tuple],
    sugar_corrected: list[tuple],
) -> list[tuple]:
    """
    Fix OP1/OP2 positions after the inter-residue P shift (Entry 2 fix).

    Root cause: In Entry 2, P_tmpl was shifted by ΔP ≈ (−0.062, +0.017, −0.012) nm
    to fix the C3'–O3'–P angle, but OP1/OP2 were NOT moved with it. This left
    OP1/OP2 referencing the OLD P position, causing:
        P→OP1 = 1.13 Å (target 1.48 Å)  P→OP2 = 1.85 Å (target 1.48 Å)
        O5'–P–OP1 = 142°  O5'–P–OP2 = 101°

    Fix: shift OP1/OP2 by the same ΔP applied to P. This preserves the intra-
    residue crystal geometry from 1ZEW A:5 (all P-OP bond vectors are maintained)
    while restoring correct bond lengths relative to the new P position.

    Note: the O5'–P–O3'_prev angle in the NADOC single-template model is only ~70°
    (instead of ~104° in real B-DNA) because P was moved outward to extend the
    C3'–P inter-residue distance. The tetrahedral constraint u_O5'+u_O3prev+u_OP1+
    u_OP2=0 cannot produce ideal angles from a 70° base, so the ΔP-shift approach
    (preserving crystal geometry) gives the best one-pass approximation.

    Returns updated sugar_corrected with new OP1/OP2 positions.
    """
    orig = {name: np.array([n, y, z]) for name, _, n, y, z in sugar_original}
    corr = {name: np.array([n, y, z]) for name, _, n, y, z in sugar_corrected}

    dP = corr["P"] - orig["P"]

    OP1_old = corr["OP1"]   # pre-fix: still references old P
    OP2_old = corr["OP2"]
    OP1_new = orig["OP1"] + dP   # crystal geometry + ΔP
    OP2_new = orig["OP2"] + dP

    def _angle(a: np.ndarray, vertex: np.ndarray, c: np.ndarray) -> float:
        v1 = a - vertex; v2 = c - vertex
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        return math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

    P   = corr["P"]
    O5p = corr["O5'"]
    print(f"\n=== OP1/OP2 correction (ΔP shift) ===")
    print(f"  ΔP = ({dP[0]:.4f}, {dP[1]:.4f}, {dP[2]:.4f}) nm  |ΔP| = {np.linalg.norm(dP)*10:.3f} Å")
    print(f"\n  OLD  P→OP1 = {np.linalg.norm(OP1_old - P)*10:.3f} Å  pos=({OP1_old[0]:.4f},{OP1_old[1]:.4f},{OP1_old[2]:.4f})")
    print(f"  NEW  P→OP1 = {np.linalg.norm(OP1_new - P)*10:.3f} Å  pos=({OP1_new[0]:.4f},{OP1_new[1]:.4f},{OP1_new[2]:.4f})")
    print(f"  OLD  P→OP2 = {np.linalg.norm(OP2_old - P)*10:.3f} Å  pos=({OP2_old[0]:.4f},{OP2_old[1]:.4f},{OP2_old[2]:.4f})")
    print(f"  NEW  P→OP2 = {np.linalg.norm(OP2_new - P)*10:.3f} Å  pos=({OP2_new[0]:.4f},{OP2_new[1]:.4f},{OP2_new[2]:.4f})")
    print(f"\n  O5'–P–OP1  = {_angle(O5p, P, OP1_new):.1f}°")
    print(f"  O5'–P–OP2  = {_angle(O5p, P, OP2_new):.1f}°")
    print(f"  OP1–P–OP2  = {_angle(OP1_new, P, OP2_new):.1f}°  (target ~120° for non-bridging pair)")
    print(f"  P→O5' = {np.linalg.norm(O5p - P)*10:.3f} Å")

    updated = []
    for name, elem, n, y, z in sugar_corrected:
        if name == "OP1":
            updated.append((name, elem, float(OP1_new[0]), float(OP1_new[1]), float(OP1_new[2])))
        elif name == "OP2":
            updated.append((name, elem, float(OP2_new[0]), float(OP2_new[1]), float(OP2_new[2])))
        else:
            updated.append((name, elem, n, y, z))
    return updated


# ── C1'–N geometry verification ───────────────────────────────────────────────

def _angle_deg(a: np.ndarray, vertex: np.ndarray, c: np.ndarray) -> float:
    v1 = a - vertex; v2 = c - vertex
    cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))


def verify_c1n_geometry(
    sugar: list[tuple],
    bases: dict[str, dict[str, list[tuple]]],
) -> None:
    """
    For each residue type (FWD and REV), report:
      - C1'–N1/N9 bond distance
      - C1'–N1–C2, C1'–N1–C6 for pyrimidines (target ~117°, ~120°)
      - C1'–N9–C4, C1'–N9–C8 for purines (target ~126°, ~125°)
    """
    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar}
    C1p = sugar_dict["C1'"]  # reference C1' = (0.2248, 0.4334, 0.0)

    print("\n=== C1'–N glycosidic bond geometry ===")
    print(f"  Reference C1' = ({C1p[0]:.4f}, {C1p[1]:.4f}, {C1p[2]:.4f})\n")

    _glyco_n = {"DT": "N1", "DC": "N1", "DA": "N9", "DG": "N9"}
    _adj1    = {"DT": "C2", "DC": "C2", "DA": "C4", "DG": "C4"}  # adjacent on one side
    _adj2    = {"DT": "C6", "DC": "C6", "DA": "C8", "DG": "C8"}  # adjacent on other side
    _target_dist = 0.147  # nm

    for strand in ("FWD", "REV"):
        strand_bases = bases.get(strand, {})
        for restype in ("DT", "DC", "DA", "DG"):
            atoms_list = strand_bases.get(restype, [])
            if not atoms_list:
                continue
            adict = {name: np.array([n, y, z]) for name, _, n, y, z in atoms_list}
            gn   = _glyco_n[restype]
            adj1 = _adj1[restype]
            adj2 = _adj2[restype]
            if gn not in adict:
                print(f"  {strand} {restype}: missing {gn}")
                continue
            N    = adict[gn]
            dist = float(np.linalg.norm(N - C1p))
            err  = (dist - _target_dist) * 10  # Å
            a1   = _angle_deg(C1p, N, adict[adj1]) if adj1 in adict else float("nan")
            a2   = _angle_deg(C1p, N, adict[adj2]) if adj2 in adict else float("nan")
            print(f"  {strand} {restype:2s}  C1'–{gn} = {dist*10:.3f} Å (target {_target_dist*10:.1f} Å, err {err:+.3f} Å)")
            print(f"         C1'–{gn}–{adj1} = {a1:.1f}°   C1'–{gn}–{adj2} = {a2:.1f}°")


# ── Printers ──────────────────────────────────────────────────────────────────

def print_sugar(atoms: list[tuple]) -> None:
    print("\n_SUGAR: tuple[_AtomDef, ...] = (")
    print("    # Extracted from 1ZEW chain A residue 5 (DT) using NADOC synthetic frame.")
    print("    # Frame: NADOC _atom_frame(direction=FORWARD) at 34.3°/bp, 0.334 nm/bp.")
    print("    # C1' z = 0 convention applied.")
    for name, elem, n, y, z in atoms:
        print(f'    ("{name:<4}", "{elem}", {n:8.4f}, {y:8.4f}, {z:8.4f}),')
    print(")")


def print_base(var: str, atoms: list[tuple], comment: str) -> None:
    print(f"\n{var}: tuple[_AtomDef, ...] = (")
    print(f"    # {comment}")
    for name, elem, n, y, z in atoms:
        print(f'    ("{name}", "{elem}", {n:8.4f}, {y:8.4f}, {z:8.4f}),')
    print(")")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure-o3", action="store_true",
                    help="Only print expected O3' angles, don't output templates")
    ap.add_argument("--pdb", default=None,
                    help="Path to 1ZEW PDB (default: Examples/1zew.pdb)")
    args = ap.parse_args()

    pdb_path = Path(args.pdb) if args.pdb else \
        Path(__file__).resolve().parent.parent / "Examples" / "1zew.pdb"
    if not pdb_path.exists():
        print(f"ERROR: {pdb_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {pdb_path} ...")
    records = parse_pdb(str(pdb_path))

    print("\nComputing helix axis ...")
    axis_origin, axis_tangent = compute_helix_axis(records)
    print(f"  axis_tangent = [{axis_tangent[0]:.4f}, {axis_tangent[1]:.4f}, {axis_tangent[2]:.4f}]")

    print("\nBuilding synthetic NADOC helix (34.3°/bp, 0.334 nm/bp) matched to 1ZEW axis ...")
    helix, ax_start = build_synthetic_helix(records, axis_origin, axis_tangent)

    # Verify: print NADOC frame origins vs 1ZEW P positions
    print("\n  Residue | NADOC origin (nm) | 1ZEW P (nm)  | Δ (nm)")
    nuc_list = nucleotide_positions(helix)
    nuc_map = {(n.bp_index, n.direction.value): n for n in nuc_list}
    for bp_idx in range(6):
        nuc = nuc_map.get((bp_idx, "FORWARD"))
        a_res = _BP_TO_A[bp_idx]
        if nuc is None or a_res not in _CHAIN_A_INNER:
            continue
        origin, _ = _atom_frame(nuc, Direction.FORWARD, axis_origin,
                                  helix_direction=Direction.FORWARD)
        p_pdb = records[("A", a_res)].get("P")
        if p_pdb is not None:
            delta = np.linalg.norm(origin - p_pdb)
            print(f"  A:{a_res} bp{bp_idx}  "
                  f"origin=({origin[0]:.3f},{origin[1]:.3f},{origin[2]:.3f})  "
                  f"P_pdb=({p_pdb[0]:.3f},{p_pdb[1]:.3f},{p_pdb[2]:.3f})  "
                  f"Δ={delta*10:.2f} Å")

    if args.measure_o3:
        measure_expected_o3_angle(records, helix, axis_origin, axis_tangent)
        return

    # Extract SUGAR (from 1ZEW A:5 in NADOC frame)
    print(f"\nExtracting SUGAR (A:5, bp_index=2) using NADOC frame ...")
    sugar = extract_sugar(records, helix, axis_origin, ref_bp=2)

    # Show predicted O3' angle BEFORE correction (should be ~91° still)
    predict_o3_angle(sugar, records, helix, axis_origin)

    # Compute corrected P + O3' positions for correct inter-residue geometry
    sugar_corrected = compute_corrected_p_and_o3prime(sugar, records, helix, axis_origin)

    # Verify the corrected O3' angle
    verify_corrected_o3prime(sugar_corrected, helix, axis_origin)

    # Fix OP1/OP2: shift by ΔP to restore crystal geometry relative to corrected P
    print(f"\nFixing OP1/OP2 (ΔP shift to match corrected P position) ...")
    sugar_final = compute_corrected_op1_op2(sugar, sugar_corrected)

    # Extract base templates with C1'-referenced correction
    print(f"\nExtracting BASE templates (C1'-referenced) using NADOC frames ...")
    bases = extract_bases(records, helix, axis_origin)

    # Verify C1'–N geometry after C1'-referenced extraction
    verify_c1n_geometry(sugar_final, bases)

    # ── Output ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEMPLATE CODE — copy into atomistic.py")
    print("=" * 60)

    print_sugar(sugar_final)

    restype_order = ["DT", "DC", "DA", "DG"]
    for restype in restype_order:
        if restype in bases["FWD"]:
            contribs = [str(a) for bp, a in _BP_TO_A.items()
                        if _CHAIN_A_INNER.get(a) == restype]
            comment = (f"C1'-referenced. 1ZEW chain A residue(s) {'/'.join(contribs)}, "
                       f"NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).")
            print_base(f"_{restype}_BASE", bases["FWD"][restype], comment)

    for restype in restype_order:
        if restype in bases["REV"]:
            contribs = [str(b) for bp, b in _BP_TO_B.items()
                        if _CHAIN_B_INNER.get(b) == restype]
            comment = (f"C1'-referenced. 1ZEW chain B residue(s) {'/'.join(contribs)}, "
                       f"NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).")
            print_base(f"_{restype}_BASE_REV", bases["REV"][restype], comment)

    # Summary of key atom positions
    print("\n" + "=" * 60)
    print("KEY ATOMS (verification)")
    print("=" * 60)
    sugar_dict = {name: np.array([n, y, z]) for name, _, n, y, z in sugar_final}
    p   = sugar_dict["P"]
    o3  = sugar_dict["O3'"]
    c1p = sugar_dict["C1'"]
    op1 = sugar_dict["OP1"]
    op2 = sugar_dict["OP2"]
    print(f"SUGAR P:   ({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})")
    print(f"SUGAR O3': ({o3[0]:.4f}, {o3[1]:.4f}, {o3[2]:.4f})")
    print(f"SUGAR C1': ({c1p[0]:.4f}, {c1p[1]:.4f}, {c1p[2]:.4f})")
    print(f"SUGAR OP1: ({op1[0]:.4f}, {op1[1]:.4f}, {op1[2]:.4f})")
    print(f"SUGAR OP2: ({op2[0]:.4f}, {op2[1]:.4f}, {op2[2]:.4f})")


if __name__ == "__main__":
    main()
