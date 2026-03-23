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
Sugar + phosphate: derived from ideal B-DNA C2′-endo pucker geometry
(Arnott & Hukins 1972, Olson et al. 2001) and CHARMM36 bond lengths.
Base rings: canonical aromatic ring geometry (bond length 0.137 nm,
120° angles for 6-ring, 108° for 5-ring) with substitution positions
from CHARMM36 nucleic acid topology (top_all36_na.rtf).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
    # Phosphate group
    ("P",    "P",  0.000,  0.000,  0.000),
    ("OP1",  "O", -0.063,  0.121,  0.000),
    ("OP2",  "O", -0.063, -0.121,  0.000),
    # 5′ side
    ("O5'",  "O",  0.089,  0.000,  0.159),
    ("C5'",  "C",  0.163,  0.000,  0.068),
    # Main sugar ring
    ("C4'",  "C",  0.220, -0.046, -0.019),
    ("O4'",  "O",  0.204, -0.160, -0.055),
    ("C3'",  "C",  0.206,  0.021, -0.153),
    # 3′ connector (links to next residue's P)
    ("O3'",  "O",  0.136,  0.020, -0.292),
    # C2′-endo pucker
    ("C2'",  "C",  0.253,  0.108, -0.063),
    # Glycosidic carbon — base attaches here
    ("C1'",  "C",  0.292,  0.000, -0.021),
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

# N9 position for purines; N1 for pyrimidines (relative to P origin).
# Derived as C1′ + 0.146 nm along e_n (glycosidic bond length).
_GLYCOSIDIC_N = (0.438, 0.000, -0.021)

# ── Base ring definitions ──────────────────────────────────────────────────────
# All positions relative to P origin (same local frame as sugar).
# 6-membered rings: regular hexagon radius 0.137 nm; N1/N9 at 180° (smallest n).
# Purines: fused 5+6 ring.  5-ring circumradius 0.116 nm.

def _hex_vertex(cx: float, cy: float, angle_deg: float) -> tuple[float, float]:
    """One vertex of a regular hexagon (radius 0.137 nm) at angle_deg."""
    r = 0.137
    a = _np.radians(angle_deg)
    return (cx + r * _np.cos(a), cy + r * _np.sin(a))


def _pent_vertex(cx: float, cy: float, angle_deg: float) -> tuple[float, float]:
    """One vertex of a regular pentagon (radius 0.116 nm) at angle_deg."""
    r = 0.116
    a = _np.radians(angle_deg)
    return (cx + r * _np.cos(a), cy + r * _np.sin(a))


# ── Thymine (DT) ──────────────────────────────────────────────────────────────
# 6-membered ring: N1-C2-N3-C4-C5-C6.
# Ring center = glycosidic N1 + (0.137, 0, 0) = (0.575, 0, -0.021).
# N1 at 180°.  Carbonyl O2 on C2, O4 on C4, methyl C7 on C5.

def _make_dt() -> tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]:
    cx, cy, z = 0.575, 0.000, -0.021
    N1 = _hex_vertex(cx, cy, 180); C2 = _hex_vertex(cx, cy, 240)
    N3 = _hex_vertex(cx, cy, 300); C4 = _hex_vertex(cx, cy,   0)
    C5 = _hex_vertex(cx, cy,  60); C6 = _hex_vertex(cx, cy, 120)
    # substituents: perpendicular outward from ring center
    O2 = (C2[0] + 0.122 * _np.cos(_np.radians(240)), C2[1] + 0.122 * _np.sin(_np.radians(240)))
    O4 = (C4[0] + 0.122,                            C4[1])
    C7 = (C5[0] + 0.150 * _np.cos(_np.radians(60)),   C5[1] + 0.150 * _np.sin(_np.radians(60)))

    atoms: tuple[_AtomDef, ...] = (
        ("N1", "N", N1[0], N1[1], z),
        ("C2", "C", C2[0], C2[1], z),
        ("N3", "N", N3[0], N3[1], z),
        ("C4", "C", C4[0], C4[1], z),
        ("C5", "C", C5[0], C5[1], z),
        ("C6", "C", C6[0], C6[1], z),
        ("O2", "O", O2[0], O2[1], z),
        ("O4", "O", O4[0], O4[1], z),
        ("C7", "C", C7[0], C7[1], z),  # methyl carbon
    )
    bonds: tuple[tuple[str, str], ...] = (
        ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
        ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
        ("C2",  "O2"), ("C4", "O4"), ("C5", "C7"),
    )
    return atoms, bonds


# ── Cytosine (DC) ─────────────────────────────────────────────────────────────
# Same ring as thymine; N4-amino at C4 instead of O4; no methyl at C5.

def _make_dc() -> tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]:
    cx, cy, z = 0.575, 0.000, -0.021
    N1 = _hex_vertex(cx, cy, 180); C2 = _hex_vertex(cx, cy, 240)
    N3 = _hex_vertex(cx, cy, 300); C4 = _hex_vertex(cx, cy,   0)
    C5 = _hex_vertex(cx, cy,  60); C6 = _hex_vertex(cx, cy, 120)
    O2 = (C2[0] + 0.122 * _np.cos(_np.radians(240)), C2[1] + 0.122 * _np.sin(_np.radians(240)))
    N4 = (C4[0] + 0.136, C4[1])

    atoms: tuple[_AtomDef, ...] = (
        ("N1", "N", N1[0], N1[1], z),
        ("C2", "C", C2[0], C2[1], z),
        ("N3", "N", N3[0], N3[1], z),
        ("C4", "C", C4[0], C4[1], z),
        ("C5", "C", C5[0], C5[1], z),
        ("C6", "C", C6[0], C6[1], z),
        ("O2", "O", O2[0], O2[1], z),
        ("N4", "N", N4[0], N4[1], z),
    )
    bonds: tuple[tuple[str, str], ...] = (
        ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
        ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
        ("C2",  "O2"), ("C4", "N4"),
    )
    return atoms, bonds


# ── Adenine (DA) ──────────────────────────────────────────────────────────────
# Purine: fused 5-ring (N9-C8-N7-C5-C4) + 6-ring (C4-N3-C2-N1-C6-C5).
# 5-ring center at N9 + (0.116, 0, 0) = (0.554, 0, -0.021).
# N9 at 180° of 5-ring.  6-ring center derived from shared C4-C5 edge.
# Amino N6 on C6.

def _make_da() -> tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]:
    z = -0.021
    # 5-ring: N9 at 180°, going clockwise → C8(252°), N7(324°), C5(36°), C4(108°)
    p5x, p5y = 0.554, 0.000
    N9 = _pent_vertex(p5x, p5y, 180)
    C8 = _pent_vertex(p5x, p5y, 252)
    N7 = _pent_vertex(p5x, p5y, 324)
    C5 = _pent_vertex(p5x, p5y,  36)
    C4 = _pent_vertex(p5x, p5y, 108)
    # 6-ring center: on opposite side of C4-C5 edge from 5-ring center
    mx = (C4[0] + C5[0]) / 2;  my = (C4[1] + C5[1]) / 2
    # direction from 5-ring center to midpoint, then reflect
    dx = mx - p5x;  dy = my - p5y
    norm = _np.sqrt(dx*dx + dy*dy)
    p6x = mx + dx / norm * 0.119  # hexagon inradius
    p6y = my + dy / norm * 0.119
    # 6-ring vertex angles: find angles for C4 and C5, then space remaining 4 atoms
    a_C4 = _np.degrees(_np.arctan2(C4[1] - p6y, C4[0] - p6x))
    a_C5 = _np.degrees(_np.arctan2(C5[1] - p6y, C5[0] - p6x))
    # Remaining atoms at +60° steps from C4 going the same direction as C4→C5
    step = -60.0  # clockwise (C4→C5 going clockwise from top)
    a_N3 = a_C4 + step
    a_C2 = a_N3 + step
    a_N1 = a_C2 + step
    a_C6 = a_N1 + step
    N3 = _hex_vertex(p6x, p6y, a_N3)
    C2 = _hex_vertex(p6x, p6y, a_C2)
    N1 = _hex_vertex(p6x, p6y, a_N1)
    C6 = _hex_vertex(p6x, p6y, a_C6)
    # Amino N6 on C6, direction from 6-ring center outward at C6
    d6 = _np.array([C6[0] - p6x, C6[1] - p6y])
    d6 /= _np.linalg.norm(d6)
    N6 = (C6[0] + 0.136 * d6[0], C6[1] + 0.136 * d6[1])

    atoms: tuple[_AtomDef, ...] = (
        ("N9", "N", N9[0], N9[1], z),
        ("C8", "C", C8[0], C8[1], z),
        ("N7", "N", N7[0], N7[1], z),
        ("C5", "C", C5[0], C5[1], z),
        ("C4", "C", C4[0], C4[1], z),
        ("N3", "N", N3[0], N3[1], z),
        ("C2", "C", C2[0], C2[1], z),
        ("N1", "N", N1[0], N1[1], z),
        ("C6", "C", C6[0], C6[1], z),
        ("N6", "N", N6[0], N6[1], z),
    )
    bonds: tuple[tuple[str, str], ...] = (
        ("C1'", "N9"),
        ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
        ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
        ("C6",  "N6"),
    )
    return atoms, bonds


# ── Guanine (DG) ──────────────────────────────────────────────────────────────
# Same purine scaffold as adenine; O6 on C6 (instead of N6), N2-amino on C2.

def _make_dg() -> tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]:
    da_atoms, da_bonds = _make_da()
    # Reuse DA coordinates; replace N6 with O6 and add N2 on C2
    # Build lookup for atom positions
    pos = {name: (n, y, z_val) for name, _, n, y, z_val in da_atoms}
    z = -0.021

    # Replace N6 (amino on C6) with O6 (carbonyl)
    new_atoms = []
    for entry in da_atoms:
        name, elem, n, y, z_val = entry
        if name == "N6":
            new_atoms.append(("O6", "O", n, y, z_val))
        else:
            new_atoms.append(entry)

    # N2: amino on C2.  Find 6-ring center and C2 position.
    p5x, p5y = 0.554, 0.000
    C4 = _pent_vertex(p5x, p5y, 108)
    C5 = _pent_vertex(p5x, p5y,  36)
    mx = (C4[0] + C5[0]) / 2;  my = (C4[1] + C5[1]) / 2
    dx = mx - p5x;  dy = my - p5y
    norm = _np.sqrt(dx*dx + dy*dy)
    p6x = mx + dx / norm * 0.119
    p6y = my + dy / norm * 0.119
    a_C4 = _np.degrees(_np.arctan2(C4[1] - p6y, C4[0] - p6x))
    a_C2 = a_C4 - 120.0  # two steps from C4
    C2 = _hex_vertex(p6x, p6y, a_C2)
    d2 = _np.array([C2[0] - p6x, C2[1] - p6y])
    d2 /= _np.linalg.norm(d2)
    N2 = (C2[0] + 0.136 * d2[0], C2[1] + 0.136 * d2[1])
    new_atoms.append(("N2", "N", N2[0], N2[1], z))

    bonds = tuple(
        ("O6" if a == "N6" else a, b) if a == "N6" else (a, "O6" if b == "N6" else b)
        for a, b in da_bonds
    )
    # Filter out N6 bond (now O6) and add N2 bond
    bonds = tuple(
        (("C6", "O6") if (a, b) == ("C6", "N6") else (a, b))
        for a, b in bonds
    ) + (("C2", "N2"),)

    return tuple(new_atoms), bonds


# ── Assemble template dict ─────────────────────────────────────────────────────

_DT_BASE, _DT_BONDS = _make_dt()
_DC_BASE, _DC_BONDS = _make_dc()
_DA_BASE, _DA_BONDS = _make_da()
_DG_BASE, _DG_BONDS = _make_dg()

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


# ── Frame builder ─────────────────────────────────────────────────────────────


def _atom_frame(
    nuc_pos: NucleotidePosition,
    direction: Direction,
) -> tuple[_np.ndarray, _np.ndarray]:
    """
    Returns (origin, R) where:
      origin  = backbone bead world position (template origin)
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
    R = _np.column_stack([e_n, e_y, e_z])
    return nuc_pos.position.copy(), R


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


def build_atomistic_model(design: Design) -> AtomisticModel:
    """
    Build the heavy-atom model for the entire design.

    Returns an AtomisticModel with a flat atom list and a bond list (0-based
    serial pairs).  Serial numbers are 0-based to match the list index.

    Bond coverage:
    - All intra-residue bonds (sugar + base ring)
    - Inter-residue backbone bonds: O3′(i) → P(i+1) for consecutive bp on the
      same strand segment (direction-aware; skips across crossovers/nicks).
    """
    seq_map = _build_sequence_map(design)

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

                origin, R = _atom_frame(nuc_pos, direction)

                # ── Sugar + phosphate atoms ───────────────────────────────
                sugar_name_to_serial: dict[str, int] = {}
                for atom_name, element, n, y, z_local in _SUGAR:
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
