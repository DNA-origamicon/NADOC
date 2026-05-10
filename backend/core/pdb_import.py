"""
PDB import and B-DNA geometry analysis module.

Parses PDB files containing B-form DNA duplexes and extracts:
- Per-nucleotide local reference frames (NADOC convention)
- Averaged atom templates for sugar backbone and each base type
- Diagnostic measurements: rise, twist, chi angle, sugar pucker,
  Watson-Crick pair geometry, ribose-to-base orientation

All coordinates are in nm internally (PDB Angstroms ÷ 10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# ── PDB parser ───────────────────────────────────────────────────────────────


@dataclass
class PDBAtom:
    serial: int
    name: str
    resName: str
    chainID: str
    resSeq: int
    x: float  # nm
    y: float  # nm
    z: float  # nm
    element: str

    @property
    def pos(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


def parse_pdb(path: str | Path) -> list[PDBAtom]:
    """Parse ATOM records from a PDB file.  Coordinates converted to nm."""
    atoms: list[PDBAtom] = []
    with open(path) as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            atoms.append(PDBAtom(
                serial=int(line[6:11]),
                name=line[12:16].strip(),
                resName=line[17:20].strip(),
                chainID=line[21],
                resSeq=int(line[22:26]),
                x=float(line[30:38]) / 10.0,
                y=float(line[38:46]) / 10.0,
                z=float(line[46:54]) / 10.0,
                element=line[76:78].strip(),
            ))
    return atoms


# ── Residue grouping ─────────────────────────────────────────────────────────


@dataclass
class Residue:
    chainID: str
    resSeq: int
    resName: str
    atoms: dict[str, PDBAtom] = field(default_factory=dict)

    def pos(self, atom_name: str) -> np.ndarray:
        return self.atoms[atom_name].pos

    def has(self, atom_name: str) -> bool:
        return atom_name in self.atoms


def group_residues(atoms: list[PDBAtom]) -> dict[tuple[str, int], Residue]:
    """Group atoms by (chainID, resSeq) into Residue objects."""
    residues: dict[tuple[str, int], Residue] = {}
    for a in atoms:
        key = (a.chainID, a.resSeq)
        if key not in residues:
            residues[key] = Residue(chainID=a.chainID, resSeq=a.resSeq, resName=a.resName)
        residues[key].atoms[a.name] = a
    return residues


# ── Vector helpers ────────────────────────────────────────────────────────────


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _dihedral(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray) -> float:
    """Compute dihedral angle p1-p2-p3-p4 in radians (-pi, pi]."""
    b1 = p2 - p1
    b2 = p3 - p2
    b3 = p4 - p3
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    n1_norm = np.linalg.norm(n1)
    n2_norm = np.linalg.norm(n2)
    if n1_norm < 1e-12 or n2_norm < 1e-12:
        return 0.0
    n1 /= n1_norm
    n2 /= n2_norm
    m1 = np.cross(n1, _norm(b2))
    x = float(np.dot(n1, n2))
    y = float(np.dot(m1, n2))
    return math.atan2(y, x)


def _plane_normal(points: np.ndarray) -> np.ndarray:
    """Best-fit plane normal for Nx3 points via SVD."""
    centroid = points.mean(axis=0)
    _, _, vh = np.linalg.svd(points - centroid)
    return _norm(vh[2])  # smallest singular value → normal


# ── Helix axis fitting ────────────────────────────────────────────────────────


def fit_helix_axis(midpoints: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a line through Nx3 midpoints via SVD.
    Returns (centroid, axis_direction) where axis_direction is a unit vector.
    """
    centroid = midpoints.mean(axis=0)
    _, _, vh = np.linalg.svd(midpoints - centroid)
    return centroid, _norm(vh[0])


# ── Per-nucleotide frame computation ──────────────────────────────────────────


def compute_nucleotide_frame(
    residue: Residue,
    partner: Residue,
    e_z: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the NADOC local frame for a nucleotide.

    Returns (origin, R_raw) where:
      origin = P atom position (nm)
      R_raw  = 3×3 matrix with columns [e_n, e_y, e_z]

    e_n: base normal (toward partner C1')
    e_z: 3'→5' direction (supplied by caller — typically global helix axis with
         appropriate sign for the strand direction)
    e_y: cross(e_z, e_n), orthogonalised
    """
    origin = residue.pos("P")

    # e_n: toward partner strand
    self_c1 = residue.pos("C1'")
    partner_c1 = partner.pos("C1'")
    e_n = _norm(partner_c1 - self_c1)

    # e_y = cross(e_z, e_n), then re-orthogonalise
    e_y = np.cross(e_z, e_n)
    e_y_norm = np.linalg.norm(e_y)
    if e_y_norm < 1e-9:
        raise ValueError(f"Degenerate frame for {residue.chainID}:{residue.resSeq}")
    e_y = e_y / e_y_norm

    # Re-orthogonalise e_n to be exactly perpendicular to e_z
    e_n = np.cross(e_y, e_z)
    e_n = _norm(e_n)

    R_raw = np.column_stack([e_n, e_y, e_z])
    return origin, R_raw


def extract_template_coords(
    residue: Residue,
    origin: np.ndarray,
    R_raw: np.ndarray,
    frame_rot_rad: float,
    atom_names: list[str],
) -> dict[str, np.ndarray]:
    """
    Transform world coordinates to NADOC template coordinates.

    Applies: local = Rz(-frame_rot_rad) @ R_raw^T @ (world - origin)
    This pre-compensates for the rotation applied in _atom_frame().
    """
    c = math.cos(-frame_rot_rad)
    s = math.sin(-frame_rot_rad)
    Rz_neg = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    coords: dict[str, np.ndarray] = {}
    for name in atom_names:
        if not residue.has(name):
            continue
        world = residue.pos(name)
        local_raw = R_raw.T @ (world - origin)
        coords[name] = Rz_neg @ local_raw
    return coords


# ── Sugar pucker analysis ─────────────────────────────────────────────────────


def sugar_pucker_phase(residue: Residue) -> tuple[float, float, str]:
    """
    Compute sugar ring pseudorotation phase angle P and amplitude tau_m.

    Uses the Altona-Sundaralingam formulation with 5 endocyclic torsions
    ν0(C4'-O4'-C1'-C2'), ν1(O4'-C1'-C2'-C3'), ν2(C1'-C2'-C3'-C4'),
    ν3(C2'-C3'-C4'-O4'), ν4(C3'-C4'-O4'-C1').

    Returns (phase_deg, amplitude_deg, pucker_label).
    """
    nu = [
        _dihedral(residue.pos("C4'"), residue.pos("O4'"), residue.pos("C1'"), residue.pos("C2'")),
        _dihedral(residue.pos("O4'"), residue.pos("C1'"), residue.pos("C2'"), residue.pos("C3'")),
        _dihedral(residue.pos("C1'"), residue.pos("C2'"), residue.pos("C3'"), residue.pos("C4'")),
        _dihedral(residue.pos("C2'"), residue.pos("C3'"), residue.pos("C4'"), residue.pos("O4'")),
        _dihedral(residue.pos("C3'"), residue.pos("C4'"), residue.pos("O4'"), residue.pos("C1'")),
    ]

    # Altona-Sundaralingam: tan(P) = ((ν4 + ν1) - (ν3 + ν0)) / (2 ν2 (sin(36°) + sin(72°)))
    sin36 = math.sin(math.radians(36))
    sin72 = math.sin(math.radians(72))
    numerator = (nu[4] + nu[1]) - (nu[3] + nu[0])
    denominator = 2.0 * nu[2] * (sin36 + sin72)

    if abs(denominator) < 1e-12:
        P_rad = 0.0
    else:
        P_rad = math.atan2(numerator, denominator)

    P_deg = math.degrees(P_rad) % 360.0

    # Amplitude
    if abs(math.cos(P_rad)) > 1e-6:
        tau_m = nu[2] / math.cos(P_rad)
    else:
        tau_m = nu[2]  # fallback
    tau_m_deg = math.degrees(abs(tau_m))

    # Classification
    if 0 <= P_deg < 36:
        label = "C3'-endo"
    elif 144 <= P_deg < 180:
        label = "C2'-endo"
    elif 162 <= P_deg < 198:
        label = "C2'-endo"  # wider range for B-DNA
    else:
        # Generic Cremer-Pople sector labels
        sectors = [
            (0, 36, "C3'-endo"), (36, 72, "C4'-exo"), (72, 108, "O4'-endo"),
            (108, 144, "C1'-exo"), (144, 180, "C2'-endo"), (180, 216, "C3'-exo"),
            (216, 252, "C4'-endo"), (252, 288, "O4'-exo"), (288, 324, "C1'-endo"),
            (324, 360, "C2'-exo"),
        ]
        label = "unknown"
        for lo, hi, name in sectors:
            if lo <= P_deg < hi:
                label = name
                break

    return P_deg, tau_m_deg, label


# ── Chi angle ─────────────────────────────────────────────────────────────────


def chi_angle(residue: Residue) -> float:
    """Glycosidic torsion chi in degrees.
    Purines:    O4'-C1'-N9-C4
    Pyrimidines: O4'-C1'-N1-C2
    """
    if residue.resName in ("DA", "DG"):
        angle = _dihedral(
            residue.pos("O4'"), residue.pos("C1'"),
            residue.pos("N9"), residue.pos("C4"),
        )
    else:
        angle = _dihedral(
            residue.pos("O4'"), residue.pos("C1'"),
            residue.pos("N1"), residue.pos("C2"),
        )
    return math.degrees(angle)


# ── Ribose-to-base rotation matrix ───────────────────────────────────────────


def ribose_base_rotation(residue: Residue) -> np.ndarray:
    """
    Compute 3×3 rotation from ribose ring plane to base aromatic plane.

    Ribose ring atoms: C1', C2', C3', C4', O4'
    Base ring atoms depend on residue type:
      Purines (DA, DG): N9, C8, N7, C5, C4
      Pyrimidines (DC, DT): N1, C2, N3, C4, C5, C6
    """
    ribose_atoms = ["C1'", "C2'", "C3'", "C4'", "O4'"]
    ribose_pts = np.array([residue.pos(a) for a in ribose_atoms])
    ribose_normal = _plane_normal(ribose_pts)

    if residue.resName in ("DA", "DG"):
        base_ring_atoms = ["N9", "C8", "N7", "C5", "C4"]
    else:
        base_ring_atoms = ["N1", "C2", "N3", "C4", "C5", "C6"]
    base_pts = np.array([residue.pos(a) for a in base_ring_atoms if residue.has(a)])
    base_normal = _plane_normal(base_pts)

    # Ensure normals point in a consistent direction (toward major groove)
    if np.dot(ribose_normal, base_normal) < 0:
        base_normal = -base_normal

    # Rotation from ribose_normal to base_normal via Rodrigues
    v = np.cross(ribose_normal, base_normal)
    c = float(np.dot(ribose_normal, base_normal))
    s = float(np.linalg.norm(v))

    if s < 1e-12:
        return np.eye(3)

    vx = np.array([
        [0, -v[2], v[1]],
        [v[2], 0, -v[0]],
        [-v[1], v[0], 0],
    ])
    R = np.eye(3) + vx + vx @ vx * (1 - c) / (s * s)
    return R


# ── Watson-Crick pair analysis ────────────────────────────────────────────────


@dataclass
class WCPairGeometry:
    pair_label: str
    c1_c1_distance_nm: float
    hbond_distances_nm: dict[str, float]
    propeller_twist_deg: float


# H-bond atom pairs for each WC pair type
_WC_HBONDS: dict[tuple[str, str], list[tuple[str, str]]] = {
    # (resName_fwd, resName_rev): [(donor_atom_fwd, acceptor_atom_rev), ...]
    ("DA", "DT"): [("N6", "O4"), ("N1", "N3")],
    ("DT", "DA"): [("O4", "N6"), ("N3", "N1")],
    ("DG", "DC"): [("O6", "N4"), ("N1", "N3"), ("N2", "O2")],
    ("DC", "DG"): [("N4", "O6"), ("N3", "N1"), ("O2", "N2")],
}


def analyze_wc_pair(res_fwd: Residue, res_rev: Residue) -> WCPairGeometry:
    """Measure Watson-Crick base pair geometry."""
    c1_dist = float(np.linalg.norm(res_fwd.pos("C1'") - res_rev.pos("C1'")))

    # H-bond distances
    pair_key = (res_fwd.resName, res_rev.resName)
    hbonds: dict[str, float] = {}
    for atom_fwd, atom_rev in _WC_HBONDS.get(pair_key, []):
        if res_fwd.has(atom_fwd) and res_rev.has(atom_rev):
            d = float(np.linalg.norm(res_fwd.pos(atom_fwd) - res_rev.pos(atom_rev)))
            hbonds[f"{atom_fwd}...{atom_rev}"] = d

    # Propeller twist: angle between the two base planes
    if res_fwd.resName in ("DA", "DG"):
        fwd_ring = ["N9", "C8", "N7", "C5", "C4"]
    else:
        fwd_ring = ["N1", "C2", "N3", "C4", "C5", "C6"]
    if res_rev.resName in ("DA", "DG"):
        rev_ring = ["N9", "C8", "N7", "C5", "C4"]
    else:
        rev_ring = ["N1", "C2", "N3", "C4", "C5", "C6"]

    fwd_pts = np.array([res_fwd.pos(a) for a in fwd_ring if res_fwd.has(a)])
    rev_pts = np.array([res_rev.pos(a) for a in rev_ring if res_rev.has(a)])
    fwd_n = _plane_normal(fwd_pts)
    rev_n = _plane_normal(rev_pts)

    cos_angle = float(np.clip(np.dot(fwd_n, rev_n), -1.0, 1.0))
    propeller = math.degrees(math.acos(abs(cos_angle)))

    label = f"{res_fwd.chainID}:{res_fwd.resSeq}({res_fwd.resName})-{res_rev.chainID}:{res_rev.resSeq}({res_rev.resName})"
    return WCPairGeometry(
        pair_label=label,
        c1_c1_distance_nm=c1_dist,
        hbond_distances_nm=hbonds,
        propeller_twist_deg=propeller,
    )


# ── Backbone step analysis ────────────────────────────────────────────────────


@dataclass
class BackboneStep:
    label: str
    rise_nm: float
    twist_deg: float
    slide_nm: float
    shift_nm: float


def analyze_backbone_step(
    res_i: Residue,
    res_j: Residue,
    partner_i: Residue,
    partner_j: Residue,
    axis_dir: np.ndarray,
) -> BackboneStep:
    """Measure base-step parameters between consecutive residues."""
    P_i = res_i.pos("P")
    P_j = res_j.pos("P")
    dp = P_j - P_i

    # Rise: projection along helix axis
    rise = float(np.dot(dp, axis_dir))

    # Twist: angle between base normals around the helix axis
    bn_i = _norm(partner_i.pos("C1'") - res_i.pos("C1'"))
    bn_j = _norm(partner_j.pos("C1'") - res_j.pos("C1'"))

    # Project out axis component
    bn_i_perp = bn_i - np.dot(bn_i, axis_dir) * axis_dir
    bn_j_perp = bn_j - np.dot(bn_j, axis_dir) * axis_dir
    bn_i_perp = _norm(bn_i_perp)
    bn_j_perp = _norm(bn_j_perp)

    cos_twist = float(np.clip(np.dot(bn_i_perp, bn_j_perp), -1.0, 1.0))
    cross_twist = np.cross(bn_i_perp, bn_j_perp)
    sign = 1.0 if np.dot(cross_twist, axis_dir) >= 0 else -1.0
    twist = sign * math.degrees(math.acos(cos_twist))

    # Slide & shift: lateral displacements perpendicular to axis
    dp_perp = dp - np.dot(dp, axis_dir) * axis_dir
    # Slide: along base-normal direction, Shift: perpendicular to both
    slide = float(np.dot(dp_perp, bn_i_perp))
    shift_dir = np.cross(axis_dir, bn_i_perp)
    shift = float(np.dot(dp_perp, shift_dir))

    label = f"{res_i.chainID}:{res_i.resSeq}→{res_j.resSeq}"
    return BackboneStep(label=label, rise_nm=rise, twist_deg=twist,
                        slide_nm=slide, shift_nm=shift)


# ── Bond distance measurement ─────────────────────────────────────────────────

# Standard covalent bonds within a DNA nucleotide
SUGAR_BONDS: list[tuple[str, str]] = [
    ("P", "OP1"), ("P", "OP2"), ("P", "O5'"),
    ("O5'", "C5'"), ("C5'", "C4'"),
    ("C4'", "O4'"), ("C4'", "C3'"),
    ("O4'", "C1'"), ("C3'", "O3'"), ("C3'", "C2'"),
    ("C2'", "C1'"),
]

BASE_BONDS: dict[str, list[tuple[str, str]]] = {
    "DC": [("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
           ("C4", "C5"), ("C5", "C6"), ("C6", "N1"), ("C2", "O2"), ("C4", "N4")],
    "DT": [("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
           ("C4", "C5"), ("C5", "C6"), ("C6", "N1"), ("C2", "O2"), ("C4", "O4"), ("C5", "C7")],
    "DA": [("C1'", "N9"), ("N9", "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),
           ("C4", "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"), ("C6", "N6")],
    "DG": [("C1'", "N9"), ("N9", "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),
           ("C4", "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"), ("C6", "O6"), ("C2", "N2")],
}


def measure_bond_distances(residue: Residue) -> dict[tuple[str, str], float]:
    """Measure all intra-residue covalent bond distances (nm)."""
    bonds: dict[tuple[str, str], float] = {}
    all_bonds = list(SUGAR_BONDS)
    if residue.resName in BASE_BONDS:
        all_bonds.extend(BASE_BONDS[residue.resName])
    for a1, a2 in all_bonds:
        if residue.has(a1) and residue.has(a2):
            d = float(np.linalg.norm(residue.pos(a1) - residue.pos(a2)))
            bonds[(a1, a2)] = d
    return bonds


# ── Full duplex analysis ─────────────────────────────────────────────────────


# Atom names for the sugar-phosphate backbone (shared by all residues)
SUGAR_ATOMS: list[str] = [
    "P", "OP1", "OP2", "O5'", "C5'",
    "C4'", "O4'", "C3'", "O3'", "C2'", "C1'",
]

# Base-specific atom names
BASE_ATOMS: dict[str, list[str]] = {
    "DC": ["N1", "C2", "O2", "N3", "C4", "N4", "C5", "C6"],
    "DT": ["N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"],
    "DA": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6", "N6"],
    "DG": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N2", "N1", "C6", "O6"],
}

# Element lookup
ATOM_ELEMENT: dict[str, str] = {
    "P": "P", "OP1": "O", "OP2": "O", "O5'": "O", "C5'": "C",
    "C4'": "C", "O4'": "O", "C3'": "C", "O3'": "O", "C2'": "C", "C1'": "C",
    "N1": "N", "C2": "C", "O2": "O", "N3": "N", "C4": "C", "N4": "N",
    "C5": "C", "C6": "C", "O4": "O", "C7": "C", "N6": "N",
    "N9": "N", "C8": "C", "N7": "N", "N2": "N", "O6": "O",
}


@dataclass
class DuplexAnalysis:
    """Complete analysis of a B-DNA duplex from a PDB file."""
    # Averaged template coordinates {atom_name: (n, y, z)} in nm
    sugar_template: dict[str, np.ndarray]
    sugar_std: dict[str, np.ndarray]
    base_templates: dict[str, dict[str, np.ndarray]]   # {resName: {atom: coords}}
    base_std: dict[str, dict[str, np.ndarray]]

    # Diagnostics
    backbone_steps: list[BackboneStep]
    wc_pairs: list[WCPairGeometry]
    chi_angles: dict[str, list[float]]          # {chain:resSeq: chi_deg}
    sugar_puckers: dict[str, tuple[float, float, str]]
    ribose_base_rotations: dict[str, np.ndarray]
    bond_distances: dict[str, dict[tuple[str, str], float]]  # {chain:resSeq: {(a1,a2): dist_nm}}

    # Per-instance raw template coords for inspection
    sugar_instances: list[dict[str, np.ndarray]]
    base_instances: dict[str, list[dict[str, np.ndarray]]]


def analyze_duplex(
    pdb_path: str | Path,
    chain_a: str = "A",
    chain_b: str = "B",
    wc_map: Optional[dict[int, int]] = None,
    exclude_terminal: int = 1,
    frame_rot_rad: float = math.radians(39.0),
) -> DuplexAnalysis:
    """
    Full analysis of a B-DNA duplex PDB file.

    Parameters
    ----------
    pdb_path : path to PDB file
    chain_a, chain_b : chain IDs for the two strands
    wc_map : {resSeq_A: resSeq_B} Watson-Crick pairing. If None, auto-detected.
    exclude_terminal : number of terminal residues to exclude from each end
    frame_rot_rad : NADOC frame rotation constant (default 39°)
    """
    atoms = parse_pdb(pdb_path)
    residues = group_residues(atoms)

    # Identify chain residues
    chain_a_seqs = sorted(k[1] for k in residues if k[0] == chain_a)
    chain_b_seqs = sorted(k[1] for k in residues if k[0] == chain_b)

    # Auto-detect WC pairing: antiparallel, A:i pairs with B:(max_B + min_B - i + offset)
    if wc_map is None:
        # Standard antiparallel: A:first ↔ B:last, A:last ↔ B:first
        wc_map = {}
        for idx, a_seq in enumerate(chain_a_seqs):
            b_seq = chain_b_seqs[-(idx + 1)]
            wc_map[a_seq] = b_seq

    # Inner residues (exclude terminals)
    inner_a = chain_a_seqs[exclude_terminal:-exclude_terminal]
    inner_b = chain_b_seqs[exclude_terminal:-exclude_terminal]

    # Fit helix axis from WC pair midpoints
    midpoints = []
    for a_seq in inner_a:
        b_seq = wc_map[a_seq]
        c1_a = residues[(chain_a, a_seq)].pos("C1'")
        c1_b = residues[(chain_b, b_seq)].pos("C1'")
        midpoints.append((c1_a + c1_b) / 2.0)
    midpoints_arr = np.array(midpoints)
    axis_centroid, axis_dir = fit_helix_axis(midpoints_arr)

    # Ensure axis_dir points in the 5'→3' direction of chain A (increasing resSeq)
    p_first = residues[(chain_a, inner_a[0])].pos("P")
    p_last = residues[(chain_a, inner_a[-1])].pos("P")
    if np.dot(p_last - p_first, axis_dir) < 0:
        axis_dir = -axis_dir

    # ── Compute per-nucleotide frames and extract templates ───────────────
    # Use global helix axis for e_z (consistent frame, reduces noise from
    # sequence-dependent bending).  Sign convention:
    #   axis_dir = chain A's 5'→3' direction
    #   Chain A 3'→5' = -axis_dir
    #   Chain B 3'→5' = +axis_dir  (antiparallel)
    e_z_chain_a = -axis_dir  # chain A 3'→5'
    e_z_chain_b = axis_dir   # chain B 3'→5'

    # Build reverse WC lookup for chain B
    wc_map_rev: dict[int, int] = {b: a for a, b in wc_map.items()}

    sugar_instances: list[dict[str, np.ndarray]] = []
    base_instances: dict[str, list[dict[str, np.ndarray]]] = {
        "DA": [], "DT": [], "DG": [], "DC": [],
    }
    chi_angles_map: dict[str, list[float]] = {}
    sugar_puckers_map: dict[str, tuple[float, float, str]] = {}
    ribose_rotations_map: dict[str, np.ndarray] = {}
    bond_dist_map: dict[str, dict[tuple[str, str], float]] = {}

    def _process_residue(chain: str, seq: int) -> None:
        res = residues[(chain, seq)]

        if chain == chain_a:
            partner_seq = wc_map.get(seq)
            partner_chain = chain_b
            e_z = e_z_chain_a
        else:
            partner_seq = wc_map_rev.get(seq)
            partner_chain = chain_a
            e_z = e_z_chain_b

        if partner_seq is None:
            return
        partner = residues[(partner_chain, partner_seq)]

        origin, R_raw = compute_nucleotide_frame(res, partner, e_z)

        # Extract sugar template coords
        sugar_coords = extract_template_coords(res, origin, R_raw, frame_rot_rad, SUGAR_ATOMS)
        if sugar_coords:
            sugar_instances.append(sugar_coords)

        # Extract base template coords
        base_type = res.resName
        if base_type in BASE_ATOMS:
            base_coords = extract_template_coords(res, origin, R_raw, frame_rot_rad, BASE_ATOMS[base_type])
            if base_coords:
                base_instances[base_type].append(base_coords)

        # Diagnostics
        key = f"{chain}:{seq}"
        chi_angles_map[key] = [chi_angle(res)]
        sugar_puckers_map[key] = sugar_pucker_phase(res)
        ribose_rotations_map[key] = ribose_base_rotation(res)
        bond_dist_map[key] = measure_bond_distances(res)

    for seq in inner_a:
        _process_residue(chain_a, seq)
    for seq in inner_b:
        _process_residue(chain_b, seq)

    # ── Average templates ─────────────────────────────────────────────────

    def _average_coords(instances: list[dict[str, np.ndarray]], atom_names: list[str]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        avg: dict[str, np.ndarray] = {}
        std: dict[str, np.ndarray] = {}
        for name in atom_names:
            coords_list = [inst[name] for inst in instances if name in inst]
            if coords_list:
                arr = np.array(coords_list)
                avg[name] = arr.mean(axis=0)
                std[name] = arr.std(axis=0)
        return avg, std

    sugar_avg, sugar_std = _average_coords(sugar_instances, SUGAR_ATOMS)

    # Shift z so C1' is at z=0
    c1_z = sugar_avg.get("C1'", np.zeros(3))[2]
    for name in sugar_avg:
        sugar_avg[name][2] -= c1_z

    base_avg: dict[str, dict[str, np.ndarray]] = {}
    base_std_map: dict[str, dict[str, np.ndarray]] = {}
    for base_type, atom_names in BASE_ATOMS.items():
        if base_instances[base_type]:
            avg, std = _average_coords(base_instances[base_type], atom_names)
            # Shift base atoms by same c1_z offset (they share the frame)
            for name in avg:
                avg[name][2] -= c1_z
            base_avg[base_type] = avg
            base_std_map[base_type] = std

    # ── Backbone step analysis ────────────────────────────────────────────
    backbone_steps: list[BackboneStep] = []
    for i in range(len(inner_a) - 1):
        seq_i = inner_a[i]
        seq_j = inner_a[i + 1]
        res_i = residues[(chain_a, seq_i)]
        res_j = residues[(chain_a, seq_j)]
        partner_i = residues[(chain_b, wc_map[seq_i])]
        partner_j = residues[(chain_b, wc_map[seq_j])]
        backbone_steps.append(analyze_backbone_step(res_i, res_j, partner_i, partner_j, axis_dir))

    # ── WC pair analysis ──────────────────────────────────────────────────
    wc_pairs: list[WCPairGeometry] = []
    for a_seq in inner_a:
        b_seq = wc_map[a_seq]
        wc_pairs.append(analyze_wc_pair(residues[(chain_a, a_seq)], residues[(chain_b, b_seq)]))

    return DuplexAnalysis(
        sugar_template=sugar_avg,
        sugar_std=sugar_std,
        base_templates=base_avg,
        base_std=base_std_map,
        backbone_steps=backbone_steps,
        wc_pairs=wc_pairs,
        chi_angles=chi_angles_map,
        sugar_puckers=sugar_puckers_map,
        ribose_base_rotations=ribose_rotations_map,
        bond_distances=bond_dist_map,
        sugar_instances=sugar_instances,
        base_instances=base_instances,
    )


# ── Calibration — analytical frame constant derivation ──────────────────────


@dataclass
class CalibrationResult:
    """Optimal frame constants derived by comparing NADOC's geometric layer
    against real PDB crystallographic positions."""
    frame_rot_rad: float
    frame_shift_n: float    # nm
    frame_shift_y: float    # nm
    frame_shift_z: float    # nm
    measured_helix_radius: float   # nm (P-to-axis mean)
    measured_twist_deg: float
    measured_rise_nm: float
    rmsd_before: float      # P-atom RMSD with old constants (nm)
    rmsd_after: float       # P-atom RMSD with calibrated constants (nm)
    per_nucleotide: list[dict]


def calibrate_from_pdb(
    pdb_path: str | Path,
    chain_a: str = "A",
    chain_b: str = "B",
    wc_map: Optional[dict[int, int]] = None,
    exclude_terminal: int = 1,
) -> CalibrationResult:
    """Derive optimal frame constants by comparing NADOC's geometric layer
    against real PDB atom positions.

    The approach:
    1. Parse PDB, fit helix axis, identify inner WC pairs.
    2. Build a synthetic NADOC Helix with matching geometry.
    3. Compute NADOC NucleotidePositions for the synthetic helix.
    4. For each nucleotide, measure the offset between the NADOC backbone
       bead and the PDB's P atom position, expressed in the NADOC local
       frame.  Also measure the angular offset between NADOC's e_n and
       the PDB's e_n (the frame rotation constant).
    5. Average across all inner nucleotides.
    """
    from backend.core.constants import (
        BDNA_RISE_PER_BP,
        BDNA_TWIST_PER_BP_RAD,
    )
    from backend.core.geometry import nucleotide_positions, _frame_from_helix_axis
    from backend.core.models import Direction, Helix, Vec3

    # ── 1. Parse and analyse PDB ──────────────────────────────────────────
    atoms = parse_pdb(pdb_path)
    residues = group_residues(atoms)

    chain_a_seqs = sorted(k[1] for k in residues if k[0] == chain_a)
    chain_b_seqs = sorted(k[1] for k in residues if k[0] == chain_b)

    if wc_map is None:
        wc_map = {}
        for idx, a_seq in enumerate(chain_a_seqs):
            b_seq = chain_b_seqs[-(idx + 1)]
            wc_map[a_seq] = b_seq

    inner_a = chain_a_seqs[exclude_terminal:-exclude_terminal]
    inner_b = chain_b_seqs[exclude_terminal:-exclude_terminal]
    n_bp = len(inner_a)

    # Fit helix axis from inner WC pair C1' midpoints
    midpoints = []
    for a_seq in inner_a:
        b_seq = wc_map[a_seq]
        c1_a = residues[(chain_a, a_seq)].pos("C1'")
        c1_b = residues[(chain_b, b_seq)].pos("C1'")
        midpoints.append((c1_a + c1_b) / 2.0)
    midpoints_arr = np.array(midpoints)
    axis_centroid, axis_dir = fit_helix_axis(midpoints_arr)

    # Ensure axis_dir points in chain A 5'→3' direction
    p_first = residues[(chain_a, inner_a[0])].pos("P")
    p_last = residues[(chain_a, inner_a[-1])].pos("P")
    if np.dot(p_last - p_first, axis_dir) < 0:
        axis_dir = -axis_dir

    # Axis endpoints for synthetic helix
    t_vals = np.array([np.dot(mp - axis_centroid, axis_dir) for mp in midpoints])
    t_min, t_max = float(t_vals.min()), float(t_vals.max())
    ax_start = axis_centroid + (t_min - BDNA_RISE_PER_BP * 0.5) * axis_dir
    ax_end = axis_centroid + (t_max + BDNA_RISE_PER_BP * 0.5) * axis_dir

    # Measure PDB helix parameters
    backbone_steps = []
    for i in range(len(inner_a) - 1):
        res_i = residues[(chain_a, inner_a[i])]
        res_j = residues[(chain_a, inner_a[i + 1])]
        partner_i = residues[(chain_b, wc_map[inner_a[i]])]
        partner_j = residues[(chain_b, wc_map[inner_a[i + 1]])]
        backbone_steps.append(analyze_backbone_step(res_i, res_j, partner_i, partner_j, axis_dir))
    measured_rise = float(np.mean([s.rise_nm for s in backbone_steps]))
    measured_twist = float(np.mean([s.twist_deg for s in backbone_steps]))

    # Measure P-to-axis distance for all inner residues
    p_to_axis_dists = []
    for seq in inner_a:
        P = residues[(chain_a, seq)].pos("P")
        t = np.dot(P - axis_centroid, axis_dir)
        proj = axis_centroid + t * axis_dir
        p_to_axis_dists.append(float(np.linalg.norm(P - proj)))
    for seq in inner_b:
        P = residues[(chain_b, seq)].pos("P")
        t = np.dot(P - axis_centroid, axis_dir)
        proj = axis_centroid + t * axis_dir
        p_to_axis_dists.append(float(np.linalg.norm(P - proj)))
    measured_radius = float(np.mean(p_to_axis_dists))

    # ── 2. Build synthetic NADOC Helix ────────────────────────────────────
    # Determine phase: project first FWD P atom radial onto the helix frame
    frame = _frame_from_helix_axis(axis_dir)
    bp0_axis_pt = axis_centroid + t_min * axis_dir
    p_fwd_0 = residues[(chain_a, inner_a[0])].pos("P")
    radial = p_fwd_0 - bp0_axis_pt
    radial -= np.dot(radial, axis_dir) * axis_dir
    radial = _norm(radial)
    pdb_phase = math.atan2(
        float(np.dot(radial, frame[:, 1])),
        float(np.dot(radial, frame[:, 0])),
    )

    synthetic = Helix(
        id="__calibration__",
        axis_start=Vec3.from_array(ax_start),
        axis_end=Vec3.from_array(ax_end),
        phase_offset=pdb_phase,
        twist_per_bp_rad=BDNA_TWIST_PER_BP_RAD,
        length_bp=n_bp,
        bp_start=0,
        direction=Direction.FORWARD,
    )

    # ── 3. Compute NADOC NucleotidePositions ──────────────────────────────
    nuc_positions = nucleotide_positions(synthetic)
    # Index by (bp_index, direction)
    nuc_map: dict[tuple[int, str], object] = {}
    for nuc in nuc_positions:
        nuc_map[(nuc.bp_index, nuc.direction.value)] = nuc

    # ── 4. Per-nucleotide comparison ──────────────────────────────────────
    # For chain A (FORWARD) and chain B (REVERSE), compute frame offsets.
    e_z_chain_a = -axis_dir   # chain A 3'→5'
    e_z_chain_b = axis_dir    # chain B 3'→5'
    wc_map_rev = {b: a for a, b in wc_map.items()}

    # Collect per-direction residuals separately.  FORWARD calibration is
    # authoritative because REVERSE backbone bead placement suffers from
    # the geometric-layer groove-angle mismatch (150° NADOC vs ~120° real).
    # Templates are symmetric via the z-flip in _atom_frame(), so FORWARD-
    # derived constants apply correctly to both directions.
    fwd_shift_n: list[float] = []
    fwd_shift_y: list[float] = []
    fwd_shift_z: list[float] = []
    fwd_rot: list[float] = []
    rev_shift_n: list[float] = []
    rev_shift_y: list[float] = []
    rev_shift_z: list[float] = []
    rev_rot: list[float] = []
    per_nuc: list[dict] = []

    def _compare_nucleotide(
        chain: str, seq: int, bp_idx: int, direction_str: str,
    ) -> None:
        res = residues[(chain, seq)]
        if not res.has("P"):
            return

        nuc = nuc_map.get((bp_idx, direction_str))
        if nuc is None:
            return

        # PDB P atom world position
        P_pdb = res.pos("P")

        # NADOC backbone bead position, radially corrected to match real B-DNA
        from backend.core.atomistic import _ATOMISTIC_P_RADIUS
        bb = nuc.position
        # Radial correction: move backbone from HELIX_RADIUS to _ATOMISTIC_P_RADIUS
        axis_pt_local = ax_start + bp_idx * BDNA_RISE_PER_BP * axis_dir
        radial = bb - axis_pt_local
        radial_perp = radial - np.dot(radial, nuc.axis_tangent) * nuc.axis_tangent
        r_norm = np.linalg.norm(radial_perp)
        if r_norm > 1e-9:
            radial_hat = radial_perp / r_norm
            bb = axis_pt_local + np.dot(radial, nuc.axis_tangent) * nuc.axis_tangent + _ATOMISTIC_P_RADIUS * radial_hat

        # NADOC local basis
        e_n = nuc.base_normal
        e_z_ax = nuc.axis_tangent
        # e_z for template: FORWARD → -axis_tangent, REVERSE → +axis_tangent
        if direction_str == "FORWARD":
            e_z = -e_z_ax
        else:
            e_z = e_z_ax
        e_y = np.cross(e_z, e_n)
        e_y_norm = np.linalg.norm(e_y)
        if e_y_norm < 1e-9:
            return
        e_y = e_y / e_y_norm

        # Positional offset: P_pdb - backbone_bead, in NADOC basis
        delta = P_pdb - bb
        sn = float(np.dot(delta, e_n))
        sy = float(np.dot(delta, e_y))
        sz = float(np.dot(delta, e_z))

        # Rotational offset: angle between NADOC's e_n and PDB's e_n
        if chain == chain_a:
            partner_seq = wc_map.get(seq)
            partner_chain = chain_b
            e_z_pdb = e_z_chain_a
        else:
            partner_seq = wc_map_rev.get(seq)
            partner_chain = chain_a
            e_z_pdb = e_z_chain_b
        if partner_seq is None:
            return
        partner = residues[(partner_chain, partner_seq)]
        _, R_pdb = compute_nucleotide_frame(res, partner, e_z_pdb)
        e_n_pdb = R_pdb[:, 0]

        # Project both e_n vectors into the plane perpendicular to e_z
        e_n_nadoc_proj = e_n - np.dot(e_n, e_z) * e_z
        e_n_pdb_proj = e_n_pdb - np.dot(e_n_pdb, e_z) * e_z
        e_n_nadoc_proj = _norm(e_n_nadoc_proj)
        e_n_pdb_proj = _norm(e_n_pdb_proj)

        cross_val = np.cross(e_n_nadoc_proj, e_n_pdb_proj)
        rot = math.atan2(float(np.dot(cross_val, e_z)),
                         float(np.dot(e_n_nadoc_proj, e_n_pdb_proj)))

        if direction_str == "FORWARD":
            fwd_shift_n.append(sn)
            fwd_shift_y.append(sy)
            fwd_shift_z.append(sz)
            fwd_rot.append(rot)
        else:
            rev_shift_n.append(sn)
            rev_shift_y.append(sy)
            rev_shift_z.append(sz)
            rev_rot.append(rot)

        per_nuc.append({
            "chain": chain, "seq": seq, "bp": bp_idx,
            "direction": direction_str,
            "shift_n": sn, "shift_y": sy, "shift_z": sz,
            "rot_deg": math.degrees(rot),
            "p_to_axis_nm": float(np.linalg.norm(P_pdb - (axis_centroid + np.dot(P_pdb - axis_centroid, axis_dir) * axis_dir))),
        })

    for bp_idx, a_seq in enumerate(inner_a):
        _compare_nucleotide(chain_a, a_seq, bp_idx, "FORWARD")
    for bp_idx, b_seq in enumerate(reversed(inner_b)):
        _compare_nucleotide(chain_b, b_seq, bp_idx, "REVERSE")

    # ── 5. Average (FORWARD only — authoritative) ──────────────────────
    opt_shift_n = float(np.mean(fwd_shift_n))
    opt_shift_y = float(np.mean(fwd_shift_y))
    opt_shift_z = float(np.mean(fwd_shift_z))
    opt_rot = float(np.mean(fwd_rot))

    # ── 6. Compute RMSD before/after ──────────────────────────────────────
    from backend.core.atomistic import _FRAME_ROT_RAD, _FRAME_SHIFT_N, _FRAME_SHIFT_Y, _FRAME_SHIFT_Z

    def _p_atom_rmsd(rot_rad: float, sn: float, sy: float, sz: float,
                     direction_filter: str = "FORWARD") -> float:
        """Compute RMS distance between predicted P position and actual PDB P.
        Only considers nucleotides matching *direction_filter*."""
        from backend.core.atomistic import _ATOMISTIC_P_RADIUS
        sq_sum = 0.0
        count = 0
        for entry in per_nuc:
            if entry["direction"] != direction_filter:
                continue
            nuc = nuc_map.get((entry["bp"], entry["direction"]))
            if nuc is None:
                continue
            e_n = nuc.base_normal
            e_z_ax = nuc.axis_tangent
            if entry["direction"] == "FORWARD":
                e_z = -e_z_ax
            else:
                e_z = e_z_ax
            e_y = np.cross(e_z, e_n)
            e_y_norm = np.linalg.norm(e_y)
            if e_y_norm < 1e-9:
                continue
            e_y = e_y / e_y_norm

            # Apply radial correction to backbone position
            bb = nuc.position
            axis_pt_local = ax_start + entry["bp"] * BDNA_RISE_PER_BP * axis_dir
            radial = bb - axis_pt_local
            radial_perp = radial - np.dot(radial, nuc.axis_tangent) * nuc.axis_tangent
            r_norm = np.linalg.norm(radial_perp)
            if r_norm > 1e-9:
                radial_hat = radial_perp / r_norm
                bb = axis_pt_local + np.dot(radial, nuc.axis_tangent) * nuc.axis_tangent + _ATOMISTIC_P_RADIUS * radial_hat

            predicted_P = bb + sn * e_n + sy * e_y + sz * e_z
            actual_P = residues[(entry["chain"], entry["seq"])].pos("P")
            sq_sum += float(np.sum((predicted_P - actual_P) ** 2))
            count += 1
        return math.sqrt(sq_sum / max(count, 1))

    rmsd_before = _p_atom_rmsd(_FRAME_ROT_RAD, _FRAME_SHIFT_N, _FRAME_SHIFT_Y, _FRAME_SHIFT_Z)
    rmsd_after = _p_atom_rmsd(opt_rot, opt_shift_n, opt_shift_y, opt_shift_z)

    return CalibrationResult(
        frame_rot_rad=opt_rot,
        frame_shift_n=opt_shift_n,
        frame_shift_y=opt_shift_y,
        frame_shift_z=opt_shift_z,
        measured_helix_radius=measured_radius,
        measured_twist_deg=measured_twist,
        measured_rise_nm=measured_rise,
        rmsd_before=rmsd_before,
        rmsd_after=rmsd_after,
        per_nucleotide=per_nuc,
    )
