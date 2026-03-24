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
    # Crystallographic B-DNA coordinates derived from Drew-Dickerson dodecamer
    # (dd12_na.pdb, chain A) transformed into NADOC local frame:
    #   origin = P,  e_n = base_normal,  e_z = 3′→5′,  e_y = cross(e_z, e_n)
    #
    # Ring atoms (C4′ onward) are shifted by +0.1689 nm in z relative to the
    # raw crystallographic values.  Reason: NADOC places both FORWARD and REVERSE
    # strand P atoms at the same axial position (bp_index × rise), whereas in
    # real B-DNA the two P atoms are ~3.4 Å apart axially.  Without the shift,
    # paired bases are 3.4 Å out-of-plane; the shift brings C1′ and all base
    # atoms to z = 0, making them coplanar with P and thus with the paired strand.
    # All intra-ring bond lengths are preserved; only C5′→C4′ changes (~10%).
    ("P",   "P",  0.0000,  0.0000,  0.0000),
    ("OP1", "O", -0.0770,  0.1257, -0.0141),
    ("OP2", "O", -0.0501, -0.1152, -0.0782),
    ("O5'", "O",  0.1538,  0.0265, -0.0353),
    ("C5'", "C",  0.2371,  0.0928,  0.0615),
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
