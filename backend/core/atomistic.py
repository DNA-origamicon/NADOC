"""
All-atom model builder — Phase AA.

Derives heavy-atom 3D positions for every nucleotide in a Design by
rigidly transforming crystallographic nucleotide templates into the local
frame already computed by geometry.py.  No external converter tools are
used.

Local frame convention (per nucleotide)
────────────────────────────────────────
  origin  = NADOC backbone bead (≈ phosphate P, 1.0 nm from helix axis)
  e_n     = base_normal         (cross-strand unit vector; points toward partner)
  e_z     = axis_tangent        (3′→5′ unit vector for this strand — matches the
                                  template coordinate convention where O5′ is at
                                  +z and O3′ is at −z:
                                  −axis_tangent for FORWARD,
                                  +axis_tangent for REVERSE)
  e_y     = cross(e_z, e_n)     (in-plane perpendicular, completes right-hand frame)

All template coordinates are (n, y, z) in nm.  Positive n = toward base
(inward toward helix axis and partner strand).  The z-axis flip for
REVERSE strands automatically mirrors the sugar chirality so O3′ connects
in the correct 3′ direction for both strands.

Template sources
────────────────
All heavy-atom coordinates are averaged from the B-DNA crystal structure
1zew.pdb (2.25 Å, 10 bp self-complementary duplex CCTCTAGAGG, chains A+B).
Inner residues only (terminals excluded).  C2′-endo/C2′-exo pucker
geometry is preserved from the crystal data.  Template origin is at the
P atom; C1′ is at z=0 for base coplanarity.

Analysis tool: backend/core/pdb_import.py + scripts/analyze_pdb.py.
Calibration tool: scripts/calibrate_pdb.py (derives frame constants analytically).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import math as _math
import numpy as _np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import NucleotidePosition, nucleotide_positions
from backend.core.models import Design, Direction, Strand
from backend.core.sequences import domain_bp_range


# ── Element VDW radii (nm, Bondi 1964) ───────────────────────────────────────

VDW_RADIUS: dict[str, float] = {
    "P": 0.190,
    "C": 0.170,
    "N": 0.155,
    "O": 0.140,
}

# ── CPK colours (hex int) ─────────────────────────────────────────────────────

CPK_COLOR: dict[str, int] = {
    "P": 0xFF8C00,   # orange
    "C": 0x505050,   # dark grey
    "N": 0x3050F8,   # blue
    "O": 0xFF0D0D,   # red
}

# ── Template type alias ───────────────────────────────────────────────────────
# Each entry: (atom_name, element, n_nm, y_nm, z_nm)
_AtomDef = tuple[str, str, float, float, float]

# ── Sugar-phosphate backbone (common to all four residues) ────────────────────
# Origin at P.  C2′-endo pucker.  Connectivity:  …O3′(i-1)→P→O5′→C5′→C4′→C3′→O3′(i)→…
#                                                               ↓
#                                                              O4′→C1′→(base)
#                                                              C2′↗

_SUGAR: tuple[_AtomDef, ...] = (
    # From 1zew.pdb chain A residue 5 (DT) — single reference residue.
    # Averaging across residues is WRONG: the local frame (e_n = C1'→C1') rotates
    # ~34.3° per bp, so backbone atoms appear at different (n,y) positions in each
    # residue's frame.  Averaging gives compressed, meaningless coordinates.
    # Single-residue extraction preserves all intra-residue bond lengths exactly.
    #
    # C1′ z = 0 (base coplanarity shift applied).
    # e_n = cross-strand C1′→C1′,  e_z = helix axis (3′→5′),  e_y = cross(e_z, e_n).
    # Pre-rotated by +37.05° to compensate for _FRAME_ROT_RAD (−37.05°) in _atom_frame().
    ("P",   "P",  0.0000,  0.0000,  0.2712),
    ("OP1", "O", -0.1167, -0.0413,  0.3513),
    ("OP2", "O",  0.0779, -0.1025,  0.1955),
    ("O5'", "O", -0.0596,  0.1096,  0.1710),
    ("C5'", "C", -0.0925,  0.2420,  0.2161),
    ("C4'", "C", -0.0352,  0.3475,  0.1233),
    ("O4'", "O",  0.1092,  0.3562,  0.1320),
    ("C3'", "C", -0.0669,  0.3300, -0.0253),
    ("O3'", "O", -0.0957,  0.4573, -0.0821),
    ("C2'", "C",  0.0635,  0.2795, -0.0840),
    ("C1'", "C",  0.1620,  0.3572,  0.0000),
)

# ── Intra-residue bond table (by atom name pairs) ─────────────────────────────
# Used to build the per-residue bond list.  Inter-residue backbone bonds
# (O3′ → next P) are added during build_atomistic_model().

_SUGAR_BONDS: tuple[tuple[str, str], ...] = (
    ("P",   "OP1"), ("P",   "OP2"),
    ("P",   "O5'"), ("O5'", "C5'"),
    ("C5'", "C4'"), ("C4'", "O4'"), ("C4'", "C3'"),
    ("O4'", "C1'"), ("C3'", "O3'"), ("C3'", "C2'"),
    ("C2'", "C1'"),
)

# ── Base heavy-atom coordinates (1zew crystallographic, NADOC local frame) ────
# Same frame as _SUGAR: origin=P, e_n=C1′→C1′, e_z=helix axis (3′→5′),
# e_y=cross(e_z,e_n).  Averaged from 1zew.pdb inner residues.

# ── Thymine (DT) ──────────────────────────────────────────────────────────────

_DT_BASE: tuple[_AtomDef, ...] = (
    # Whole ring translated by (+0.052607, -0.002851, +0.007491) nm
    # to set C1'–N1 = 1.484 Å (canonical pyrimidine glycosidic bond length).
    # C1' reference: (0.1620, 0.3572, 0.0000) nm from A:5 single-residue sugar template.
    ("N1", "N",  0.3087,  0.3492,  0.0209),
    ("C2", "C",  0.4064,  0.4449,  0.0139),
    ("O2", "O",  0.3852,  0.5627,  0.0258),
    ("N3", "N",  0.5306,  0.3976, -0.0076),
    ("C4", "C",  0.5661,  0.2674, -0.0221),
    ("O4", "O",  0.6824,  0.2394, -0.0396),
    ("C5", "C",  0.4585,  0.1727, -0.0145),
    ("C6", "C",  0.3367,  0.2177,  0.0060),
    ("C7", "C",  0.4878,  0.0296, -0.0292),
)

_DT_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "O4"), ("C5", "C7"),
)

# ── Cytosine (DC) ─────────────────────────────────────────────────────────────

_DC_BASE: tuple[_AtomDef, ...] = (
    # Whole ring translated by (+0.030462, -0.009892, -0.031863) nm
    # to set C1'–N1 = 1.484 Å (canonical pyrimidine glycosidic bond length).
    # C1' reference: (0.1620, 0.3572, 0.0000) nm from A:5 single-residue sugar template.
    ("N1", "N",  0.2621,  0.3247, -0.1047),
    ("C2", "C",  0.3649,  0.4170, -0.1114),
    ("O2", "O",  0.3377,  0.5361, -0.0992),
    ("N3", "N",  0.4908,  0.3743, -0.1311),
    ("C4", "C",  0.5163,  0.2455, -0.1445),
    ("N4", "N",  0.6422,  0.2080, -0.1637),
    ("C5", "C",  0.4137,  0.1495, -0.1390),
    ("C6", "C",  0.2893,  0.1930, -0.1191),
)

_DC_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "N4"),
)

# ── Adenine (DA) ──────────────────────────────────────────────────────────────

_DA_BASE: tuple[_AtomDef, ...] = (
    # Whole ring translated by (+0.001782, -0.000417, -0.005821) nm
    # to set C1'–N9 = 1.459 Å (canonical purine glycosidic bond length).
    # C1' reference: (0.1620, 0.3572, 0.0000) nm from A:5 single-residue sugar template.
    ("N9", "N",  0.1194,  0.3672,  0.1392),
    ("C8", "C",  0.1686,  0.2426,  0.1127),
    ("N7", "N",  0.2979,  0.2390,  0.0979),
    ("C5", "C",  0.3365,  0.3704,  0.1152),
    ("C4", "C",  0.2275,  0.4506,  0.1396),
    ("N3", "N",  0.2282,  0.5826,  0.1603),
    ("C2", "C",  0.3518,  0.6300,  0.1546),
    ("N1", "N",  0.4660,  0.5653,  0.1327),
    ("C6", "C",  0.4618,  0.4325,  0.1126),
    ("N6", "N",  0.5756,  0.3674,  0.0920),
)

_DA_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
    ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
    ("C6",  "N6"),
)

# ── Guanine (DG) ──────────────────────────────────────────────────────────────

_DG_BASE: tuple[_AtomDef, ...] = (
    # Whole ring translated by (+0.053006, -0.010133, -0.008874) nm
    # to set C1'–N9 = 1.459 Å (canonical purine glycosidic bond length).
    # C1' reference: (0.1620, 0.3572, 0.0000) nm from A:5 single-residue sugar template.
    ("N9", "N",  0.3034,  0.3302, -0.0237),
    ("C8", "C",  0.3500,  0.2026, -0.0341),
    ("N7", "N",  0.4793,  0.1958, -0.0325),
    ("C5", "C",  0.5204,  0.3271, -0.0205),
    ("C4", "C",  0.4128,  0.4109, -0.0149),
    ("N3", "N",  0.4115,  0.5444, -0.0033),
    ("C2", "C",  0.5325,  0.5946,  0.0031),
    ("N2", "N",  0.5494,  0.7263,  0.0158),
    ("N1", "N",  0.6460,  0.5198, -0.0020),
    ("C6", "C",  0.6498,  0.3823, -0.0139),
    ("O6", "O",  0.7578,  0.3246, -0.0171),
)

_DG_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
    ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
    ("C6",  "O6"), ("C2", "N2"),
)

# ── Assemble template dict ─────────────────────────────────────────────────────

# BASE_TEMPLATES[residue] = (atom_defs, bond_pairs)
BASE_TEMPLATES: dict[str, tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]] = {
    "DA": (_DA_BASE, _DA_BONDS),
    "DT": (_DT_BASE, _DT_BONDS),
    "DG": (_DG_BASE, _DG_BONDS),
    "DC": (_DC_BASE, _DC_BONDS),
}

_BASE_CHAR_TO_RESIDUE: dict[str, str] = {
    "A": "DA", "T": "DT", "G": "DG", "C": "DC",
    "a": "DA", "t": "DT", "g": "DG", "c": "DC",
}

# ── Output dataclass ──────────────────────────────────────────────────────────


@dataclass
class Atom:
    serial:     int
    name:       str
    element:    str
    residue:    str        # DA / DT / DG / DC
    chain_id:   str        # A / B / C … (one per strand, wrapping at Z)
    seq_num:    int        # 1-based residue number within chain
    x:          float      # nm, world frame
    y:          float
    z:          float
    strand_id:  str
    helix_id:   str
    bp_index:   int
    direction:  str        # "FORWARD" | "REVERSE"
    is_modified: bool = False


@dataclass
class AtomisticModel:
    atoms:  list[Atom]
    bonds:  list[tuple[int, int]]  # 0-based serial pairs


def merge_models(*models: AtomisticModel) -> AtomisticModel:
    """Merge multiple AtomisticModels into one, renumbering serials."""
    atoms: list[Atom] = []
    bonds: list[tuple[int, int]] = []
    offset = 0
    for model in models:
        if not model.atoms:
            continue
        for a in model.atoms:
            atoms.append(Atom(
                serial=a.serial + offset,
                name=a.name, element=a.element, residue=a.residue,
                chain_id=a.chain_id, seq_num=a.seq_num,
                x=a.x, y=a.y, z=a.z,
                strand_id=a.strand_id, helix_id=a.helix_id,
                bp_index=a.bp_index, direction=a.direction,
                is_modified=a.is_modified,
            ))
        for i, j in model.bonds:
            bonds.append((i + offset, j + offset))
        offset += len(model.atoms)
    return AtomisticModel(atoms=atoms, bonds=bonds)


# ── Calibrated frame constants ───────────────────────────────────────────────
# Derived from 1zew.pdb by comparing NADOC's geometric-layer backbone bead
# positions against real crystallographic P-atom positions (FWD strand).
# _FRAME_SHIFT_N/Y were calibrated for P_RADIUS=0.928 (PDB P-to-axis fit);
# _ATOMISTIC_P_RADIUS was then tuned to 0.971 to match PDB C1′–C1′ cross-strand
# distance (~1.074 nm).  The net effect is that the C1′ atoms sit at the correct
# distance from their Watson-Crick partner, matching crystallographic geometry.
# Calibration tool: scripts/calibrate_pdb.py

_FRAME_ROT_RAD: float = -0.646577   # −37.05° (calibrated from 1zew.pdb)
_FRAME_SHIFT_N: float =  0.0860     # nm along e_n (toward partner strand)
_FRAME_SHIFT_Y: float =  0.0926     # nm along e_y (tangential)
_FRAME_SHIFT_Z: float =  0.0706     # nm along e_z (axial)

# The geometric layer places backbone beads at HELIX_RADIUS (1.0 nm, oxDNA convention).
# The atomistic renderer corrects the radial position before applying frame shifts,
# keeping the coarse-grained view unchanged while giving atomistic atoms correct
# cross-strand distances.  Tuned so C1′–C1′ ≈ 1.074 nm (PDB 1zew average).
_ATOMISTIC_P_RADIUS: float = 0.971  # nm

# ── Per-residue empirical corrections (test_atomic overlay, 2026-04-13) ───────
# After placing each residue in its local frame, the whole frame is additionally
# rotated around the helix axis (azimuthal) and shifted along it (axial).
# Calibrated by comparing the NADOC atomistic model with averaged 1zew.pdb
# inner GC pairs using the Help → Test Atomic overlay.
# These are applied in _atom_frame() only when axis_point is provided.
_ATOMISTIC_AZIMUTH_RAD: float = _math.radians(-78.0)  # −78° around helix axis
_ATOMISTIC_AXIAL_CORR:  float = 0.02                  # nm, along axis_tangent

# ── Frame builder ─────────────────────────────────────────────────────────────


def _atom_frame(
    nuc_pos: NucleotidePosition,
    direction: Direction,
    axis_point: _np.ndarray | None = None,
) -> tuple[_np.ndarray, _np.ndarray]:
    """
    Returns (origin, R) where:
      origin  = world position of the template origin (the P atom)
      R       = 3×3 rotation matrix with columns [e_n, e_y, e_z]

    e_z = template 3′→5′ axis (−axis_tangent for FORWARD, +axis_tangent for REVERSE).
    Template convention: O5′ at +z (toward 5′/previous residue), O3′ at −z (toward
    3′/next residue).  Flipping the sign vs. axis_tangent also un-mirrors the sugar
    chirality to the correct D-deoxyribose handedness.

    If *axis_point* is provided, the backbone position is radially corrected
    from HELIX_RADIUS to _ATOMISTIC_P_RADIUS before applying frame shifts,
    so atom positions match real B-DNA crystallographic distances.
    """
    bb = nuc_pos.position
    e_radial: _np.ndarray | None = None   # outward unit vector from axis to bead
    if axis_point is not None:
        radial = bb - axis_point
        radial_perp = radial - _np.dot(radial, nuc_pos.axis_tangent) * nuc_pos.axis_tangent
        r_norm = _np.linalg.norm(radial_perp)
        if r_norm > 1e-9:
            e_radial = radial_perp / r_norm
            bb = axis_point + _np.dot(radial, nuc_pos.axis_tangent) * nuc_pos.axis_tangent + _ATOMISTIC_P_RADIUS * e_radial

    e_n = nuc_pos.base_normal                                          # unit vector
    # Template z-axis = 3′→5′ direction (O5′ is at +z, O3′ is at −z in the template).
    # FORWARD 3′→5′ = −axis_tangent; REVERSE 3′→5′ = +axis_tangent.
    e_z = -nuc_pos.axis_tangent if direction == Direction.FORWARD else nuc_pos.axis_tangent
    e_y = _np.cross(e_z, e_n)
    norm = _np.linalg.norm(e_y)
    if norm < 1e-9:
        # Degenerate case (axis_tangent ∥ base_normal) — use fallback
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(_np.dot(e_n, fallback)) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        e_y = _np.cross(e_z, fallback)
        norm = _np.linalg.norm(e_y)
    e_y /= norm
    origin = bb + _FRAME_SHIFT_N * e_n + _FRAME_SHIFT_Y * e_y + _FRAME_SHIFT_Z * e_z
    R = _np.column_stack([e_n, e_y, e_z])
    c, s = _math.cos(_FRAME_ROT_RAD), _math.sin(_FRAME_ROT_RAD)
    R = R @ _np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])

    # ── Azimuthal + axial per-residue correction ──────────────────────────────
    # Rotate origin and R around the helix axis (Rodrigues) then shift axially.
    # Applied only when axis_point is available (always the case in build_atomistic_model).
    if axis_point is not None:
        ax = nuc_pos.axis_tangent          # helix axis unit vector

        # The azimuth correction was calibrated on a helix whose minor groove sits
        # at −150° (direction=None → REVERSE lattice parity → negative groove sign).
        # For FORWARD-parity helices the groove is +150° and base_normal is mirrored,
        # so the correction must be negated.  Detected geometrically: the sign of
        # dot(e_n, cross(e_z, e_radial)) is positive for −150° and negative for +150°.
        if e_radial is not None:
            azimuth_sign = 1.0 if _np.dot(e_n, _np.cross(e_z, e_radial)) >= 0 else -1.0
        else:
            azimuth_sign = 1.0
        azimuth_rad = azimuth_sign * _ATOMISTIC_AZIMUTH_RAD

        c_az = _math.cos(azimuth_rad)
        s_az = _math.sin(azimuth_rad)
        # Rodrigues rotation matrix around ax
        _K   = _np.array([[ 0.,    -ax[2],  ax[1]],
                           [ ax[2],  0.,    -ax[0]],
                           [-ax[1],  ax[0],  0.   ]])
        R_az = _np.eye(3) + s_az * _K + (1. - c_az) * (_K @ _K)
        # Rotate only the perpendicular (XY-like) part of origin relative to axis_point
        rel    = origin - axis_point
        axial  = _np.dot(rel, ax) * ax
        origin = axis_point + R_az @ (rel - axial) + axial + _ATOMISTIC_AXIAL_CORR * ax
        R      = R_az @ R

    return origin, R


# ── Backbone torsion adjustment ───────────────────────────────────────────────


def _apply_backbone_torsions(
    delta_rad: float = 0.0,
    gamma_rad: float = 0.0,
    beta_rad: float = 0.0,
) -> tuple[_AtomDef, ...]:
    """
    Return a modified _SUGAR tuple with δ, γ, and β backbone torsions adjusted.
    Applied in order: δ first, then γ, then β.

    delta_rad: rotation around the C3′–C4′ bond axis (pivot = C4′).
               Moves C5′, O5′, P, OP1, OP2.  Adjusts the δ dihedral (C5′–C4′–C3′–O3′).
    gamma_rad: rotation around the C4′–C5′ bond axis (pivot = C5′).
               Moves O5′, P, OP1, OP2.  Adjusts the γ dihedral (O5′–C5′–C4′–C3′).
    beta_rad:  rotation around the C5′–O5′ bond axis (pivot = O5′).
               Moves P, OP1, OP2.  Adjusts the β dihedral (P–O5′–C5′–C4′).
    """
    if not delta_rad and not gamma_rad and not beta_rad:
        return _SUGAR

    pos = {name: _np.array([n, y, z], dtype=float) for name, _, n, y, z in _SUGAR}
    elem_map = {name: el for name, el, *_ in _SUGAR}

    def _rot(pivot: _np.ndarray, axis_vec: _np.ndarray, names: list[str], angle: float) -> None:
        ax = axis_vec / _np.linalg.norm(axis_vec)
        c, s = _np.cos(angle), _np.sin(angle)
        for nm in names:
            v = pos[nm] - pivot
            pos[nm] = pivot + v * c + _np.cross(ax, v) * s + ax * _np.dot(ax, v) * (1.0 - c)

    if delta_rad:
        # Rotate C5′/O5′/P/OP1/OP2 around C3′→C4′ axis, pivot at C4′
        pivot = pos["C4'"].copy()
        axis  = pos["C4'"] - pos["C3'"]
        _rot(pivot, axis, ["C5'", "O5'", "P", "OP1", "OP2"], delta_rad)

    if gamma_rad:
        # Rotate O5′/P/OP1/OP2 around C4′→C5′ axis, pivot at C5′ (post-δ position)
        pivot = pos["C5'"].copy()
        axis  = pos["C5'"] - pos["C4'"]
        _rot(pivot, axis, ["O5'", "P", "OP1", "OP2"], gamma_rad)

    if beta_rad:
        # Rotate P/OP1/OP2 around C5′→O5′ axis, pivot at O5′ (post-γ position)
        pivot = pos["O5'"].copy()
        axis  = pos["O5'"] - pos["C5'"]
        _rot(pivot, axis, ["P", "OP1", "OP2"], beta_rad)

    return tuple(
        (name, elem_map[name], float(pos[name][0]), float(pos[name][1]), float(pos[name][2]))
        for name, *_ in _SUGAR
    )


# ── Sequence lookup builder ───────────────────────────────────────────────────


def _build_sequence_map(design: Design) -> dict[tuple[str, int, str], str]:
    """
    Returns a mapping (helix_id, bp_index, direction) → base character (A/T/G/C/N).

    Iterates all strands.  If a strand has a sequence, distributes characters
    across its domains 5′→3′ in domain order.
    """
    seq_map: dict[tuple[str, int, str], str] = {}
    for strand in design.strands:
        if not strand.sequence:
            continue
        seq = strand.sequence
        idx = 0
        for domain in strand.domains:
            if idx >= len(seq):
                break
            h_id = domain.helix_id
            dir_str = domain.direction.value
            for bp in domain_bp_range(domain):
                if idx >= len(seq):
                    break
                seq_map[(h_id, bp, dir_str)] = seq[idx]
                idx += 1
    return seq_map


# ── Model builder ─────────────────────────────────────────────────────────────


def build_atomistic_model(
    design: Design,
    exclude_helix_ids: set[str] | None = None,
) -> AtomisticModel:
    """
    Build the heavy-atom model for the entire design.

    Returns an AtomisticModel with a flat atom list and a bond list (0-based
    serial pairs).  Serial numbers are 0-based to match the list index.

    Frame constants (_FRAME_ROT_RAD, _FRAME_SHIFT_*, _ATOMISTIC_P_RADIUS,
    _ATOMISTIC_AZIMUTH_RAD, _ATOMISTIC_AXIAL_CORR) are baked in at the module
    level and not overridable here — ensuring the production renderer always
    produces the same result as the Test Atomic reference.

    Bond coverage:
    - All intra-residue bonds (sugar + base ring)
    - Inter-residue backbone bonds: O3′(i) → P(i+1) for consecutive bp on the
      same strand segment (direction-aware; skips across crossovers/nicks).
    """
    seq_map = _build_sequence_map(design)
    sugar_template = _SUGAR

    # Build chain_id assignment: one letter per strand, wrapping A-Z then AA-AZ etc.
    strand_to_chain: dict[str, str] = {}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for si, strand in enumerate(design.strands):
        if si < 26:
            strand_to_chain[strand.id] = letters[si]
        else:
            strand_to_chain[strand.id] = letters[si // 26 - 1] + letters[si % 26]

    # (helix_id, bp_index, direction_str) → (o3_serial, p_serial) for backbone bonds
    bp_to_serials: dict[tuple[str, int, str], tuple[Optional[int], Optional[int]]] = {}

    # Cache nucleotide positions per helix (avoid recomputing for each domain)
    helix_map   = {h.id: h for h in design.helices}
    nuc_pos_cache: dict[str, dict[tuple[int, Direction], NucleotidePosition]] = {}

    # Cache helix axis geometry for radial correction: (axis_start, axis_hat)
    _helix_axis_cache: dict[str, tuple[_np.ndarray, _np.ndarray, int]] = {}
    for h in design.helices:
        s = _np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        e = _np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z])
        ax = e - s
        ln = _np.linalg.norm(ax)
        _helix_axis_cache[h.id] = (s, ax / ln if ln > 1e-9 else ax, h.bp_start)

    atoms:  list[Atom]            = []
    bonds:  list[tuple[int, int]] = []
    serial  = 0

    for strand in design.strands:
        chain_id = strand_to_chain[strand.id]
        seq_num_in_chain = 0

        for domain in strand.domains:
            h_id      = domain.helix_id
            dir_str   = domain.direction.value
            direction = domain.direction

            if exclude_helix_ids and h_id in exclude_helix_ids:
                continue

            helix = helix_map.get(h_id)
            if helix is None:
                continue

            if h_id not in nuc_pos_cache:
                nuc_pos_cache[h_id] = {
                    (nuc.bp_index, nuc.direction): nuc
                    for nuc in nucleotide_positions(helix)
                }
            nuc_positions = nuc_pos_cache[h_id]

            for bp in domain_bp_range(domain):
                nuc_pos = nuc_positions.get((bp, direction))
                if nuc_pos is None:
                    continue  # skip/loop position

                seq_num_in_chain += 1
                base_char = seq_map.get((h_id, bp, dir_str), "N")
                residue   = _BASE_CHAR_TO_RESIDUE.get(base_char, "DT")

                # Compute helix axis point for radial correction
                ax_start, ax_hat, bp_start = _helix_axis_cache[h_id]
                axis_pt = ax_start + (bp - bp_start) * BDNA_RISE_PER_BP * ax_hat

                origin, R = _atom_frame(nuc_pos, direction, axis_point=axis_pt)

                # ── Sugar + phosphate atoms ───────────────────────────────
                sugar_name_to_serial: dict[str, int] = {}
                for atom_name, element, n, y, z_local in sugar_template:
                    local = _np.array([n, y, z_local])
                    world = origin + R @ local
                    atoms.append(Atom(
                        serial    = serial,
                        name      = atom_name,
                        element   = element,
                        residue   = residue,
                        chain_id  = chain_id,
                        seq_num   = seq_num_in_chain,
                        x         = float(world[0]),
                        y         = float(world[1]),
                        z         = float(world[2]),
                        strand_id = strand.id,
                        helix_id  = h_id,
                        bp_index  = bp,
                        direction = dir_str,
                    ))
                    sugar_name_to_serial[atom_name] = serial
                    serial += 1

                # ── Base atoms ────────────────────────────────────────────
                base_atoms_def, base_bond_defs = BASE_TEMPLATES[residue]
                base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
                for atom_name, element, n, y, z_local in base_atoms_def:
                    local = _np.array([n, y, z_local])
                    world = origin + R @ local
                    atoms.append(Atom(
                        serial    = serial,
                        name      = atom_name,
                        element   = element,
                        residue   = residue,
                        chain_id  = chain_id,
                        seq_num   = seq_num_in_chain,
                        x         = float(world[0]),
                        y         = float(world[1]),
                        z         = float(world[2]),
                        strand_id = strand.id,
                        helix_id  = h_id,
                        bp_index  = bp,
                        direction = dir_str,
                    ))
                    base_name_to_serial[atom_name] = serial
                    serial += 1

                # ── Intra-residue bonds ───────────────────────────────────
                # Sugar backbone bonds
                for a_name, b_name in _SUGAR_BONDS:
                    sa = sugar_name_to_serial.get(a_name)
                    sb = sugar_name_to_serial.get(b_name)
                    if sa is not None and sb is not None:
                        bonds.append((sa, sb))
                # Base bonds (includes C1′→N1/N9 glycosidic bond)
                for a_name, b_name in base_bond_defs:
                    sa = base_name_to_serial.get(a_name)
                    sb = base_name_to_serial.get(b_name)
                    if sa is not None and sb is not None:
                        bonds.append((sa, sb))

                # Register for inter-residue backbone bond building
                bp_to_serials[(h_id, bp, dir_str)] = (
                    sugar_name_to_serial.get("O3'"),
                    sugar_name_to_serial.get("P"),
                )

    # ── Inter-residue backbone bonds (O3′ → P of next residue) ───────────────
    # Walk each strand's domains in 5′→3′ order; connect consecutive bp.
    for strand in design.strands:
        direction = None
        prev_o3_serial: Optional[int] = None
        for domain in strand.domains:
            h_id      = domain.helix_id
            dir_str   = domain.direction.value
            direction = domain.direction
            for bp in domain_bp_range(domain):
                entry = bp_to_serials.get((h_id, bp, dir_str))
                if entry is None:
                    prev_o3_serial = None
                    continue
                o3_serial, p_serial = entry
                if prev_o3_serial is not None and p_serial is not None:
                    bonds.append((prev_o3_serial, p_serial))
                prev_o3_serial = o3_serial

    return AtomisticModel(atoms=atoms, bonds=bonds)


def _normalise(v: _np.ndarray) -> _np.ndarray:
    n = float(_np.linalg.norm(v))
    return v / n if n > 1e-9 else v


# ── Serialisation helper ──────────────────────────────────────────────────────


def atomistic_to_json(model: AtomisticModel) -> dict:
    """Convert AtomisticModel to a JSON-serialisable dict for the API."""
    return {
        "atoms": [
            {
                "serial":      a.serial,
                "name":        a.name,
                "element":     a.element,
                "residue":     a.residue,
                "chain_id":    a.chain_id,
                "seq_num":     a.seq_num,
                "x":           round(a.x, 5),
                "y":           round(a.y, 5),
                "z":           round(a.z, 5),
                "strand_id":   a.strand_id,
                "helix_id":    a.helix_id,
                "bp_index":    a.bp_index,
                "direction":   a.direction,
                "is_modified": a.is_modified,
            }
            for a in model.atoms
        ],
        "bonds": [[i, j] for i, j in model.bonds],
        "element_meta": {
            el: {"vdw_radius": r, "cpk_color": CPK_COLOR[el]}
            for el, r in VDW_RADIUS.items()
        },
    }
