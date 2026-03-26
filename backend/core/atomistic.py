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
All heavy-atom coordinates are derived from the Drew-Dickerson dodecamer
crystal structure (dd12_na.pdb, chain A) and transformed into the NADOC
local frame.  C2′-endo pucker geometry is preserved from the crystal data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import math as _math
import numpy as _np

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
    # Coordinates in NADOC local frame:
    #   e_n = base_normal (toward partner strand),  e_z = 3′→5′,  e_y = cross(e_z, e_n)
    #
    # Ring atoms (C4′ onward) are shifted +0.1689 nm in z to bring C1′ and all
    # base atoms to z = 0 (base coplanarity across FORWARD/REVERSE strands).
    #
    # C5′/O5′/P were placed using the NERF algorithm from 1BNA internal coords:
    #   C3′-C4′-C5′ = 116.1°, O4′-C4′-C5′ = 107.4°, then adjusted with
    #   δ = +88°, γ = −77°, β = +180° torsion rotations to match 1BNA visually.
    # OP1/OP2 are placed tetrahedrally: O5′-P-OP1 = O5′-P-OP2 =
    #   O3′(prev)-P-OP1 = O3′(prev)-P-OP2 = 109.47°, OP1-P-OP2 = 114.4°.
    ("P",   "P", -0.0158,  0.1754,  0.2763),
    ("OP1", "O",  0.0175,  0.2582,  0.3945),
    ("OP2", "O", -0.1155,  0.2428,  0.1900),
    ("O5'", "O",  0.1166,  0.1473,  0.1923),
    ("C5'", "C",  0.2387,  0.1760,  0.2625),
    # Ring atoms shifted by +0.1689 nm in z:
    ("C4'", "C",  0.3480,  0.1688,  0.1601),
    ("O4'", "O",  0.4507,  0.0727,  0.1371),
    ("C3'", "C",  0.3137,  0.2229,  0.0213),
    ("O3'", "O",  0.3961,  0.3331, -0.0145),
    ("C2'", "C",  0.3454,  0.1044, -0.0699),
    ("C1'", "C",  0.4657,  0.0420,  0.0000),
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

# ── Base heavy-atom coordinates (dd12 crystallographic, NADOC local frame) ────
# Same frame as _SUGAR: origin=P, e_n=base_normal, e_z=3′→5′, e_y=cross(e_z,e_n).
# Source: Drew-Dickerson dodecamer (dd12_na.pdb, chain A).

# ── Thymine (DT) ──────────────────────────────────────────────────────────────

_BASE_Z = 0.0  # base atoms coplanar with C1′ (z = 0 = P-plane) for correct base-pair planarity

_DT_BASE: tuple[_AtomDef, ...] = (
    ("N1", "N",  0.4693, -0.1066, _BASE_Z),
    ("C2", "C",  0.5929, -0.1659, _BASE_Z),
    ("O2", "O",  0.6967, -0.1021, _BASE_Z),
    ("N3", "N",  0.5922, -0.3038, _BASE_Z),
    ("C4", "C",  0.4808, -0.3853, _BASE_Z),
    ("O4", "O",  0.4929, -0.5078, _BASE_Z),
    ("C5", "C",  0.3558, -0.3141, _BASE_Z),
    ("C6", "C",  0.3536, -0.1800, _BASE_Z),
    ("C7", "C",  0.2297, -0.3954, _BASE_Z),
)

_DT_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "O4"), ("C5", "C7"),
)

# ── Cytosine (DC) ─────────────────────────────────────────────────────────────

_DC_BASE: tuple[_AtomDef, ...] = (
    ("N1", "N",  0.4693, -0.1067, _BASE_Z),
    ("C2", "C",  0.5938, -0.1682, _BASE_Z),
    ("O2", "O",  0.6952, -0.0975, _BASE_Z),
    ("N3", "N",  0.5991, -0.3036, _BASE_Z),
    ("C4", "C",  0.4869, -0.3766, _BASE_Z),
    ("N4", "N",  0.4975, -0.5084, _BASE_Z),
    ("C5", "C",  0.3578, -0.3153, _BASE_Z),
    ("C6", "C",  0.3547, -0.1798, _BASE_Z),
)

_DC_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "N4"),
)

# ── Adenine (DA) ──────────────────────────────────────────────────────────────

_DA_BASE: tuple[_AtomDef, ...] = (
    ("N9", "N",  0.4693, -0.1067, _BASE_Z),
    ("C8", "C",  0.3647, -0.1961, _BASE_Z),
    ("N7", "N",  0.4013, -0.3202, _BASE_Z),
    ("C5", "C",  0.5397, -0.3138, _BASE_Z),
    ("C4", "C",  0.5818, -0.1841, _BASE_Z),
    ("N3", "N",  0.7094, -0.1405, _BASE_Z),
    ("C2", "C",  0.7929, -0.2416, _BASE_Z),
    ("N1", "N",  0.7667, -0.3721, _BASE_Z),
    ("C6", "C",  0.6387, -0.4129, _BASE_Z),
    ("N6", "N",  0.6117, -0.5441, _BASE_Z),
)

_DA_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
    ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
    ("C6",  "N6"),
)

# ── Guanine (DG) ──────────────────────────────────────────────────────────────

_DG_BASE: tuple[_AtomDef, ...] = (
    ("N9", "N",  0.4693, -0.1067, _BASE_Z),
    ("C8", "C",  0.3648, -0.1965, _BASE_Z),
    ("N7", "N",  0.4022, -0.3219, _BASE_Z),
    ("C5", "C",  0.5412, -0.3146, _BASE_Z),
    ("C4", "C",  0.5831, -0.1837, _BASE_Z),
    ("N3", "N",  0.7099, -0.1353, _BASE_Z),
    ("C2", "C",  0.8005, -0.2324, _BASE_Z),
    ("N2", "N",  0.9306, -0.2035, _BASE_Z),
    ("N1", "N",  0.7678, -0.3664, _BASE_Z),
    ("C6", "C",  0.6375, -0.4182, _BASE_Z),
    ("O6", "O",  0.6199, -0.5395, _BASE_Z),
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


# ── Empirically-tuned frame constants ────────────────────────────────────────
# These values were found by visual inspection to align base pairs correctly
# with NADOC's coarse-grained backbone frame.

_FRAME_ROT_RAD: float = _math.radians(39.0)  # rotation of residue around helix axis
_FRAME_SHIFT_N: float = -0.07   # nm along e_n (toward partner strand)
_FRAME_SHIFT_Y: float = -0.59   # nm along e_y (tangential)
_FRAME_SHIFT_Z: float =  0.00   # nm along e_z (axial)

# ── Frame builder ─────────────────────────────────────────────────────────────


def _atom_frame(
    nuc_pos: NucleotidePosition,
    direction: Direction,
    frame_rot_rad: float = _FRAME_ROT_RAD,
    frame_shift_n: float = _FRAME_SHIFT_N,
    frame_shift_y: float = _FRAME_SHIFT_Y,
    frame_shift_z: float = _FRAME_SHIFT_Z,
) -> tuple[_np.ndarray, _np.ndarray]:
    """
    Returns (origin, R) where:
      origin  = world position of the template origin (the P atom)
      R       = 3×3 rotation matrix with columns [e_n, e_y, e_z]

    e_z = template 3′→5′ axis (−axis_tangent for FORWARD, +axis_tangent for REVERSE).
    Template convention: O5′ at +z (toward 5′/previous residue), O3′ at −z (toward
    3′/next residue).  Flipping the sign vs. axis_tangent also un-mirrors the sugar
    chirality to the correct D-deoxyribose handedness.
    """
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
    origin = nuc_pos.position + frame_shift_n * e_n + frame_shift_y * e_y + frame_shift_z * e_z
    R = _np.column_stack([e_n, e_y, e_z])
    c, s = _math.cos(frame_rot_rad), _math.sin(frame_rot_rad)
    R = R @ _np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
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
    delta_rad: float = 0.0,
    gamma_rad: float = 0.0,
    beta_rad: float = 0.0,
    frame_rot_rad: float = _FRAME_ROT_RAD,
    frame_shift_n: float = _FRAME_SHIFT_N,
    frame_shift_y: float = _FRAME_SHIFT_Y,
    frame_shift_z: float = _FRAME_SHIFT_Z,
    crossover_mode: str = 'none',
) -> AtomisticModel:
    """
    Build the heavy-atom model for the entire design.

    Returns an AtomisticModel with a flat atom list and a bond list (0-based
    serial pairs).  Serial numbers are 0-based to match the list index.

    delta_rad:    extra rotation around C3′–C4′ bond (adjusts δ dihedral; moves C5′/O5′/P/OP1/OP2).
    gamma_rad:    extra rotation around C4′–C5′ bond (adjusts γ dihedral; moves O5′/P/OP1/OP2).
    beta_rad:     extra rotation around C5′–O5′ bond (adjusts β dihedral; moves P/OP1/OP2).
    frame_rot_rad: in-plane rotation of each residue around its local z-axis (moves all atoms).
    frame_shift_n: shift along e_n (toward partner strand; moves all atoms).
    frame_shift_y: shift along e_y (tangential; moves all atoms).
    frame_shift_z: shift along e_z (axial; moves all atoms).

    Bond coverage:
    - All intra-residue bonds (sugar + base ring)
    - Inter-residue backbone bonds: O3′(i) → P(i+1) for consecutive bp on the
      same strand segment (direction-aware; skips across crossovers/nicks).
    """
    seq_map = _build_sequence_map(design)

    # Pre-compute the (possibly torsion-adjusted) sugar template once for all residues.
    sugar_template = _apply_backbone_torsions(delta_rad, gamma_rad, beta_rad)

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

                origin, R = _atom_frame(nuc_pos, direction,
                                       frame_rot_rad, frame_shift_n,
                                       frame_shift_y, frame_shift_z)

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

    # ── Extra bases at crossovers (CrossoverBases, CPD/crosslinking tools) ────
    # Each CrossoverBases entry inserts N user-defined single-stranded residues
    # into the backbone gap of a crossover, placed along a quadratic Bézier arc
    # between the two anchor nucleotides.
    _build_crossover_bases_atoms(
        design, atoms, bonds, bp_to_serials, nuc_pos_cache, helix_map,
        strand_to_chain, sugar_template,
        frame_rot_rad, frame_shift_n, frame_shift_y, frame_shift_z,
    )

    _adjust_crossover_backbones(atoms, bonds, crossover_mode)
    return AtomisticModel(atoms=atoms, bonds=bonds)


def _build_crossover_bases_atoms(
    design: Design,
    atoms: list,
    bonds: list,
    bp_to_serials: dict,
    nuc_pos_cache: dict,
    helix_map: dict,
    strand_to_chain: dict,
    sugar_template,
    frame_rot_rad: float,
    frame_shift_n: float,
    frame_shift_y: float,
    frame_shift_z: float,
) -> None:
    """
    Append heavy-atom residues for all CrossoverBases entries in the design.

    Positions are placed along a quadratic Bézier arc connecting the 3′-anchor
    of domain_a to the 5′-anchor of domain_b, matching the geometry computed
    by the frontend/backend geometry layer.

    Also adds O3′→P inter-residue bonds connecting:
      • last domain-A residue → first extra-base
      • consecutive extra-bases
      • last extra-base → first domain-B residue
    """
    xo_by_id = {xo.id: xo for xo in design.crossovers}
    strand_by_id = {s.id: s for s in design.strands}

    # Build helix-pair → sorted departure-bp list for z_sign determination.
    # Same logic as _crossover_bases_geometry in crud.py.
    from collections import defaultdict as _defaultdict
    _hp_bps: dict = _defaultdict(list)
    for _xo in design.crossovers:
        _s = strand_by_id.get(_xo.strand_a_id)
        if _s is None or _xo.domain_a_index >= len(_s.domains):
            continue
        _da = _s.domains[_xo.domain_a_index]
        _sb = strand_by_id.get(_xo.strand_b_id)
        if _sb is None or _xo.domain_b_index >= len(_sb.domains):
            continue
        _db = _sb.domains[_xo.domain_b_index]
        _hp_bps[frozenset({_da.helix_id, _db.helix_id})].append((_da.end_bp, _xo.id))

    for cb in (design.crossover_bases or []):
        xo = xo_by_id.get(cb.crossover_id)
        if xo is None:
            continue
        strand = strand_by_id.get(cb.strand_id)
        if strand is None:
            continue
        if xo.domain_a_index >= len(strand.domains) or xo.domain_b_index >= len(strand.domains):
            continue

        dom_a = strand.domains[xo.domain_a_index]
        dom_b = strand.domains[xo.domain_b_index]

        # 3′ end of domain_a (the nucleotide just before the crossover gap).
        # 5′ end of domain_b (the nucleotide just after the crossover gap).
        # end_bp is always the 3′ end and start_bp is always the 5′ end
        # regardless of direction — no direction check needed.
        bp_a = dom_a.end_bp
        bp_b = dom_b.start_bp

        # Ensure helix position caches are built.
        for h_id, dom in ((dom_a.helix_id, dom_a), (dom_b.helix_id, dom_b)):
            if h_id not in nuc_pos_cache:
                helix = helix_map.get(h_id)
                if helix:
                    nuc_pos_cache[h_id] = {
                        (nuc.bp_index, nuc.direction): nuc
                        for nuc in nucleotide_positions(helix)
                    }

        nuc_a = nuc_pos_cache.get(dom_a.helix_id, {}).get((bp_a, dom_a.direction))
        nuc_b = nuc_pos_cache.get(dom_b.helix_id, {}).get((bp_b, dom_b.direction))
        if nuc_a is None or nuc_b is None:
            continue

        p0 = nuc_a.position
        p2 = nuc_b.position
        mid = (p0 + p2) * 0.5
        dist = float(_np.linalg.norm(p2 - p0))

        # Bézier control point (same formula as crud.py geometry helper).
        if dist > 1e-6:
            chord_hat = (p2 - p0) / dist
            perp = _np.cross(chord_hat, _np.array([0.0, 0.0, 1.0]))
            if _np.linalg.norm(perp) < 1e-6:
                perp = _np.cross(chord_hat, _np.array([0.0, 1.0, 0.0]))
            perp = perp / _np.linalg.norm(perp)
        else:
            perp = _np.array([0.0, 1.0, 0.0])
        p1 = mid + perp * dist * 0.15

        # z_sign: same companion-nearest rule as _crossover_bases_geometry.
        # All bases on this crossover share one sign.
        # Lower departure-bp of the DX pair → −Z, higher → +Z.
        _this_bp = dom_a.end_bp
        _hp      = frozenset({dom_a.helix_id, dom_b.helix_id})
        _companions = [(bp, xid) for bp, xid in _hp_bps.get(_hp, []) if xid != xo.id]
        if _companions:
            _comp_bp = min(_companions, key=lambda e: abs(e[0] - _this_bp))[0]
            z_sign = -1.0 if _this_bp < _comp_bp else 1.0
        else:
            z_sign = -1.0

        n_bases = len(cb.sequence)
        chain_id = strand_to_chain.get(strand.id, 'A')

        # Determine seq_num offset: the extra bases follow the last domain-A residue.
        # We compute it from the domain_a domain's bp count.
        dom_a_len = abs(dom_a.end_bp - dom_a.start_bp) + 1
        # Find position in chain by counting all domains up to and including domain_a.
        seq_num_base = sum(
            abs(strand.domains[di].end_bp - strand.domains[di].start_bp) + 1
            for di in range(xo.domain_a_index + 1)
        )

        prev_o3_serial: Optional[int] = None

        # Try to connect from the last real domain-A residue's O3'.
        anchor_a_key = (dom_a.helix_id, bp_a, dom_a.direction.value)
        if anchor_a_key in bp_to_serials:
            prev_o3_serial = bp_to_serials[anchor_a_key][0]  # O3' of last domain-A residue

        # Synthetic NucleotidePosition for each Bézier-interpolated base.
        synthetic_helix_id = f"__xb_{cb.id}"
        xb_o3_serials: list[Optional[int]] = []

        for i in range(n_bases):
            t = (i + 1) / (n_bases + 1)
            # Quadratic Bézier
            pos = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
            tangent = 2 * (1 - t) * (p1 - p0) + 2 * t * (p2 - p1)
            tang_len = _np.linalg.norm(tangent)
            if tang_len > 1e-6:
                tangent = tangent / tang_len
            else:
                tangent = nuc_a.axis_tangent

            # Compute base_normal (e_n) so that C1′→N1 points along z_sign*Z.
            #
            # In _atom_frame: R = [e_n, e_y, e_z], where
            #   e_z = ∓tangent (FORWARD/REVERSE), e_y = cross(e_z, e_n).
            # Template has C1′→N1 ≈ −0.1486·ê_y (all base atoms at z_local=0).
            # For C1′→N1 → z_sign·Z we need e_y = [0, 0, −z_sign].
            # cross(e_z, e_n) = [0,0,−z_sign]  ←→  e_n = z_sign·[e_z[1], −e_z[0], 0].
            e_z_dir = -tangent if dom_a.direction == Direction.FORWARD else tangent
            bn_xy = _np.array([z_sign * e_z_dir[1], -z_sign * e_z_dir[0], 0.0])
            bn_norm = _np.linalg.norm(bn_xy)
            if bn_norm > 1e-9:
                bn = bn_xy / bn_norm
            else:
                bn = _np.array([1.0, 0.0, 0.0])  # degenerate: tangent along Z

            base_pos = pos + 0.3 * bn

            # Build a synthetic NucleotidePosition for _atom_frame.
            nuc_xb = NucleotidePosition(
                helix_id     = synthetic_helix_id,
                bp_index     = i,
                direction    = dom_a.direction,
                position     = pos,
                base_position= base_pos,
                base_normal  = bn,
                axis_tangent = tangent,
            )

            seq_num_in_chain = seq_num_base + i + 1
            base_char = cb.sequence[i].upper()
            residue   = _BASE_CHAR_TO_RESIDUE.get(base_char, "DT")

            # Extra-base frame: zero in-plane rotation (frame_rot_rad=0) so that
            # C1′→N1 aligns with ±Z as derived above, and zero tangential shift
            # (frame_shift_y=0) so the P atom stays on the Bézier arc rather than
            # being pushed 0.59 nm along e_y=[0,0,−z_sign] off the arc.
            origin, R = _atom_frame(nuc_xb, dom_a.direction,
                                    0.0, frame_shift_n, 0.0, frame_shift_z)

            sugar_name_to_serial: dict[str, int] = {}
            for atom_name, element, n_c, y_c, z_local in sugar_template:
                local = _np.array([n_c, y_c, z_local])
                world = origin + R @ local
                s = len(atoms)
                atoms.append(Atom(
                    serial    = s,
                    name      = atom_name,
                    element   = element,
                    residue   = residue,
                    chain_id  = chain_id,
                    seq_num   = seq_num_in_chain,
                    x         = float(world[0]),
                    y         = float(world[1]),
                    z         = float(world[2]),
                    strand_id = strand.id,
                    helix_id  = synthetic_helix_id,
                    bp_index  = i,
                    direction = dom_a.direction.value,
                ))
                sugar_name_to_serial[atom_name] = s

            base_atoms_def, base_bond_defs = BASE_TEMPLATES[residue]
            base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
            for atom_name, element, n_c, y_c, z_local in base_atoms_def:
                local = _np.array([n_c, y_c, z_local])
                world = origin + R @ local
                s = len(atoms)
                atoms.append(Atom(
                    serial    = s,
                    name      = atom_name,
                    element   = element,
                    residue   = residue,
                    chain_id  = chain_id,
                    seq_num   = seq_num_in_chain,
                    x         = float(world[0]),
                    y         = float(world[1]),
                    z         = float(world[2]),
                    strand_id = strand.id,
                    helix_id  = synthetic_helix_id,
                    bp_index  = i,
                    direction = dom_a.direction.value,
                ))
                base_name_to_serial[atom_name] = s

            # Intra-residue bonds
            for a_name, b_name in _SUGAR_BONDS:
                sa = sugar_name_to_serial.get(a_name)
                sb = sugar_name_to_serial.get(b_name)
                if sa is not None and sb is not None:
                    bonds.append((sa, sb))
            for a_name, b_name in base_bond_defs:
                sa = base_name_to_serial.get(a_name)
                sb = base_name_to_serial.get(b_name)
                if sa is not None and sb is not None:
                    bonds.append((sa, sb))

            # Inter-residue bond: O3' of previous → P of this residue
            p_serial = sugar_name_to_serial.get("P")
            if prev_o3_serial is not None and p_serial is not None:
                bonds.append((prev_o3_serial, p_serial))
            prev_o3_serial = sugar_name_to_serial.get("O3'")
            xb_o3_serials.append(prev_o3_serial)

        # Bond from last extra-base O3' to domain-B's first residue P.
        anchor_b_key = (dom_b.helix_id, bp_b, dom_b.direction.value)
        if anchor_b_key in bp_to_serials and prev_o3_serial is not None:
            _, p_serial_b = bp_to_serials[anchor_b_key]
            if p_serial_b is not None:
                bonds.append((prev_o3_serial, p_serial_b))


# ── Crossover backbone relaxation ────────────────────────────────────────────
# At a crossover the O3'(source helix)→P(dest helix) bond spans a gap that
# is longer than the ideal O3'–P bond length (~0.161 nm).  Without adjustment
# the phosphate group atoms (P, OP1, OP2, O5') sit at their helix-geometry
# positions, which can cause severe inter-atomic clashes along the bridging
# segment — bad for MD simulations.
#
# Two relaxation modes (both adjust P, OP1, OP2, O5' only; sugars untouched):
#
#   'lerp'    — proportional linear interpolation between the fixed anchors
#               O3'(source) and C5'(dest).  Guaranteed smooth but ignores
#               real backbone geometry (bond angles will be 180°).
#
#   'natural' — P placed at the ideal O3'–P bond length along O3'→C5';
#               O5' placed at ideal P–O5' length along P→C5'.
#               OP1/OP2 placed using a tetrahedral arrangement around P
#               perpendicular to the O3'–P–O5' plane.  Bond lengths are
#               ideal; bond angles will vary with the crossover geometry.

# Ideal B-DNA backbone bond lengths (nm), from CHARMM36 equilibrium values
_XOVER_O3P  = 0.1608   # O3′–P
_XOVER_PO5  = 0.1602   # P–O5′
_XOVER_O5C5 = 0.1440   # O5′–C5′
_XOVER_C5C4 = 0.1524   # C5′–C4′  (sugar ring; C4′ is the lerp far anchor)
_XOVER_POP  = 0.1485   # P–OP1 / P–OP2 (non-bridging phosphate oxygens)


def _adjust_crossover_backbones(
    atoms: list,
    bonds: list[tuple[int, int]],
    mode: str,
) -> None:
    """
    Reposition P, OP1, OP2, O5' at every crossover junction (in-place).
    No-op if *mode* is not 'lerp' or 'natural'.
    """
    if mode not in ('lerp', 'natural'):
        return

    by_serial: dict[int, object] = {a.serial: a for a in atoms}

    adj: dict[int, list[int]] = {}
    for i, j in bonds:
        adj.setdefault(i, []).append(j)
        adj.setdefault(j, []).append(i)

    def _pos(atom) -> _np.ndarray:
        return _np.array([atom.x, atom.y, atom.z], dtype=_np.float64)

    def _set(atom, p: _np.ndarray) -> None:
        atom.x, atom.y, atom.z = float(p[0]), float(p[1]), float(p[2])

    def _nbr(atom, name: str, same_res: bool = False):
        """First neighbor with the given atom name."""
        for s in adj.get(atom.serial, []):
            n = by_serial[s]
            if n.name != name:
                continue
            if same_res and (n.seq_num != atom.seq_num or n.chain_id != atom.chain_id):
                continue
            return n
        return None

    for i, j in bonds:
        a, b = by_serial[i], by_serial[j]
        # Find O3'→P bonds that need backbone relaxation:
        #   1. Cross-helix bonds (source and dest on different real helices).
        #   2. Bonds where O3' is on an extra-base residue (__xb_ helix) —
        #      this covers consecutive extra-base O3'→P bonds that share the
        #      same synthetic helix_id and would otherwise be skipped.
        def _needs_relax(o3, p):
            return o3.helix_id != p.helix_id or o3.helix_id.startswith('__xb_')
        if   a.name == "O3'" and b.name == "P" and _needs_relax(a, b):
            o3_a, p_a = a, b
        elif b.name == "O3'" and a.name == "P" and _needs_relax(b, a):
            o3_a, p_a = b, a
        else:
            continue

        o5_a  = _nbr(p_a,  "O5'", same_res=True)
        if o5_a is None:
            continue
        c5_a  = _nbr(o5_a, "C5'")
        if c5_a is None:
            continue
        c4_a  = _nbr(c5_a, "C4'")   # lerp far anchor (stays fixed)
        op1_a = _nbr(p_a, "OP1")
        op2_a = _nbr(p_a, "OP2")

        pos_o3 = _pos(o3_a)
        pos_c5 = _pos(c5_a)

        if mode == 'lerp':
            # ── Proportional linear interpolation (O3' → C4') ────────────────
            # Anchor: O3'(source fixed), C4'(dest fixed — ring carbon).
            # Interpolate P, OP1/OP2, O5', C5' along the O3'→C4' line.
            pos_c4  = _pos(c4_a) if c4_a is not None else pos_c5
            gap     = pos_c4 - pos_o3
            dist    = float(_np.linalg.norm(gap))
            if dist < 1e-9:
                continue
            d_hat   = gap / dist

            total   = _XOVER_O3P + _XOVER_PO5 + _XOVER_O5C5 + _XOVER_C5C4
            pos_p   = pos_o3 + (_XOVER_O3P / total) * gap
            pos_o5  = pos_o3 + ((_XOVER_O3P + _XOVER_PO5) / total) * gap
            pos_c5_new = pos_o3 + ((_XOVER_O3P + _XOVER_PO5 + _XOVER_O5C5) / total) * gap

            # OP1/OP2: equal-and-opposite perpendicular offset from P
            ref  = _np.array([0., 0., 1.]) if abs(d_hat[2]) < 0.9 \
                   else _np.array([1., 0., 0.])
            perp = _np.cross(d_hat, ref)
            perp /= _np.linalg.norm(perp)
            pos_op1 = pos_p + perp * _XOVER_POP
            pos_op2 = pos_p - perp * _XOVER_POP

            _set(p_a,   pos_p)
            _set(o5_a,  pos_o5)
            _set(c5_a,  pos_c5_new)
            if op1_a is not None: _set(op1_a, pos_op1)
            if op2_a is not None: _set(op2_a, pos_op2)
            continue

        # 'natural' uses C5' as anchor (not C4'); compute gap from O3' to C5'
        gap   = pos_c5 - pos_o3
        dist  = float(_np.linalg.norm(gap))
        if dist < 1e-9:
            continue
        d_hat = gap / dist

        # ── Ideal bond lengths + tetrahedral OP1/OP2 ─────────────────────────
        # P: exact O3'–P bond length along O3'→C5' direction
        pos_p  = pos_o3 + d_hat * _XOVER_O3P

        # O5': exact P–O5' bond length along P→C5' direction
        d_o5   = pos_c5 - pos_p
        n_o5   = float(_np.linalg.norm(d_o5))
        d_o5   = d_o5 / n_o5 if n_o5 > 1e-9 else d_hat
        pos_o5 = pos_p + d_o5 * _XOVER_PO5

        # OP1/OP2: complete the tetrahedron around P.
        # Normal to the O3'–P–O5' plane; OP1/OP2 symmetric about it.
        d_o3f  = (pos_o3 - pos_p) / _XOVER_O3P        # unit vec P→O3'
        d_o5f  = d_o5                                  # unit vec P→O5'
        normal = _np.cross(d_o3f, d_o5f)
        nn     = float(_np.linalg.norm(normal))
        if nn < 1e-6:
            # Degenerate (O3', P, O5' collinear) — fall back to a perp ref
            ref    = _np.array([0., 1., 0.]) if abs(d_o3f[1]) < 0.9 \
                     else _np.array([1., 0., 0.])
            normal = _np.cross(d_o3f, ref)
            normal /= float(_np.linalg.norm(normal))
        else:
            normal /= nn

        # Anti-bisector: direction away from backbone chain (outward)
        anti   = -(d_o3f + d_o5f)
        an     = float(_np.linalg.norm(anti))
        anti   = anti / an if an > 1e-9 else normal

        # OP1/OP2 at ≈109.5° from each bridging oxygen — blend anti + ±normal
        pos_op1 = pos_p + _XOVER_POP * _normalise(anti + normal)
        pos_op2 = pos_p + _XOVER_POP * _normalise(anti - normal)

        _set(p_a,  pos_p)
        _set(o5_a, pos_o5)
        if op1_a is not None: _set(op1_a, pos_op1)
        if op2_a is not None: _set(op2_a, pos_op2)


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
