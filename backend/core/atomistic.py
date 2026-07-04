"""
All-atom model builder — Phase AA.

Derives heavy-atom 3D positions for every nucleotide in a Design by
rigidly transforming crystallographic nucleotide templates into the local
frame already computed by geometry.py.  No external converter tools are
used.

Local frame convention (per nucleotide)
────────────────────────────────────────
  origin  = corrected P position (_ATOMISTIC_P_RADIUS from helix axis)
  e_n     = −e_radial            (inward radial — from P toward helix axis)
  e_z     = axis_tangent         (3′→5′ unit vector for this strand:
                                  −axis_tangent for FORWARD,
                                  +axis_tangent for REVERSE)
  e_y     = cross(e_z, e_n)      (in-plane tangential, right-hand completion)

All template coordinates are (n, y, z) in nm.  Positive n = toward base
(inward toward helix axis and partner strand).  The z-axis flip for
REVERSE strands automatically mirrors the sugar chirality so O3′ connects
in the correct 3′ direction for both strands.

Template sources
────────────────
All heavy-atom coordinates are extracted from the B-DNA crystal structure
1zew.pdb (2.25 Å, 10 bp self-complementary duplex CCTCTAGAGG, chains A+B).
Inner residues only (terminals excluded).  C2′-endo/C2′-exo pucker
geometry is preserved from the crystal data.
  • SUGAR: chain A residue 5 (DT), single reference residue.
  • FWD BASE: chain A inner residues A:3–A:8, averaged by residue type.
  • REV BASE: chain B inner residues B:13–B:18, averaged by residue type.
All templates use the production radial frame (e_n = −e_radial, not cross-strand
C1′→C1′), ensuring consistency between SUGAR, FWD BASE, and REV BASE.
Template origin is at the P atom (clamped to _ATOMISTIC_P_RADIUS); C1′ z = 0.

Extraction tool: scripts/extract_all_templates.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import functools as _functools
import hashlib as _hashlib
import json as _json
import math as _math
import numpy as _np
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor

from backend.core.atomistic_helpers import (
    _arc_bow_dir,
    _arc_ctrl_pt,
    _bezier_pt,
    _bezier_tan,
    _lerp,
    _normalise,
)
from backend.core.atomistic_minimisers import (
    _atom_pos,
    _interpolate_backbone_bridge,
    _minimize_1_extra_base,
    _minimize_2_extra_base,
    _minimize_3_extra_base,
    _minimize_backbone_bridge,
    _set_atom_pos,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import (
    NucleotidePosition,
    nucleotide_positions,
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.models import Design, Direction, Strand, StrandType
from backend.core.sequences import domain_bp_range


# ── Element VDW radii (nm, Bondi 1964) ───────────────────────────────────────

VDW_RADIUS: dict[str, float] = {
    "P": 0.190,
    "C": 0.170,
    "N": 0.155,
    "O": 0.140,
    # Additional elements common in proteins / cofactors (for protein rendering).
    "S": 0.180,
    "H": 0.120,
    "Se": 0.190,
    "Fe": 0.160,
    "Zn": 0.139,
    "Mg": 0.173,
    "Mn": 0.161,
    "Ca": 0.231,
}

# ── CPK colours (hex int) ─────────────────────────────────────────────────────

CPK_COLOR: dict[str, int] = {
    "P": 0xFF8C00,   # orange
    "C": 0x505050,   # dark grey
    "N": 0x3050F8,   # blue
    "O": 0xFF0D0D,   # red
    "S": 0xFFFF30,   # yellow
    "H": 0xFFFFFF,   # white
    "Se": 0xFFA100,
    "Fe": 0xE06633,
    "Zn": 0x7D80B0,
    "Mg": 0x8AFF00,
    "Mn": 0x9C7AC7,
    "Ca": 0x3DFF00,
}

# Fallback for any element not listed above (rendered grey at a mid radius).
DEFAULT_VDW_RADIUS: float = 0.160
DEFAULT_CPK_COLOR: int = 0x808080

# ── Template type alias ───────────────────────────────────────────────────────
# Each entry: (atom_name, element, n_nm, y_nm, z_nm)
_AtomDef = tuple[str, str, float, float, float]

# ── Sugar-phosphate backbone (common to all four residues) ────────────────────
# Origin at P.  C2′-endo pucker.  Connectivity:  …O3′(i-1)→P→O5′→C5′→C4′→C3′→O3′(i)→…
#                                                               ↓
#                                                              O4′→C1′→(base)
#                                                              C2′↗

_SUGAR: tuple[_AtomDef, ...] = (
    # From 1ZEW chain A residue 5 (DT) in the NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).
    # Frame: origin = backbone bead at _ATOMISTIC_P_RADIUS, e_n = −e_radial, e_z = −axis_tangent.
    # C1′ z = 0 convention applied.
    # P and O3′ adjusted for inter-residue C3′(N)–O3′(N)–P(N+1) angle = 119.35°:
    #   ΔP = (−0.062, +0.017, −0.012) nm — minimal shift along the C3′→P(N+1) direction.
    #   O3′ re-derived on the intersection circle (r_C3O3=1.52Å, r_O3P=1.61Å), biased to crystal.
    # OP1/OP2 shifted by the same ΔP to restore crystal geometry relative to corrected P:
    #   P→OP1 = 1.474 Å, P→OP2 = 1.494 Å, OP1–P–OP2 = 119.7°.
    ("P",   "P", -0.1020,  0.1588,  0.2560),
    ("OP1", "O", -0.2263,  0.1547,  0.3352),
    ("OP2", "O", -0.0584,  0.0376,  0.1803),
    ("O5'", "O", -0.0629,  0.2645,  0.1684),
    ("C5'", "C", -0.0543,  0.4005,  0.2139),
    ("C4'", "C",  0.0331,  0.4838,  0.1220),
    ("O4'", "O",  0.1733,  0.4481,  0.1316),
    ("C3'", "C", -0.0013,  0.4772, -0.0269),
    ("O3'", "O", -0.0605,  0.5756, -0.1253),
    ("C2'", "C",  0.1079,  0.3896, -0.0850),
    ("C1'", "C",  0.2248,  0.4334,  0.0000),
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

# ── Base heavy-atom coordinates (1ZEW, NADOC synthetic frame) ──────────────────
# NADOC synthetic frame: origin = backbone bead at _ATOMISTIC_P_RADIUS = 0.886 nm,
# e_n = −e_radial (inward from P), e_z = −axis_tangent (FWD, 3′→5′).
# Extracted using NADOC 34.3°/bp, 0.334 nm/bp helix; averaged per residue type.
# C1′ z = 0 convention applied.

# ── Thymine (DT) ──────────────────────────────────────────────────────────────

_DT_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A inner DT residues A:3, A:5.
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation −9.393° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N",  0.3323,  0.3376, -0.0216),
    ("C2", "C",  0.4595,  0.3874, -0.0278),
    ("O2", "O",  0.4844,  0.5044, -0.0154),
    ("N3", "N",  0.5569,  0.2956, -0.0491),
    ("C4", "C",  0.5402,  0.1621, -0.0638),
    ("O4", "O",  0.6374,  0.0912, -0.0824),
    ("C5", "C",  0.4043,  0.1167, -0.0557),
    ("C6", "C",  0.3080,  0.2053, -0.0356),
    ("C7", "C",  0.3775, -0.0261, -0.0697),
)

_DT_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "O4"), ("C5", "C7"),
)

# ── Cytosine (DC) ─────────────────────────────────────────────────────────────

_DC_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A DC residue A:4 (single residue, only DC available).
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation −13.031° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N",  0.3036,  0.3102, -0.0184),
    ("C2", "C",  0.4417,  0.3222, -0.0336),
    ("O2", "O",  0.4927,  0.4348, -0.0267),
    ("N3", "N",  0.5162,  0.2113, -0.0550),
    ("C4", "C",  0.4574,  0.0919, -0.0605),
    ("N4", "N",  0.5344, -0.0146, -0.0837),
    ("C5", "C",  0.3168,  0.0765, -0.0426),
    ("C6", "C",  0.2444,  0.1874, -0.0220),
)

_DC_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"), ("N1", "C2"), ("C2", "N3"), ("N3", "C4"),
    ("C4",  "C5"), ("C5", "C6"), ("C6", "N1"),
    ("C2",  "O2"), ("C4", "N4"),
)

# ── Adenine (DA) ──────────────────────────────────────────────────────────────

_DA_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A inner DA residues A:6, A:8.
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation +2.255° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N",  0.3294,  0.3340, -0.0197),
    ("C8", "C",  0.3150,  0.1998, -0.0436),
    ("N7", "N",  0.4280,  0.1362, -0.0562),
    ("C5", "C",  0.5236,  0.2354, -0.0393),
    ("C4", "C",  0.4641,  0.3576, -0.0173),
    ("N3", "N",  0.5259,  0.4751,  0.0026),
    ("C2", "C",  0.6577,  0.4597, -0.0013),
    ("N1", "N",  0.7290,  0.3488, -0.0211),
    ("C6", "C",  0.6635,  0.2325, -0.0405),
    ("N6", "N",  0.7341,  0.1216, -0.0589),
)

_DA_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
    ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
    ("C6",  "N6"),
)

# ── Guanine (DG) ──────────────────────────────────────────────────────────────

_DG_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A DG residue A:7 (single residue, only DG available).
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation +16.962° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N",  0.3499,  0.3595,  0.0046),
    ("C8", "C",  0.3675,  0.2235,  0.0094),
    ("N7", "N",  0.4934,  0.1882,  0.0109),
    ("C5", "C",  0.5625,  0.3088,  0.0071),
    ("C4", "C",  0.4750,  0.4149,  0.0034),
    ("N3", "N",  0.5027,  0.5468, -0.0009),
    ("C2", "C",  0.6323,  0.5701, -0.0006),
    ("N2", "N",  0.6768,  0.6966, -0.0027),
    ("N1", "N",  0.7279,  0.4717,  0.0024),
    ("C6", "C",  0.7020,  0.3352,  0.0063),
    ("O6", "O",  0.7954,  0.2550,  0.0088),
)

_DG_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9",  "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"), ("C4", "N9"),  # 5-ring
    ("C4",  "N3"), ("N3", "C2"), ("C2", "N1"), ("N1", "C6"), ("C6", "C5"),  # 6-ring
    ("C6",  "O6"), ("C2", "N2"),
)

# ── REVERSE strand base templates (chain B, 1ZEW inner residues 13–18) ──────────
# Extracted from 1ZEW chain B using the NADOC synthetic REV frame.
# _atom_frame(direction=REVERSE) places the REV origin at FWD_partner_azimuth + 208.2°
# (canonical P-P correction; 1ZEW Holliday-junction P-P angles deviate ±10° from 208.2°).
# C1′ z = 0 convention applied.
#
# Available inner chain B residues by type:
#   DT: B:13, B:15   DC: B:14   DA: B:16, B:18   DG: B:17

_DT_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B inner DT residues B:13, B:15.
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation −13.591° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N",  0.3496,  0.3665, -0.0261),
    ("C2", "C",  0.4634,  0.4436, -0.0334),
    ("O2", "O",  0.4649,  0.5642, -0.0229),
    ("N3", "N",  0.5762,  0.3735, -0.0534),
    ("C4", "C",  0.5866,  0.2378, -0.0667),
    ("O4", "O",  0.6958,  0.1884, -0.0818),
    ("C5", "C",  0.4633,  0.1636, -0.0602),
    ("C6", "C",  0.3525,  0.2311, -0.0410),
    ("C7", "C",  0.4647,  0.0158, -0.0747),
)

_DC_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B DC residue B:14 (single residue, only DC available).
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation −36.459° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N",  0.3085,  0.3159, -0.0303),
    ("C2", "C",  0.4427,  0.3362, -0.0634),
    ("O2", "O",  0.4866,  0.4517, -0.0667),
    ("N3", "N",  0.5210,  0.2297, -0.0911),
    ("C4", "C",  0.4700,  0.1062, -0.0866),
    ("N4", "N",  0.5510,  0.0041, -0.1146),
    ("C5", "C",  0.3335,  0.0825, -0.0536),
    ("C6", "C",  0.2568,  0.1893, -0.0265),
)

_DA_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B inner DA residues B:16, B:18.
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation +0.997° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N",  0.3501,  0.3637, -0.0302),
    ("C8", "C",  0.3649,  0.2310, -0.0607),
    ("N7", "N",  0.4892,  0.1941, -0.0782),
    ("C5", "C",  0.5614,  0.3104, -0.0588),
    ("C4", "C",  0.4769,  0.4161, -0.0309),
    ("N3", "N",  0.5126,  0.5431, -0.0078),
    ("C2", "C",  0.6452,  0.5565, -0.0150),
    ("N1", "N",  0.7387,  0.4644, -0.0400),
    ("C6", "C",  0.6995,  0.3375, -0.0624),
    ("N6", "N",  0.7927,  0.2449, -0.0861),
)

_DG_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B DG residue B:17 (single residue, only DG available).
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation −10.173° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N",  0.3494,  0.3590,  0.0079),
    ("C8", "C",  0.3648,  0.2232, -0.0015),
    ("N7", "N",  0.4886,  0.1847,  0.0126),
    ("C5", "C",  0.5591,  0.3026,  0.0319),
    ("C4", "C",  0.4744,  0.4109,  0.0288),
    ("N3", "N",  0.5044,  0.5416,  0.0434),
    ("C2", "C",  0.6339,  0.5607,  0.0621),
    ("N2", "N",  0.6814,  0.6847,  0.0781),
    ("N1", "N",  0.7261,  0.4595,  0.0666),
    ("C6", "C",  0.6973,  0.3244,  0.0523),
    ("O6", "O",  0.7880,  0.2414,  0.0588),
)

# ── Assemble template dicts ────────────────────────────────────────────────────

# BASE_TEMPLATES[residue] = (atom_defs, bond_pairs) — FORWARD strand
BASE_TEMPLATES: dict[str, tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]] = {
    "DA": (_DA_BASE, _DA_BONDS),
    "DT": (_DT_BASE, _DT_BONDS),
    "DG": (_DG_BASE, _DG_BONDS),
    "DC": (_DC_BASE, _DC_BONDS),
}

# BASE_TEMPLATES_REV[residue] = (atom_defs, bond_pairs) — REVERSE strand
# Extracted from 1ZEW chain B; use when direction == Direction.REVERSE.
BASE_TEMPLATES_REV: dict[str, tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]] = {
    "DA": (_DA_BASE_REV, _DA_BONDS),
    "DT": (_DT_BASE_REV, _DT_BONDS),
    "DG": (_DG_BASE_REV, _DG_BONDS),
    "DC": (_DC_BASE_REV, _DC_BONDS),
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
    strand_id:    str
    helix_id:     str
    bp_index:     int
    direction:    str        # "FORWARD" | "REVERSE"
    is_modified:  bool  = False
    # Extra-crossover-base interpolation (empty / 0.0 for regular nucleotides)
    aux_helix_id: str   = ""   # destination helix for extra-base lerp during Q expansion
    aux_t:        float = 0.0  # lerp weight 0→1 (src helix → aux_helix_id)
    # Extra-crossover-base identity (None for regular nucleotides).  The stored
    # helix_id/bp_index/direction stay the SOURCE nucleotide's key (so the topology
    # writers are unchanged); these let the relaxed-display reconstruction and the MD
    # P-atom mapping address each insert as ``("__xb__", crossover_id, extra_base_k)``.
    crossover_id: Optional[str] = None
    extra_base_k: Optional[int] = None


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
                aux_helix_id=a.aux_helix_id,
                aux_t=a.aux_t,
                crossover_id=a.crossover_id,
                extra_base_k=a.extra_base_k,
            ))
        for i, j in model.bonds:
            bonds.append((i + offset, j + offset))
        offset += len(model.atoms)
    return AtomisticModel(atoms=atoms, bonds=bonds)


def atomistic_reference_topology_hash(design: Design) -> str:
    """Stable hash of design fields that affect atom identity or coordinates."""
    payload = design.model_dump(
        mode="json",
        exclude={
            "atomistic_reference",
            "metadata",
            "camera_poses",
            "animations",
            "loadouts",
            "active_loadout_id",
            "feature_log",
            "feature_log_cursor",
            "feature_log_sub_cursor",
        },
    )
    raw = _json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _hashlib.sha256(raw).hexdigest()


def atomistic_model_from_reference(
    design: Design,
    exclude_helix_ids: set[str] | None = None,
) -> AtomisticModel | None:
    """Return the persisted MD-derived atomistic reference, if usable.

    ``Design.atomistic_reference`` is optional and may be absent in older
    files.  When a caller asks to exclude helices, serials and bonds are
    compacted so the returned model remains valid.
    """
    ref = getattr(design, "atomistic_reference", None)
    if ref is None or not ref.atoms:
        return None
    if ref.topology_hash and ref.topology_hash != atomistic_reference_topology_hash(design):
        return None

    atoms: list[Atom] = []
    old_to_new: dict[int, int] = {}
    for ref_atom in ref.atoms:
        if exclude_helix_ids and ref_atom.helix_id in exclude_helix_ids:
            continue
        new_serial = len(atoms)
        old_to_new[int(ref_atom.serial)] = new_serial
        atoms.append(Atom(
            serial=new_serial,
            name=ref_atom.name,
            element=ref_atom.element,
            residue=ref_atom.residue,
            chain_id=ref_atom.chain_id,
            seq_num=ref_atom.seq_num,
            x=ref_atom.x,
            y=ref_atom.y,
            z=ref_atom.z,
            strand_id=ref_atom.strand_id,
            helix_id=ref_atom.helix_id,
            bp_index=ref_atom.bp_index,
            direction=ref_atom.direction,
            is_modified=ref_atom.is_modified,
            aux_helix_id=ref_atom.aux_helix_id,
            aux_t=ref_atom.aux_t,
            crossover_id=getattr(ref_atom, "crossover_id", None),
            extra_base_k=getattr(ref_atom, "extra_base_k", None),
        ))

    bonds: list[tuple[int, int]] = []
    for i, j in ref.bonds:
        ni = old_to_new.get(int(i))
        nj = old_to_new.get(int(j))
        if ni is not None and nj is not None:
            bonds.append((ni, nj))
    return AtomisticModel(atoms=atoms, bonds=bonds)


# ── Frame constants ───────────────────────────────────────────────────────────
# _FRAME_ROT_RAD cancels the +37.05° pre-compensation baked into the templates
# (both SUGAR and BASE_TEMPLATES).  Net effect = 0° rotation; kept so templates
# stay self-consistent without re-extraction.
_FRAME_ROT_RAD: float = -0.646577   # −37.05° (template pre-compensation cancel)

# The geometric layer places backbone beads at HELIX_RADIUS (1.0 nm).
# Correcting to _ATOMISTIC_P_RADIUS places the radial frame origin at the
# real P-to-axis distance measured from 1ZEW inner residues.
_ATOMISTIC_P_RADIUS: float = 0.886  # nm  (measured mean P-to-axis from 1ZEW inner residues)

# Real B-DNA P-P azimuthal separation (measured from 1ZEW inner residues): 208.2°.
# This is the angle going counterclockwise (CCW) from the FORWARD strand P to the
# REVERSE strand P at the same base-pair position.  The minor groove arc (CW from
# FWD to REV) is 360° − 208.2° = 151.8°.
#
# NADOC topology layer uses BDNA_MINOR_GROOVE_ANGLE_RAD = 150° but applies it in
# OPPOSITE directions for the two helix cell types (geometry.py):
#   FORWARD helix:  rev_angle = fwd_angle + 150°  (CCW 150°)  →  208.2° off by 58.2°
#   REVERSE helix:  rev_angle = fwd_angle − 150°  (= CCW 210°) →  208.2° off by  1.8°
#
# For the ATOMISTIC layer only, REVERSE strand P is rotated to the correct angle:
#   FORWARD helix: e_radial rotated +58.2° CCW → REV P lands at fwd+208.2°
#   REVERSE helix: e_radial rotated  −1.8° (CW) → REV P lands at fwd+208.2°
_ATOMISTIC_PP_SEP_RAD: float = _math.radians(208.2)          # 1ZEW empirical mean
_ATOMISTIC_TOPOLOGY_GROOVE_RAD: float = _math.radians(150.0) # topology-layer groove constant

# ── Atomistic phase offset ────────────────────────────────────────────────────
# Rigid-body rotation of every nucleotide about its helix axis, applied after
# all P azimuthal corrections.  Rotates e_radial (moving the frame origin and
# co-rotating e_n/e_y) so all atoms in the template orbit the axis as one body.
#
# Value calibrated by overlaying the atomistic model on the NADOC bead/slab
# representation: −32° aligns the backbone groove phase of the all-atom model
# with the coarse-grained model at phase_offset=0.
_ATOMISTIC_PHASE_OFFSET_RAD: float = _math.radians(-32.0)

_PHOSPHODIESTER_LINKER_CONTOUR_NM: float = 0.606  # C3'-O3'-P-O5'-C5' contour length

# ── Frame builder ─────────────────────────────────────────────────────────────


def _atom_frame(
    nuc_pos: NucleotidePosition,
    direction: Direction,
    axis_point: _np.ndarray | None = None,
    helix_direction: Direction | None = None,
) -> tuple[_np.ndarray, _np.ndarray]:
    """
    Returns (origin, R) where:
      origin  = world position of the template frame origin (at the atomistic P)
      R       = 3×3 rotation matrix mapping template (n,y,z) → world frame

    Frame axes
    ──────────
    e_n  = inward radial (from corrected P toward helix axis); falls back to
           base_normal when axis_point is unavailable.
    e_z  = −axis_tangent (FORWARD strand) or +axis_tangent (REVERSE strand) —
           the 3′→5′ template z-axis.  C1′ sits at z≈0 so the base-ring plane
           aligns with the slab face (slab face normal = axis_tangent).
    e_y  = cross(e_z, e_n) — right-hand completion, in-plane tangential.

    P azimuthal correction (REVERSE strand only)
    ────────────────────────────────────────────
    The topology layer places REVERSE strand backbone beads at angles that differ
    from real B-DNA (1ZEW measured P-P separation: 208.2° CCW from FWD to REV):
      FORWARD helix: topology uses fwd+150° → correct to fwd+208.2° (+58.2°).
      REVERSE helix: topology uses fwd−150° (= fwd+210°) → correct to fwd+208.2° (−1.8°).
    This correction is applied to e_radial before building the frame.

    Phase offset (_ATOMISTIC_PHASE_OFFSET_RAD = −32°)
    ──────────────────────────────────────────────────
    Rigid-body rotation of the whole nucleotide about the helix axis.  Applied
    by rotating e_radial around axis_tangent, which moves the frame origin (P)
    along the circle at _ATOMISTIC_P_RADIUS and co-rotates e_n/e_y.  All atoms
    maintain their mutual distances; the assembly orbits the helix axis as one body.
    Calibrated to align the all-atom backbone groove phase with the NADOC CG model.
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

    # Correct the REVERSE strand P azimuthal angle to the real B-DNA value (1ZEW: 208.2°).
    # FORWARD helix topology places REV P at fwd+150° (CCW); target fwd+208.2° → +58.2°.
    # REVERSE helix topology places REV P at fwd−150° (= fwd+210° CCW); target fwd+208.2° → −1.8°.
    if direction == Direction.REVERSE and e_radial is not None:
        delta = (
            _ATOMISTIC_PP_SEP_RAD - _ATOMISTIC_TOPOLOGY_GROOVE_RAD          # FWD helix: +58.2°
            if helix_direction == Direction.FORWARD
            else _ATOMISTIC_PP_SEP_RAD - (2 * _math.pi - _ATOMISTIC_TOPOLOGY_GROOVE_RAD)  # REV/None: −1.8°
        )
        if abs(delta) > 1e-9:
            ax = nuc_pos.axis_tangent
            cd, sd = _math.cos(delta), _math.sin(delta)
            bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
            e_radial = cd * e_radial + sd * _np.cross(ax, e_radial)
            bb = bb_axial + _ATOMISTIC_P_RADIUS * e_radial

    # Phase offset: rotate e_radial around the helix axis by _ATOMISTIC_PHASE_OFFSET_RAD.
    # Moves the frame origin (P) along the circle at _ATOMISTIC_P_RADIUS and co-rotates
    # e_n/e_y so the entire nucleotide orbits the axis as a rigid body.
    if e_radial is not None and abs(_ATOMISTIC_PHASE_OFFSET_RAD) > 1e-9:
        ax = nuc_pos.axis_tangent
        cc, ss = _math.cos(_ATOMISTIC_PHASE_OFFSET_RAD), _math.sin(_ATOMISTIC_PHASE_OFFSET_RAD)
        bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
        e_radial = cc * e_radial + ss * _np.cross(ax, e_radial)
        bb = bb_axial + _ATOMISTIC_P_RADIUS * e_radial

    # e_n: inward radial (toward helix axis).  e_radial-based is parity-symmetric
    # across FORWARD/REVERSE; base_normal fallback used only without axis_point.
    e_n = -e_radial if e_radial is not None else nuc_pos.base_normal
    # e_z: 3′→5′ direction so O5′ is at +z and O3′ at −z in the template, which
    # preserves D-deoxyribose chirality when the same template is used for both
    # strand directions.
    e_z = -nuc_pos.axis_tangent if direction == Direction.FORWARD else nuc_pos.axis_tangent
    e_y = _np.cross(e_z, e_n)
    norm = _np.linalg.norm(e_y)
    if norm < 1e-9:
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(_np.dot(e_n, fallback)) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        e_y = _np.cross(e_z, fallback)
        norm = _np.linalg.norm(e_y)
    e_y /= norm

    # Origin at the radial-corrected (and phase-shifted) backbone bead.
    origin = bb
    R = _np.column_stack([e_n, e_y, e_z])

    # Cancel template pre-compensation (+37.05° baked into all templates).
    c, s = _math.cos(_FRAME_ROT_RAD), _math.sin(_FRAME_ROT_RAD)
    R = R @ _np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])

    return origin, R


# ── Rigid-frame stamping from an oxDNA per-nucleotide frame ────────────────────
# For DISPLAY of a relaxed oxDNA structure (or a trajectory frame) each nucleotide
# is a rigid body with a full orientation frame (a1, a3 from the .dat, a2 = a3×a1).
# Rather than re-deriving the base orientation from position − axis_point (which
# amplifies the coarse-grained MC positional noise into a mesh of crossing,
# over-stretched backbone bonds), we stamp the all-atom template by the oxDNA frame
# directly: world = origin + R·local with  R = F·Q,  origin = backbone_site + F·c,
# where F = [a1 a2 a3] and (Q, c) is a single fixed calibration per
# (strand_direction, helix_is_forward) bucket.  This is exact and deterministic:
# no axis fitting, no smoothing, no seed-clash, and it covers every nucleotide.
#
# (Q, c) are derived EMPIRICALLY (never hand-derived — the locked _PHASE_* / frame
# constants are honored) by fitting, on a clean ideal duplex whose oxDNA frame is
# known, the constant that makes this placer reproduce build_atomistic_model's own
# (validated) atom placement to machine precision.  See _rigid_frame_calibration.

def _oxdna_frame_basis(
    cm_nm: _np.ndarray, a1: _np.ndarray, a3: _np.ndarray,
) -> tuple[_np.ndarray, _np.ndarray]:
    """Return (F, backbone_site) for an oxDNA nucleotide given its centre-of-mass
    (the .dat position) and the a1/a3 unit vectors.  a1 is orthonormalised against
    a3 (defensive — relaxed oxDNA frames are orthonormal to ~1e-6, but a stray drift
    must not skew the stamp), a2 = a3 × a1, F = [a1 | a2 | a3].  The backbone site
    is oxDNA's true phosphate position (CM is inward of it).  Used identically by
    the calibration fit and the runtime placer so the two stay self-consistent."""
    from backend.physics.oxdna_interface import oxdna_backbone_site
    a3 = a3 / (_np.linalg.norm(a3) + 1e-14)
    a1 = a1 - _np.dot(a1, a3) * a3
    a1 = a1 / (_np.linalg.norm(a1) + 1e-14)
    a2 = _np.cross(a3, a1)
    F = _np.column_stack([a1, a2, a3])
    return F, oxdna_backbone_site(cm_nm, a1, a3)


@_functools.lru_cache(maxsize=1)
def _rigid_frame_calibration() -> dict:
    """Fit the constant rigid transform (Q rotation, c offset) per
    (strand_direction, helix_is_forward) bucket that maps an oxDNA particle frame to
    the all-atom template stamping build_atomistic_model produces.

    Method (empirical, machine-precision):  build a clean ideal duplex (no
    crossovers / insertions) spanning all four buckets, write + read its oxDNA
    configuration so each nucleotide has a known (CM, a1, a3), and read its
    KNOWN-GOOD atom placement from build_atomistic_model(design).  For each
    nucleotide recover (R_kg, origin_kg) by Kabsch between the template-local atom
    coordinates and the built world coordinates, then  Q = Fᵀ·R_kg,
    c = Fᵀ·(origin_kg − backbone_site).  Q is residue-independent (the frame is set
    by the sugar-phosphate, not the base) and constant within a bucket; we average
    + re-orthonormalise (SVD).  The 4-bucket split mirrors _atom_frame's only
    direction branches (the REVERSE-strand P azimuthal correction differs for a
    FORWARD helix vs a REVERSE/None helix).  Asserts the per-nucleotide residual is
    negligible, so a silent calibration drift can never ship."""
    from backend.core.models import Helix, Strand, Domain, Vec3, Design, LatticeType
    from backend.core.design_geometry import _geometry_for_design
    from backend.physics.oxdna_interface import write_configuration, read_configuration_full
    import tempfile as _tempfile, os as _os

    L = 14
    rise = BDNA_RISE_PER_BP

    def _helix(idx: str, direction: Direction) -> Helix:
        return Helix(id=idx, direction=direction, length_bp=L, bp_start=0,
                     axis_start=Vec3(x=float(idx_x[idx]), y=0.0, z=0.0),
                     axis_end=Vec3(x=float(idx_x[idx]), y=0.0, z=L * rise))

    idx_x = {"h0": 0.0, "h1": 3.0}
    helices = [_helix("h0", Direction.FORWARD), _helix("h1", Direction.REVERSE)]
    strands: list[Strand] = []
    # One forward + one reverse single-domain strand on each helix → all 4 buckets.
    for hid in ("h0", "h1"):
        strands.append(Strand(id=f"{hid}_f", strand_type=StrandType.SCAFFOLD,
                              domains=[Domain(helix_id=hid, start_bp=0, end_bp=L - 1,
                                              direction=Direction.FORWARD)]))
        strands.append(Strand(id=f"{hid}_r", strand_type=StrandType.STAPLE,
                              domains=[Domain(helix_id=hid, start_bp=L - 1, end_bp=0,
                                              direction=Direction.REVERSE)]))
    design = Design(helices=helices, strands=strands, lattice_type=LatticeType.HONEYCOMB)

    geom = _geometry_for_design(design)
    tf = _tempfile.NamedTemporaryFile(suffix=".dat", delete=False).name
    try:
        write_configuration(design, geom, tf)
        frames = read_configuration_full(tf, design)
    finally:
        _os.unlink(tf)

    model = build_atomistic_model(design)
    hdir = {h.id: h.direction for h in design.helices}

    # Group built atoms by nucleotide (helix, bp, dir); each carries .name/.residue.
    groups: dict[tuple, list] = {}
    for a in model.atoms:
        if a.helix_id is None or a.bp_index is None:
            continue
        groups.setdefault((a.helix_id, a.bp_index, a.direction), []).append(a)

    def _local(residue: str, direction: Direction) -> dict:
        d = {n: _np.array([x, y, z]) for n, _e, x, y, z in _SUGAR}
        base = BASE_TEMPLATES if direction == Direction.FORWARD else BASE_TEMPLATES_REV
        for n, _e, x, y, z in base[residue][0]:
            d[n] = _np.array([x, y, z])
        return d

    def _kabsch(P: _np.ndarray, W: _np.ndarray) -> tuple[_np.ndarray, _np.ndarray]:
        Pc, Wc = P.mean(0), W.mean(0)
        H = (P - Pc).T @ (W - Wc)
        U, _S, Vt = _np.linalg.svd(H)
        D = _np.sign(_np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ _np.diag([1.0, 1.0, D]) @ U.T
        return R, Wc - R @ Pc

    acc: dict[tuple, dict] = {}
    for key, atoms in groups.items():
        if key not in frames:
            continue
        h_id, _bp, dstr = key
        direction = Direction.FORWARD if dstr == "FORWARD" else Direction.REVERSE
        tl = _local(atoms[0].residue, direction)
        names = [a.name for a in atoms if a.name in tl]
        if len(names) != len(set(names)) or len(names) < 6:
            continue  # duplicate copy or extra-base residue: skip
        wmap = {a.name: _np.array([a.x, a.y, a.z]) for a in atoms}
        P = _np.array([tl[n] for n in names])
        W = _np.array([wmap[n] for n in names])
        R_kg, t_kg = _kabsch(P, W)
        F, bb = _oxdna_frame_basis(frames[key]["backbone_position"],
                                   frames[key]["a1"], frames[key]["a3"])
        bucket = (dstr, hdir[h_id] == Direction.FORWARD)
        slot = acc.setdefault(bucket, {"M": [], "c": []})
        slot["M"].append(F.T @ R_kg)
        slot["c"].append(F.T @ (t_kg - bb))

    calib: dict[tuple, tuple] = {}
    for bucket, slot in acc.items():
        Ms = _np.array(slot["M"])
        U, _S, Vt = _np.linalg.svd(Ms.mean(0))
        Q = U @ Vt
        cmean = _np.array(slot["c"]).mean(0)
        m_res = max(float(_np.linalg.norm(M - Q)) for M in Ms)
        c_res = max(float(_np.linalg.norm(c - cmean)) for c in slot["c"])
        assert m_res < 1e-6 and c_res < 1e-6, (
            f"rigid-frame calibration drift in bucket {bucket}: "
            f"rotation residual {m_res:.2e}, offset residual {c_res:.2e} nm")
        calib[bucket] = (Q, cmean)
    return calib


def _oxdna_rigid_frame(
    cm_nm: _np.ndarray, a1: _np.ndarray, a3: _np.ndarray,
    direction: Direction, helix_direction: "Direction | None",
) -> tuple[_np.ndarray, _np.ndarray]:
    """Stamp position: return (origin, R) placing the nucleotide's template so its
    atoms land at the oxDNA-relaxed rigid pose (CM + a1/a3).  origin = backbone_site
    + F·c, R = F·Q with (Q, c) the calibrated per-bucket constant."""
    F, bb = _oxdna_frame_basis(_np.asarray(cm_nm, float),
                               _np.asarray(a1, float), _np.asarray(a3, float))
    Q, c = _rigid_frame_calibration()[(direction.value,
                                       helix_direction == Direction.FORWARD)]
    return bb + F @ c, F @ Q


def crossover_geometry_diagnostics(design: Design) -> dict:
    """Report crossover linker spans without changing the design.

    A direct crossover is only chemically plausible when the source C3' and
    destination C5' anchors can be joined by the explicitly modeled linker
    length.  This diagnostic flags strained crossovers so callers can move the
    crossover, locally relax the design geometry, or add explicit extra bases in
    NADOC if that is the intended construct.
    """
    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.lattice import position_linker_virtual_helices

    design = position_linker_virtual_helices(design)
    helix_map = {h.id: effective_helix_for_geometry(h, design) for h in design.helices}
    crossover_by_site: dict[frozenset[tuple[str, int, str]], object] = {}
    for xo in design.crossovers:
        key = frozenset({
            (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value),
            (xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand.value),
        })
        crossover_by_site[key] = xo

    pos_cache: dict[str, dict[tuple[int, Direction, int], NucleotidePosition]] = {}
    axis_cache: dict[str, tuple[_np.ndarray, _np.ndarray, int]] = {}
    for h in helix_map.values():
        nucs: dict[tuple[int, Direction, int], NucleotidePosition] = {}
        copy_count: dict[tuple[int, Direction], int] = {}
        for nuc in nucleotide_positions(h):
            base = (nuc.bp_index, nuc.direction)
            copy_k = copy_count.get(base, 0)
            nucs[(nuc.bp_index, nuc.direction, copy_k)] = nuc
            copy_count[base] = copy_k + 1
        pos_cache[h.id] = nucs

        start = _np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        end = _np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z])
        axis = end - start
        norm = float(_np.linalg.norm(axis))
        axis_cache[h.id] = (start, axis / norm if norm > 1e-9 else axis, h.bp_start)

    def _sugar_atom_world(helix_id: str, bp: int, direction: Direction, atom_name: str) -> _np.ndarray | None:
        helix = helix_map.get(helix_id)
        nuc = pos_cache.get(helix_id, {}).get((bp, direction, 0))
        axis_info = axis_cache.get(helix_id)
        if helix is None or nuc is None or axis_info is None:
            return None
        axis_start, axis_hat, bp_start = axis_info
        axis_pt = axis_start + (bp - bp_start) * BDNA_RISE_PER_BP * axis_hat
        origin, R = _atom_frame(nuc, direction, axis_point=axis_pt, helix_direction=helix.direction)
        for name, _element, n, y, z_local in _SUGAR:
            if name == atom_name:
                return origin + R @ _np.array([n, y, z_local])
        return None

    rows: list[dict] = []
    for strand in design.strands:
        prev_domain = None
        for domain in strand.domains:
            if (
                prev_domain is not None
                and prev_domain.helix_id != domain.helix_id
                and prev_domain.end_bp == domain.start_bp
            ):
                site_key = frozenset({
                    (prev_domain.helix_id, prev_domain.end_bp, prev_domain.direction.value),
                    (domain.helix_id, domain.start_bp, domain.direction.value),
                })
                xo = crossover_by_site.get(site_key)
                if xo is None:
                    prev_domain = domain
                    continue
                c3_src = _sugar_atom_world(
                    prev_domain.helix_id, prev_domain.end_bp, prev_domain.direction, "C3'",
                )
                c5_dst = _sugar_atom_world(
                    domain.helix_id, domain.start_bp, domain.direction, "C5'",
                )
                if c3_src is None or c5_dst is None:
                    rows.append({
                        "crossover_id": xo.id,
                        "strand_id": strand.id,
                        "status": "missing_endpoint_geometry",
                    })
                    prev_domain = domain
                    continue

                explicit_extra_bases = len(xo.extra_bases or "")
                linker_segments = explicit_extra_bases + 1
                contour_nm = linker_segments * _PHOSPHODIESTER_LINKER_CONTOUR_NM
                span_nm = float(_np.linalg.norm(c5_dst - c3_src))
                stretch_ratio = span_nm / contour_nm if contour_nm > 0 else float("inf")
                rows.append({
                    "crossover_id": xo.id,
                    "strand_id": strand.id,
                    "source": {
                        "helix_id": prev_domain.helix_id,
                        "bp_index": prev_domain.end_bp,
                        "direction": prev_domain.direction.value,
                    },
                    "destination": {
                        "helix_id": domain.helix_id,
                        "bp_index": domain.start_bp,
                        "direction": domain.direction.value,
                    },
                    "explicit_extra_bases": xo.extra_bases or "",
                    "explicit_extra_base_count": explicit_extra_bases,
                    "anchor_span_nm": span_nm,
                    "available_contour_nm": contour_nm,
                    "stretch_ratio": stretch_ratio,
                    "status": "strained" if stretch_ratio > 1.05 else "ok",
                })
            prev_domain = domain

    strained = [row for row in rows if row.get("status") == "strained"]
    return {
        "schema": "nadoc.atomistic_crossover_geometry.v1",
        "linker_contour_nm_per_segment": _PHOSPHODIESTER_LINKER_CONTOUR_NM,
        "counts": {
            "crossovers_checked": len(rows),
            "strained_crossovers": len(strained),
        },
        "crossovers": rows,
    }


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


def _loop_copy_order(direction: Direction, n_copies: int):
    """Loop-copy indices in the order a strand traverses them 5′→3′.

    A loop insertion emits ``n_copies`` nucleotides at one bp_index, stacked up the
    helix axis by copy index (copy 0 lowest — see ``nucleotide_positions``).  A
    FORWARD strand climbs that stack (0→n-1); a REVERSE strand descends it (n-1→0).
    Threading a reverse strand in ascending order zig-zags the backbone down into the
    bulge and back out (an out-of-order O3′→P bond).  The copy INDEX (identity/key) is
    unchanged — only the traversal order flips — so sequence, atom placement, and
    backbone bonds stay mutually consistent when every loop uses this helper."""
    return range(n_copies) if direction == Direction.FORWARD else range(n_copies - 1, -1, -1)


def _build_sequence_map(design: Design) -> dict[tuple[str, int, str], str]:
    """
    Returns a mapping (helix_id, bp_index, direction) → base character (A/T/G/C/N).

    Iterates all strands.  If a strand has a sequence, distributes characters
    across its domains 5′→3′ in domain order.
    """
    # Scadnano deletions (loop_skip with delta=-1) are absent from the strand
    # sequence string — there is no character at those bp positions.  Build a
    # lookup so we can skip them without consuming a sequence index.
    ls_lookup: dict[tuple[str, int], int] = {}
    for h in design.helices:
        for ls in h.loop_skips:
            key = (h.id, ls.bp_index)
            ls_lookup[key] = ls_lookup.get(key, 0) + ls.delta

    seq_map: dict[tuple, str] = {}
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
            for bp in _atomistic_domain_bp_range(domain, strand):
                if idx >= len(seq):
                    break
                delta = ls_lookup.get((h_id, bp), 0)
                if delta <= -1:
                    continue  # deletion: no character in scadnano sequence string
                n_copies = max(1, delta + 1)
                # Assign sequence characters in the strand's 5′→3′ traversal order so a
                # reverse strand's loop copies get their letters top-of-bulge first.
                for copy_k in _loop_copy_order(domain.direction, n_copies):
                    if idx >= len(seq):
                        break
                    # k=0 uses the plain 3-tuple key for backward compat;
                    # k≥1 uses a 4-tuple key to distinguish loop copies.
                    key: tuple = (h_id, bp, dir_str) if copy_k == 0 else (h_id, bp, dir_str, copy_k)
                    seq_map[key] = seq[idx]
                    idx += 1
    return seq_map


# ── Model builder ─────────────────────────────────────────────────────────────


def _atomistic_domain_bp_range(domain, strand: Strand):
    """Yield bp indices for atomistic placement, including linker edge cases.

    Overhang linker complements are generated by swapping start/end and flipping
    direction so they pair antiparallel on the overhang helix. For one
    orientation that creates a domain whose direction and endpoint order look
    inconsistent to the stricter sequence helper, yielding an empty range. The
    geometry renderer uses min/max for these domains, so atomistic needs this
    linker-only fallback to keep both linker sides represented.
    """
    bps = list(domain_bp_range(domain))
    if bps or strand.strand_type != StrandType.LINKER:
        return bps
    step = 1 if domain.end_bp >= domain.start_bp else -1
    return range(domain.start_bp, domain.end_bp + step, step)


def _append_protein_atoms(model: AtomisticModel, design: Design) -> AtomisticModel:
    """Append world-placed protein-attachment atoms (Part B / MD) to *model*.

    Proteins enter the Physical/export layer only — display/export, never DNA
    topology.  Serials continue past the DNA atoms; bonds use the same 0-based
    serial space.  No-op when the design has no visible protein attachment.
    """
    from backend.core.protein import build_protein_attachment_atoms
    p_atoms, p_bonds, _ = build_protein_attachment_atoms(design, serial_start=len(model.atoms))
    if not p_atoms:
        return model
    model.atoms.extend(p_atoms)
    model.bonds.extend(p_bonds)
    return model


def build_atomistic_model(
    design: Design,
    exclude_helix_ids: set[str] | None = None,
    nuc_pos_override: "dict[tuple[str, int, str], _np.ndarray] | None" = None,
    nuc_frame_override: "dict[tuple[str, int, str], NucleotidePosition] | None" = None,
    include_proteins: bool = False,
    axis_override: "dict[tuple[str, int], tuple[_np.ndarray, _np.ndarray]] | None" = None,
    frame_override: "dict[tuple, tuple[_np.ndarray, _np.ndarray, _np.ndarray]] | None" = None,
    xb_pos_override: "dict[tuple[str, int], _np.ndarray] | None" = None,
    close_backbone: bool = False,
    relaxed_oxdna_phase: bool = False,
) -> AtomisticModel:
    """
    Build the heavy-atom model for the entire design.

    Returns an AtomisticModel with a flat atom list and a bond list (0-based
    serial pairs).  Serial numbers are 0-based to match the list index.

    All frame constants — including the −32° helical phase offset
    (_ATOMISTIC_PHASE_OFFSET_RAD) that aligns the all-atom model with the NADOC
    CG representation — are baked in at the module level.

    Bond coverage:
    - All intra-residue bonds (sugar + base ring)
    - Inter-residue backbone bonds: O3′(i) → P(i+1) for consecutive bp on the
      same strand segment (direction-aware; skips across crossovers/nicks).
    - Extra crossover bases: full ribose + base placed along the interpolation
      line between the two junction nucleotides, with backbone atoms minimised.
    """
    if nuc_pos_override is None and nuc_frame_override is None:
        ref_model = atomistic_model_from_reference(design, exclude_helix_ids)
        if ref_model is not None:
            return _append_protein_atoms(ref_model, design) if include_proteins else ref_model

    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.lattice import position_linker_virtual_helices
    design = position_linker_virtual_helices(design)

    helix_map = {h.id: effective_helix_for_geometry(h, design) for h in design.helices}

    seq_map = _build_sequence_map(design)
    sugar_template = _SUGAR

    # Pre-compute the 3′-terminal keys (domain.end_bp) that immediately precede
    # extra-base crossover junctions.  These keys must be skipped in the direct
    # bond-building and crossover interpolation passes so _build_extra_base_atoms
    # can lay the correct O3′→P chain through the extra bases instead.
    #
    # The Crossover model is bidirectional — half_a may be either the src or dst
    # depending on strand orientation.  We determine the correct src by walking
    # the strand topology: whichever half sits at a domain.end_bp is the 3′-
    # terminal (src); the other half is the 5′-start (dst).
    _eb_junction_pos: set[tuple[str, int]] = set()
    for xo in design.crossovers:
        if xo.extra_bases:
            _eb_junction_pos.add((xo.half_a.helix_id, xo.half_a.index))
            _eb_junction_pos.add((xo.half_b.helix_id, xo.half_b.index))

    extra_base_xover_src: set[tuple[str, int, str]] = set()
    for _s in design.strands:
        _prev_d = None
        for _d in _s.domains:
            if (_prev_d is not None
                    and _prev_d.helix_id != _d.helix_id
                    and _prev_d.end_bp == _d.start_bp
                    and (_prev_d.helix_id, _prev_d.end_bp) in _eb_junction_pos):
                extra_base_xover_src.add(
                    (_prev_d.helix_id, _prev_d.end_bp, _prev_d.direction.value)
                )
            _prev_d = _d

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

    # (helix_id, bp_index, direction_str) → {atom_name: serial} for crossover interpolation
    bp_to_sugar_serials: dict[tuple[str, int, str], dict[str, int]] = {}

    # Cache nucleotide positions per helix (avoid recomputing for each domain)
    nuc_pos_cache: dict[str, dict[tuple[int, Direction], NucleotidePosition]] = {}

    # Cache helix axis geometry for radial correction: (axis_start, axis_hat)
    _helix_axis_cache: dict[str, tuple[_np.ndarray, _np.ndarray, int]] = {}
    for h in helix_map.values():
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
                _npc: dict[tuple, NucleotidePosition] = {}
                _copy_cnt: dict[tuple, int] = {}
                for _nuc in nucleotide_positions(helix):
                    _base = (_nuc.bp_index, _nuc.direction)
                    _k = _copy_cnt.get(_base, 0)
                    _npc[(_nuc.bp_index, _nuc.direction, _k)] = _nuc
                    _copy_cnt[_base] = _k + 1
                nuc_pos_cache[h_id] = _npc
            nuc_positions = nuc_pos_cache[h_id]

            # Extend the position cache if this domain reaches beyond the helix's
            # physical bp range.  This happens for scaffold loop domains generated
            # by scaffold_loops=True or scaffold_add_end_crossovers: those domains
            # extend to bp indices below bp_start (left-side crossover) or above
            # bp_start+length_bp (right-side crossover).  Without this extension
            # those nucleotides are silently skipped as "skip/loop positions".
            _helix_lo = helix.bp_start
            _helix_hi = helix.bp_start + helix.length_bp   # exclusive upper bound
            if direction == Direction.FORWARD:
                _dom_lo, _dom_hi = domain.start_bp, domain.end_bp
            else:
                _dom_lo, _dom_hi = domain.end_bp, domain.start_bp

            if _dom_lo < _helix_lo:
                _ea = nucleotide_positions_arrays_extended(helix, _dom_lo)
                for _i in range(len(_ea['bp_indices'])):
                    _bp = int(_ea['bp_indices'][_i])
                    _d  = Direction.FORWARD if _ea['directions'][_i] == 0 else Direction.REVERSE
                    _k  = (_bp, _d, 0)  # overhang extensions are always copy 0
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id      = helix.id,
                            bp_index      = _bp,
                            direction     = _d,
                            position      = _ea['positions'][_i].copy(),
                            base_position = _ea['base_positions'][_i].copy(),
                            base_normal   = _ea['base_normals'][_i].copy(),
                            axis_tangent  = _ea['axis_tangents'][_i].copy(),
                        )
            if _dom_hi >= _helix_hi:
                _ea = nucleotide_positions_arrays_extended_right(helix, _dom_hi)
                for _i in range(len(_ea['bp_indices'])):
                    _bp = int(_ea['bp_indices'][_i])
                    _d  = Direction.FORWARD if _ea['directions'][_i] == 0 else Direction.REVERSE
                    _k  = (_bp, _d, 0)  # overhang extensions are always copy 0
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id      = helix.id,
                            bp_index      = _bp,
                            direction     = _d,
                            position      = _ea['positions'][_i].copy(),
                            base_position = _ea['base_positions'][_i].copy(),
                            base_normal   = _ea['base_normals'][_i].copy(),
                            axis_tangent  = _ea['axis_tangents'][_i].copy(),
                        )

            for bp in _atomistic_domain_bp_range(domain, strand):
                _n_copies = 0
                while (bp, direction, _n_copies) in nuc_positions:
                    _n_copies += 1
                # Thread loop copies in strand 5′→3′ order (reverse strands descend the
                # axial stack) so the backbone doesn't zig-zag through the bulge.
                for copy_k in _loop_copy_order(direction, _n_copies):
                    nuc_pos = nuc_positions.get((bp, direction, copy_k))
                    if nuc_pos is None:
                        continue  # skip position (no nucleotide) — belt-and-braces

                    # Apply CG position override for copy 0 only.
                    if nuc_pos_override is not None and copy_k == 0:
                        cg_pos = nuc_pos_override.get((h_id, bp, dir_str))
                        if cg_pos is not None:
                            import dataclasses as _dc
                            nuc_pos = _dc.replace(nuc_pos, position=cg_pos)

                    seq_num_in_chain += 1
                    _seq_key: tuple = (h_id, bp, dir_str) if copy_k == 0 else (h_id, bp, dir_str, copy_k)
                    base_char = seq_map.get(_seq_key, "N")
                    residue   = _BASE_CHAR_TO_RESIDUE.get(base_char, "DT")

                    # frame_override: stamp the template by an oxDNA rigid frame
                    # (CM, a1, a3) directly, instead of deriving orientation from the
                    # axis.  SUPERSEDED FOR DISPLAY (2026-06-21): on real RELAXED
                    # frames this COLLAPSES base pairs (WC C1'–C1' ~0.48 vs 0.94 nm)
                    # because oxDNA's relaxed a1 does not map onto the all-atom base
                    # direction the calibration assumes.  The display sinks use the
                    # axis-derived path (oxdna_health.build_display_model); this branch
                    # is retained only as an exact-on-ideal-geometry capability (the
                    # rigid-placer pins in test_oxdna_relaxation.py) and the validation
                    # oracle's wc_collapsed check guards against any re-introduction.
                    _fo = None
                    if frame_override is not None:
                        _fo = frame_override.get((h_id, bp, dir_str, copy_k))
                        if _fo is None and copy_k == 0:
                            _fo = frame_override.get((h_id, bp, dir_str))
                    if _fo is not None:
                        origin, R = _oxdna_rigid_frame(
                            _fo[0], _fo[1], _fo[2], direction, helix.direction)
                    else:
                        _frame_key = (h_id, bp, dir_str)
                        _use_prepared_frame = False
                        if nuc_frame_override is not None and copy_k == 0:
                            _nfo = nuc_frame_override.get(_frame_key)
                            if _nfo is not None:
                                nuc_pos = _nfo
                                _use_prepared_frame = True

                        # Apply CG position override for copy 0 only (NAMD-seed path).
                        if nuc_pos_override is not None and copy_k == 0:
                            cg_pos = nuc_pos_override.get(_frame_key)
                            if cg_pos is not None:
                                import dataclasses as _dc
                                nuc_pos = _dc.replace(nuc_pos, position=cg_pos)

                        # Compute helix axis point for radial correction.  An optional
                        # axis_override supplies a DEFORMED (curved) centerline point +
                        # local tangent per (helix, bp): when seeding from a relaxed CG
                        # structure the radial direction (hence the helical phase) must be
                        # measured against the BENT axis, not the ideal straight one —
                        # otherwise a helix displaced from its ideal axis makes the global
                        # displacement swamp the true radial, destroying the twist and
                        # piling adjacent nucleotides together (the seed-clash bug).
                        ax_start, ax_hat, bp_start = _helix_axis_cache[h_id]
                        axis_pt = ax_start + (bp - bp_start) * BDNA_RISE_PER_BP * ax_hat
                        if _use_prepared_frame:
                            axis_pt = None
                        elif axis_override is not None:
                            _ov = axis_override.get((h_id, bp))
                            if _ov is not None:
                                import dataclasses as _dc
                                axis_pt = _ov[0]
                                nuc_pos = _dc.replace(nuc_pos, axis_tangent=_ov[1])

                        # Reverse-strand azimuthal correction: the design geometry
                        # places the reverse strand at fwd ± minor_groove (±150°),
                        # SIGN by the helix's LATTICE direction (geometry.py), and
                        # _atom_frame undoes that per-direction.  But oxDNA relaxation
                        # erases the lattice-location distinction — it relaxes BOTH
                        # helix types to a real B-DNA duplex at the SAME physical groove
                        # angle (raw CG: FORWARD ≡ REVERSE helices).  So the relaxed
                        # DISPLAY reconstruction must apply the UNIFORM (forward) branch;
                        # using the per-lattice-direction branch collapses REVERSE-helix
                        # WC pairs (C1'–C1' 0.96 → 0.72 nm).  Design/PDB/seed builds
                        # (relaxed_oxdna_phase=False) keep the real per-direction branch.
                        _hd = Direction.FORWARD if relaxed_oxdna_phase else helix.direction
                        origin, R = _atom_frame(nuc_pos, direction, axis_point=axis_pt,
                                                helix_direction=_hd)

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
                    tmpl_dict = BASE_TEMPLATES if direction == Direction.FORWARD else BASE_TEMPLATES_REV
                    base_atoms_def, base_bond_defs = tmpl_dict[residue]
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

                    # Register for inter-residue backbone bond building (copy-indexed).
                    bp_to_serials[(h_id, bp, dir_str, copy_k)] = (
                        sugar_name_to_serial.get("O3'"),
                        sugar_name_to_serial.get("P"),
                    )
                    # Register full sugar serial map for crossover/skip bridge.  Keep the
                    # HIGHEST-index copy as the representative (order-independent) so this
                    # matches the previous ascending "last-copy-wins" — crossover/skip src
                    # lookups are unaffected by the reversed loop-copy traversal order.
                    if copy_k == _n_copies - 1:
                        bp_to_sugar_serials[(h_id, bp, dir_str)] = dict(sugar_name_to_serial)

    # ── Inter-residue backbone bonds (O3′ → P of next residue) ───────────────
    # Walk each strand's domains in 5′→3′ order; connect consecutive bp.
    # Crossovers that carry extra bases are skipped here — _build_extra_base_atoms
    # adds the correct O3′→P chain through the extra-base loop instead.
    for strand in design.strands:
        direction = None
        prev_o3_serial: Optional[int] = None
        prev_nuc_key:   Optional[tuple[str, int, str]] = None
        for domain in strand.domains:
            h_id      = domain.helix_id
            dir_str   = domain.direction.value
            direction = domain.direction
            for bp in _atomistic_domain_bp_range(domain, strand):
                _n_copies = 0
                while (h_id, bp, dir_str, _n_copies) in bp_to_serials:
                    _n_copies += 1
                if _n_copies == 0:
                    prev_o3_serial = None
                    prev_nuc_key   = None
                    continue
                # Connect loop copies in the SAME 5′→3′ traversal order as placement.
                for copy_k2 in _loop_copy_order(direction, _n_copies):
                    o3_serial, p_serial = bp_to_serials[(h_id, bp, dir_str, copy_k2)]
                    if prev_o3_serial is not None and p_serial is not None:
                        # Skip direct bond if the previous nucleotide is the 3′
                        # junction of an extra-base crossover (handled separately).
                        if prev_nuc_key not in extra_base_xover_src:
                            bonds.append((prev_o3_serial, p_serial))
                    prev_o3_serial = o3_serial
                    prev_nuc_key   = (h_id, bp, dir_str)

    # ── Crossover phosphate bridge relaxation ────────────────────────────────
    # At each crossover (consecutive domains on different helices sharing the
    # same bp position), place O3′(src), P(dst), and O5′(dst) by minimising
    # canonical phosphodiester bond-length and bond-angle error.  This keeps the
    # ribose anchors fixed while avoiding the collinear linker geometry produced
    # by straight interpolation, which is a poor starting point for MD.
    # Crossovers with extra bases are skipped here — their interpolation is
    # handled by _build_extra_base_atoms which covers every pair in the chain.
    for strand in design.strands:
        prev_domain = None
        for domain in strand.domains:
            if (prev_domain is not None
                    and prev_domain.helix_id != domain.helix_id
                    and prev_domain.end_bp == domain.start_bp):
                src_key = (prev_domain.helix_id, prev_domain.end_bp, prev_domain.direction.value)
                if src_key in extra_base_xover_src:
                    prev_domain = domain
                    continue
                dst_key = (domain.helix_id, domain.start_bp, domain.direction.value)
                src_s = bp_to_sugar_serials.get(src_key)
                dst_s = bp_to_sugar_serials.get(dst_key)
                if src_s and dst_s:
                    _minimize_backbone_bridge(atoms, src_s, dst_s)

            prev_domain = domain

    # ── Skip-site backbone bridge interpolation ────────────────────────────────
    # When a helix has loop_skips with delta ≤ −1, no nucleotide is emitted for
    # that bp (nucleotide_positions() skips it with `continue`).  pdb2gmx bonds
    # residues in PDB file order, creating an O3′(before)→P(after) bond across
    # the skipped position.  Without adjustment, O3′ and P retain their template
    # positions, placing them ~5–8 Å apart (vs the 1.6 Å equilibrium O3′–P
    # bond length) — causing extreme force-field strain in GROMACS.
    #
    # Use the geometry-minimising bridge (same as extra-base crossovers) to
    # place O3′(before), P(after) and O5′(after) with canonical bond lengths
    # AND angles — not just linearly on the chord.  This gives much better
    # initial geometry, reducing residual GROMACS force-field strain after EM.
    for strand in design.strands:
        _skip_cache_bb: dict[str, set[int]] = {}

        prev_key_bb: Optional[tuple[str, int, str]] = None

        for domain in strand.domains:
            h_id    = domain.helix_id
            dir_str = domain.direction.value
            helix   = helix_map.get(h_id)
            if helix is None:
                prev_key_bb = None
                continue

            if h_id not in _skip_cache_bb:
                _ls_acc: dict[int, int] = {}
                for ls in helix.loop_skips:
                    _ls_acc[ls.bp_index] = _ls_acc.get(ls.bp_index, 0) + ls.delta
                _skip_cache_bb[h_id] = {bp for bp, d in _ls_acc.items() if d <= -1}
            skip_bps_bb = _skip_cache_bb[h_id]

            if not skip_bps_bb:
                prev_key_bb = None
                continue

            for bp in _atomistic_domain_bp_range(domain, strand):
                if bp in skip_bps_bb:
                    # Skip position — do NOT update prev_key so the next valid bp
                    # sees the gap and triggers bridge interpolation.
                    continue

                cur_key_bb = (h_id, bp, dir_str)
                if cur_key_bb not in bp_to_sugar_serials:
                    prev_key_bb = None
                    continue

                if prev_key_bb is not None:
                    pv_h, pv_bp, pv_dir = prev_key_bb
                    # Same helix, same direction, gap > 1 bp → skip(s) in between.
                    if pv_h == h_id and pv_dir == dir_str and abs(bp - pv_bp) > 1:
                        src_s = bp_to_sugar_serials.get(prev_key_bb)
                        dst_s = bp_to_sugar_serials.get(cur_key_bb)
                        if src_s and dst_s:
                            _minimize_backbone_bridge(atoms, src_s, dst_s)

                prev_key_bb = cur_key_bb

            # Reset at domain boundary: next domain is either a different helix
            # (crossover, handled above) or a different position on the same helix.
            prev_key_bb = None

    # ── Extra crossover base atoms ────────────────────────────────────────────
    serial = _build_extra_base_atoms(
        design             = design,
        atoms              = atoms,
        bonds              = bonds,
        serial             = serial,
        strand_to_chain    = strand_to_chain,
        nuc_pos_cache      = nuc_pos_cache,
        helix_map          = helix_map,
        bp_to_sugar_serials = bp_to_sugar_serials,
        exclude_helix_ids  = exclude_helix_ids,
        xb_pos_override    = xb_pos_override,
    )

    # ── Thread extra-base inserts inline in the per-chain residue numbering ────
    # _build_extra_base_atoms appends the inserts at the END of each chain's
    # seq_num range.  The psfgen topology writer bonds residues in seq_num order,
    # so end-appended inserts get threaded prev_real → eb → eb → next-crossover's
    # eb (a 55 Å junk bond), instead of prev_real → eb → eb → next_real at the
    # actual junction.  Renumber every chain so each insert sits immediately after
    # its source-flank nucleotide (see _thread_extra_bases_inline).
    _thread_extra_bases_inline(atoms)

    # ── DISPLAY-ONLY: close the sequential backbone (relaxed-frame reconstruction) ─
    # oxDNA's per-nucleotide CG frames do NOT enforce all-atom backbone continuity,
    # so reconstructing consecutive nucleotides leaves the O3′(i)→P(i+1) stick
    # stretched (~0.9 nm median on a real relaxed 6hb vs 0.16 nm ideal) — the long
    # bonds in the ball-and-stick view.  Opt-in via close_backbone=True (the relaxed
    # DISPLAY sinks only): re-seat just the phosphate linker (O3′/P/O5′/OP1/OP2)
    # between the rigid C3′(i)/C5′(i+1) anchors so the backbone draws CONNECTED.
    # Crossover / skip / extra-base junctions were bridged above and are not
    # same-helix-consecutive, so they are left untouched; the ring + base atoms never
    # move.  DEFAULT False → the design / PDB-export / NAMD-seed builds are
    # byte-identical (the seed is minimised by NAMD; it must NOT be pre-closed).
    if close_backbone:
        _close_sequential_backbone(atoms, bonds)

    # ── Apply deformations (bend/twist) and cluster rigid transforms ──────────
    # All atom positions above are placed in straight (undeformed) geometry.
    # This final pass rotates/translates every atom to match the deformed 3-D view.
    from backend.core.deformation import apply_deformations_to_atoms
    apply_deformations_to_atoms(atoms, design)

    model = AtomisticModel(atoms=atoms, bonds=bonds)
    if include_proteins:
        model = _append_protein_atoms(model, design)
    return model


def _thread_extra_bases_inline(atoms: list[Atom]) -> None:
    """Re-number per-chain ``seq_num`` so crossover extra-base inserts sit inline in
    the strand, immediately after their source-flank nucleotide, in-place.

    ``_build_extra_base_atoms`` appends every insert to the END of its chain's
    ``seq_num`` range.  Consumers that rely on ``seq_num`` order to define backbone
    connectivity — the CHARMM psfgen topology builder above all — then bond the
    inserts as one contiguous run at the chain tail (``prev_real → eb → eb → the
    next crossover's eb``), producing wildly stretched O3′→P bonds between inserts
    that belong to different junctions.  Threading them inline restores
    ``prev_real → eb… → next_real`` at each real junction.

    Each insert atom carries its source (owning, 3′) flank nucleotide's
    ``(helix_id, bp_index, direction)`` (set by ``_build_extra_base_atoms``); the
    insert is placed right after the real residue with that key, ordered by
    ``extra_base_k``.  An insert whose flank can't be resolved uniquely (e.g. a
    looped helix where ``(helix, bp, dir)`` is not unique) is left at the chain
    tail — the same position as before, so no regression for that case.

    Physical-layer only: touches ``seq_num`` (a residue counter), never topology.
    """
    from collections import defaultdict

    # residue key: real → ("r", seq_num); insert → ("x", crossover_id, extra_base_k)
    def _rkey(a: Atom):
        if getattr(a, "crossover_id", None) is not None:
            return ("x", a.crossover_id, a.extra_base_k)
        return ("r", a.seq_num)

    by_chain: dict[str, list[Atom]] = defaultdict(list)
    for a in atoms:
        by_chain[a.chain_id].append(a)

    for chain_atoms in by_chain.values():
        # Group this chain's atoms into residues.
        residues: dict[tuple, list[Atom]] = defaultdict(list)
        for a in chain_atoms:
            residues[_rkey(a)].append(a)

        real_rkeys = [k for k in residues if k[0] == "r"]
        insert_rkeys = [k for k in residues if k[0] == "x"]
        if not insert_rkeys:
            continue  # nothing to thread on this chain

        real_rkeys.sort(key=lambda k: k[1])  # by existing seq_num

        # (helix, bp, dir) → real residue key, dropping non-unique keys (loops).
        flank_to_real: dict[tuple, tuple] = {}
        ambiguous: set[tuple] = set()
        for k in real_rkeys:
            a0 = residues[k][0]
            fk = (a0.helix_id, a0.bp_index, a0.direction)
            if fk in flank_to_real:
                ambiguous.add(fk)
            flank_to_real[fk] = k
        for fk in ambiguous:
            flank_to_real.pop(fk, None)

        # Bucket inserts by the real residue they follow.
        inserts_after: dict[tuple, list[tuple]] = defaultdict(list)
        orphaned: list[tuple] = []
        for k in insert_rkeys:
            a0 = residues[k][0]
            fk = (a0.helix_id, a0.bp_index, a0.direction)
            prev_k = flank_to_real.get(fk)
            if prev_k is None:
                orphaned.append(k)
            else:
                inserts_after[prev_k].append(k)
        for lst in inserts_after.values():
            lst.sort(key=lambda k: k[2])  # by extra_base_k

        # Emit real residues in order, each trailed by its inserts; orphans last.
        ordered: list[tuple] = []
        for k in real_rkeys:
            ordered.append(k)
            ordered.extend(inserts_after.get(k, ()))
        ordered.extend(sorted(orphaned, key=lambda k: (str(k[1]), k[2])))

        # Contiguous 1-based renumber in the new order.
        for new_seq, k in enumerate(ordered, start=1):
            for a in residues[k]:
                a.seq_num = new_seq


def _close_sequential_backbone(atoms: list[Atom], bonds: list[tuple[int, int]]) -> None:
    """DISPLAY-ONLY backbone closure for the oxDNA-frame reconstruction.

    For every SEQUENTIAL O3′(i)→P(i+1) backbone bond (same helix, same direction,
    consecutive bp — i.e. a continuous strand run, NOT a crossover/skip/extra-base
    junction, which are bridged elsewhere), linearly re-seat the phosphate linker
    atoms (O3′, P, O5′, OP1, OP2) between the rigid C3′(i) and C5′(i+1) anchors via
    ``_interpolate_backbone_bridge``.  Distributes the CG-vs-all-atom spacing
    mismatch evenly across the 4 linker bonds (~span/4 each) instead of leaving one
    impossible ~0.9 nm O3′→P stick, so the backbone renders connected.  The ribose
    ring + base atoms are never touched (the rigid-stamp invariant holds).  Cheap
    (pure interpolation, ~0.01 s for ~1000 bonds), so it runs every display frame."""
    by_res: dict[tuple, dict[str, int]] = {}
    for a in atoms:
        by_res.setdefault((a.strand_id, a.seq_num), {})[a.name] = a.serial
    seen: set[tuple] = set()
    for i, j in bonds:
        a, b = atoms[i], atoms[j]
        if {a.name, b.name} != {"O3'", "P"}:
            continue
        src, dst = (a, b) if a.name == "O3'" else (b, a)
        if not (src.helix_id == dst.helix_id and src.direction == dst.direction
                and abs(src.bp_index - dst.bp_index) == 1):
            continue   # crossover / skip / extra-base bridge — already handled
        key = ((src.strand_id, src.seq_num), (dst.strand_id, dst.seq_num))
        if key in seen:
            continue
        seen.add(key)
        _interpolate_backbone_bridge(atoms, by_res[key[0]], by_res[key[1]])


# ── Crossover interpolation helpers ──────────────────────────────────────────
# _normalise and _lerp moved to atomistic_helpers (Pass 11-A).



# ── Atom-mutation primitives, backbone bridges, rigid-body, joint extra-base
# minimisers + scipy result cache moved to atomistic_minimisers (Pass 13-A);
# imported above for use within this module and re-exported for external
# callers (notably backend.core.periodic_cell).



# ── Extra-base arc geometry helpers ──────────────────────────────────────────
# _bezier_pt, _bezier_tan, _arc_bow_dir, _arc_ctrl_pt and _BOW_FRAC_3D moved to
# atomistic_helpers (Pass 11-A); imported above.


def _extra_base_frame(
    origin:   _np.ndarray,
    line_dir: _np.ndarray,
    bow_dir:  _np.ndarray,
) -> tuple[_np.ndarray, _np.ndarray]:
    """
    Build atom frame for an extra crossover base oriented along the
    interpolation line between C3′(src) and C5′(dst).

      origin   = position along that line (lerp output)
      line_dir = unit vector pointing 5′→3′: normalise(C5′(dst) − C3′(src))
      bow_dir  = outward from Holliday junction (azimuthal orientation)

    Frame construction:
      e_z = −line_dir  (3′→5′; aligns C3′–C4′ bond with line; base plane ⊥ line)
      e_n = bow_dir projected onto the plane perpendicular to e_z, then normalised
      e_y = cross(e_z, e_n)
      R   = [e_n | e_y | e_z] with _FRAME_ROT_RAD pre-compensation cancel
    """
    e_z = -line_dir

    # Project bow_dir onto the plane normal to e_z so e_n ⊥ e_z
    bow_proj = bow_dir - float(_np.dot(bow_dir, e_z)) * e_z
    bow_n = float(_np.linalg.norm(bow_proj))
    if bow_n < 1e-6:
        # bow_dir is parallel to line — pick any perpendicular
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(float(_np.dot(e_z, fallback))) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        bow_proj = fallback - float(_np.dot(fallback, e_z)) * e_z
        bow_n = float(_np.linalg.norm(bow_proj))
    e_n = bow_proj / bow_n

    e_y = _np.cross(e_z, e_n)
    norm_y = float(_np.linalg.norm(e_y))
    if norm_y < 1e-9:
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(float(_np.dot(e_n, fallback))) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        e_y = _np.cross(e_z, fallback)
        norm_y = float(_np.linalg.norm(e_y))
    e_y = e_y / norm_y

    R = _np.column_stack([e_n, e_y, e_z])
    # Cancel template pre-compensation (+37.05° baked into all templates)
    c, s = _math.cos(_FRAME_ROT_RAD), _math.sin(_FRAME_ROT_RAD)
    R = R @ _np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    return origin.copy(), R


# ── Extra-base atom builder ───────────────────────────────────────────────────


def _build_extra_base_atoms(
    design:             "Design",
    atoms:              list[Atom],
    bonds:              list[tuple[int, int]],
    serial:             int,
    strand_to_chain:    dict[str, str],
    nuc_pos_cache:      dict[str, dict[tuple[int, "Direction"], "NucleotidePosition"]],
    helix_map:          dict[str, object],
    bp_to_sugar_serials: dict[tuple[str, int, str], dict[str, int]],
    exclude_helix_ids:  "set[str] | None",
    xb_pos_override:    "dict[tuple[str, int], _np.ndarray] | None" = None,
) -> int:
    """
    Place atomistic atoms for all extra crossover bases in the design.

    Each extra base gets a full ribose ring (rigid transform of the default
    sugar template) oriented so that C3′–C4′ is parallel to the interpolation
    line between the two junction nucleotides, with the nitrogenous base
    facing the bow direction (outward from the Holliday junction).  Backbone
    linker atoms (O3′/P/O5′) between each consecutive nucleotide pair are
    placed by a scipy L-BFGS-B minimisation of bond-length and bond-angle
    deviations from canonical B-DNA values.

    Returns the updated serial number (next available 0-based index).
    """
    from types import SimpleNamespace as _NS
    xovers_with_extra = [xo for xo in design.crossovers if xo.extra_bases]

    # Append forced ligations with extra bases as crossover-compatible objects.
    # Three-prime endpoint = src (domain 3′ exit); five-prime = dst (domain 5′ entry).
    for fl in design.forced_ligations:
        if not fl.extra_bases:
            continue
        ha = _NS(helix_id=fl.three_prime_helix_id, index=fl.three_prime_bp, strand=fl.three_prime_direction)
        hb = _NS(helix_id=fl.five_prime_helix_id,  index=fl.five_prime_bp,  strand=fl.five_prime_direction)
        xovers_with_extra.append(_NS(id=fl.id, extra_bases=fl.extra_bases, half_a=ha, half_b=hb))

    if not xovers_with_extra:
        return serial

    # Build (helix_id, domain_end_bp, dir_str) → strand_id for chain lookup
    domain_end_to_strand: dict[tuple[str, int, str], str] = {}
    for strand in design.strands:
        for domain in strand.domains:
            key = (domain.helix_id, domain.end_bp, domain.direction.value)
            domain_end_to_strand[key] = strand.id

    # Track last seq_num per chain so extra bases continue numbering seamlessly
    extra_seq_num: dict[str, int] = {}
    for a in atoms:
        cur = extra_seq_num.get(a.chain_id, 0)
        if a.seq_num > cur:
            extra_seq_num[a.chain_id] = a.seq_num

    # Minimisation jobs collected here; run in parallel after all atoms are placed.
    _mini_jobs: list = []

    for xo in xovers_with_extra:
        ha, hb = xo.half_a, xo.half_b

        # Skip if either helix is excluded
        if exclude_helix_ids and (
            ha.helix_id in exclude_helix_ids or hb.helix_id in exclude_helix_ids
        ):
            continue

        # Ensure nuc_pos_cache is populated for both junction helices
        for h_id in (ha.helix_id, hb.helix_id):
            if h_id not in nuc_pos_cache:
                helix = helix_map.get(h_id)
                if helix is not None:
                    _npc2: dict[tuple, NucleotidePosition] = {}
                    _cc2: dict[tuple, int] = {}
                    for _nuc in nucleotide_positions(helix):
                        _base = (_nuc.bp_index, _nuc.direction)
                        _k2 = _cc2.get(_base, 0)
                        _npc2[(_nuc.bp_index, _nuc.direction, _k2)] = _nuc
                        _cc2[_base] = _k2 + 1
                    nuc_pos_cache[h_id] = _npc2

        nucA = nuc_pos_cache.get(ha.helix_id, {}).get((ha.index, ha.strand, 0))
        nucB = nuc_pos_cache.get(hb.helix_id, {}).get((hb.index, hb.strand, 0))
        if nucA is None or nucB is None:
            continue

        posA    = nucA.position
        posB    = nucB.position
        bow_dir = _arc_bow_dir(posA, posB, nucA.axis_tangent, nucB.axis_tangent)

        # Determine which half is the domain-end (3′ terminal = src) and which is
        # the domain-start (5′ initial = dst).  The Crossover model is
        # bidirectional; domain_end_to_strand tells us which half lies at a
        # domain.end_bp (i.e. the 3′ exit of that domain = the src).
        half_a_key = (ha.helix_id, ha.index, ha.strand.value)
        half_b_key = (hb.helix_id, hb.index, hb.strand.value)
        if half_a_key in domain_end_to_strand:
            src_key, dst_key = half_a_key, half_b_key
            pos_src, pos_dst = posA, posB
        else:
            src_key, dst_key = half_b_key, half_a_key
            pos_src, pos_dst = posB, posA

        strand_id = domain_end_to_strand.get(src_key)
        chain_id  = strand_to_chain.get(strand_id, "A") if strand_id else "A"

        # Sugar serial dicts for junction nucleotides (may be None if excluded)
        src_s = bp_to_sugar_serials.get(src_key)
        dst_s = bp_to_sugar_serials.get(dst_key)

        # Interpolation line: C3′(src) → C5′(dst).  Fall back to nucleotide
        # positions if either junction's atoms aren't in the model (excluded helix).
        if src_s is not None and "C3'" in src_s:
            line_p0 = _atom_pos(atoms, src_s["C3'"])
        else:
            line_p0 = _np.array(pos_src)
        if dst_s is not None and "C5'" in dst_s:
            line_p1 = _atom_pos(atoms, dst_s["C5'"])
        else:
            line_p1 = _np.array(pos_dst)
        line_vec = line_p1 - line_p0
        line_len = float(_np.linalg.norm(line_vec))
        line_dir = line_vec / line_len if line_len > 1e-9 else bow_dir

        # Bow the extra-base sugar origins outward along the rendered crossover
        # arc (quadratic bezier bowing BOW_FRAC_3D of the chord) instead of the
        # straight chord.  The straight chord threads the cramped inter-helix
        # backbone gap, so the inserted single-stranded loop landed on top of
        # the neighbouring helix backbones (steric clash); bowing it out lets the
        # loop bulge into solvent, matching the arc the renderer already draws.
        arc_ctrl = _arc_ctrl_pt(line_p0, line_p1, bow_dir)

        n = len(xo.extra_bases)
        eb_sugar_serials:  list[dict[str, int]] = []
        eb_glycosidic_ns:  list[str]            = []

        # Collect C1′/C3′/C4′ positions from the OPPOSITE-direction nucleotides
        # at each junction half — these are the atoms most likely to clash with
        # extra bases at the Holliday junction.
        repel_pos: list[_np.ndarray] = []
        for _h_id, _bp_idx, _d_str in (
            (ha.helix_id, ha.index, ha.strand.value),
            (hb.helix_id, hb.index, hb.strand.value),
        ):
            _opp = "REVERSE" if _d_str == "FORWARD" else "FORWARD"
            _opp_s = bp_to_sugar_serials.get((_h_id, _bp_idx, _opp))
            if _opp_s is not None:
                for _aname in ("C1'", "C3'", "C4'"):
                    _s = _opp_s.get(_aname)
                    if _s is not None:
                        repel_pos.append(_atom_pos(atoms, _s))

        # Target direction for the C1′→N glycosidic bond.
        # avg_axis points along the helix bundle axis (≈ +Z for vertical helices).
        # z_sign > 0: crossover bows "right" → align C1′→N with +avg_axis.
        # z_sign < 0: crossover bows "left"  → align C1′→N with −avg_axis.
        avg_axis   = _normalise(
            _np.array(nucA.axis_tangent) + _np.array(nucB.axis_tangent)
        )
        z_sign     = float(_np.dot(_np.cross(bow_dir, line_dir), avg_axis))
        target_c1n = avg_axis if z_sign > 0.0 else -avg_axis

        for i, base_char in enumerate(xo.extra_bases, start=1):
            t_i = i / (n + 1)
            if line_len > 1e-9:
                origin_pos = _bezier_pt(line_p0, arc_ctrl, line_p1, t_i)
                arc_dir = _bezier_tan(line_p0, arc_ctrl, line_p1, t_i)
            else:
                origin_pos = _lerp(line_p0, line_p1, t_i)
                arc_dir = bow_dir
            # Relaxed/trajectory display: place this insert at its REAL simulated
            # backbone position (keeping the arc-derived orientation), so the heavy
            # rep shows the true ssDNA conformation instead of the geometric arc.
            _xb_sim = (xb_pos_override.get((xo.id, i - 1))
                       if xb_pos_override is not None else None)
            if _xb_sim is not None:
                origin_pos = _np.asarray(_xb_sim, dtype=float)
            origin, R = _extra_base_frame(origin_pos, arc_dir, bow_dir)

            residue = _BASE_CHAR_TO_RESIDUE.get(base_char.upper(), "DT")
            extra_seq_num[chain_id] = extra_seq_num.get(chain_id, 0) + 1
            seq_num = extra_seq_num[chain_id]

            # ── Sugar atoms ──────────────────────────────────────────────────
            _aux_t = float(i) / float(n + 1)
            sugar_name_to_serial: dict[str, int] = {}
            for atom_name, element, n_c, y_c, z_c in _SUGAR:
                local = _np.array([n_c, y_c, z_c])
                world = origin + R @ local
                atoms.append(Atom(
                    serial       = serial,
                    name         = atom_name,
                    element      = element,
                    residue      = residue,
                    chain_id     = chain_id,
                    seq_num      = seq_num,
                    x            = float(world[0]),
                    y            = float(world[1]),
                    z            = float(world[2]),
                    strand_id    = strand_id or "",
                    helix_id     = src_key[0],
                    bp_index     = src_key[1],
                    direction    = src_key[2],
                    aux_helix_id = dst_key[0],
                    aux_t        = _aux_t,
                    crossover_id = xo.id,
                    extra_base_k = i - 1,
                ))
                sugar_name_to_serial[atom_name] = serial
                serial += 1

            # ── Base atoms (FORWARD template convention for all extra bases) ─
            base_atoms_def, base_bond_defs = BASE_TEMPLATES[residue]
            base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
            for atom_name, element, n_c, y_c, z_c in base_atoms_def:
                local = _np.array([n_c, y_c, z_c])
                world = origin + R @ local
                atoms.append(Atom(
                    serial       = serial,
                    name         = atom_name,
                    element      = element,
                    residue      = residue,
                    chain_id     = chain_id,
                    seq_num      = seq_num,
                    x            = float(world[0]),
                    y            = float(world[1]),
                    z            = float(world[2]),
                    strand_id    = strand_id or "",
                    helix_id     = src_key[0],
                    bp_index     = src_key[1],
                    direction    = src_key[2],
                    aux_helix_id = dst_key[0],
                    aux_t        = _aux_t,
                    crossover_id = xo.id,
                    extra_base_k = i - 1,
                ))
                base_name_to_serial[atom_name] = serial
                serial += 1

            # ── Glycosidic bond alignment ─────────────────────────────────────
            # Rotate ribose + base as a rigid body about C2′ so that the
            # C1′→N bond aligns with target_c1n (±avg_axis).
            # Anchors excluded from rotation: P, OP1, OP2, O5′ (phosphate group).
            _glycosidic_n = "N9" if residue in ("DA", "DG") else "N1"
            _n_serial  = base_name_to_serial.get(_glycosidic_n)
            _c1_serial = sugar_name_to_serial.get("C1'")
            _c2_serial = sugar_name_to_serial.get("C2'")
            if _n_serial is not None and _c1_serial is not None and _c2_serial is not None:
                _c1_pos  = _atom_pos(atoms, _c1_serial)
                _n_pos   = _atom_pos(atoms, _n_serial)
                _c2_pos  = _atom_pos(atoms, _c2_serial)
                _c1n_dir = _normalise(_n_pos - _c1_pos)
                _rot_ax  = _np.cross(_c1n_dir, target_c1n)
                _sin_t   = float(_np.linalg.norm(_rot_ax))
                _cos_t   = float(_np.dot(_c1n_dir, target_c1n))
                if _sin_t < 1e-9:
                    if _cos_t < 0.0:
                        # 180° rotation — pick an arbitrary perpendicular axis
                        _perp = _np.array([0.0, 0.0, 1.0])
                        if abs(float(_np.dot(_c1n_dir, _perp))) > 0.9:
                            _perp = _np.array([1.0, 0.0, 0.0])
                        _rot_ax  = _normalise(_np.cross(_c1n_dir, _perp))
                        _R_align = 2.0 * _np.outer(_rot_ax, _rot_ax) - _np.eye(3)
                    else:
                        _R_align = _np.eye(3)
                else:
                    _k = _rot_ax / _sin_t
                    _K = _np.array([
                        [ 0.0,   -_k[2],  _k[1]],
                        [ _k[2],  0.0,   -_k[0]],
                        [-_k[1],  _k[0],  0.0  ],
                    ])
                    _R_align = _np.eye(3) + _sin_t * _K + (1.0 - _cos_t) * (_K @ _K)
                _phosphate = {"P", "OP1", "OP2", "O5'"}
                for _aname, _s in sugar_name_to_serial.items():
                    if _aname not in _phosphate:
                        _p_rel = _atom_pos(atoms, _s) - _c2_pos
                        _set_atom_pos(atoms, _s, _c2_pos + _R_align @ _p_rel)
                for _aname, _s in base_name_to_serial.items():
                    if _aname not in sugar_name_to_serial:
                        _p_rel = _atom_pos(atoms, _s) - _c2_pos
                        _set_atom_pos(atoms, _s, _c2_pos + _R_align @ _p_rel)

            # ── Intra-residue bonds ───────────────────────────────────────────
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

            # Store full sugar+base serial dict so the rigid body includes base atoms
            eb_sugar_serials.append(dict(base_name_to_serial))
            eb_glycosidic_ns.append(_glycosidic_n)

        # ── Inter-residue backbone bonds through the extra-base chain ─────────
        # O3′(junction_a) → P(eb_1) → … → O3′(eb_n) → P(junction_b)
        all_s: list[dict[str, int]] = []
        if src_s:
            all_s.append(src_s)
        all_s.extend(eb_sugar_serials)
        if dst_s:
            all_s.append(dst_s)

        for prev_s_item, next_s_item in zip(all_s, all_s[1:]):
            o3 = prev_s_item.get("O3'")
            p  = next_s_item.get("P")
            if o3 is not None and p is not None:
                bonds.append((o3, p))

        # ── Collect minimisation job (run in parallel below) ─────────────────
        # Build a geometry-keyed cache entry so scipy is not re-run when the
        # atomistic view is toggled off and on without design changes.
        _rnd4 = lambda v: tuple(round(float(_x), 4) for _x in v)
        _cache_key: "tuple | None" = (
            xo.id, xo.extra_bases,
            _rnd4(line_p0), _rnd4(line_p1), _rnd4(target_c1n),
        ) if (src_s is not None and dst_s is not None) else None

        # When the inserts carry REAL simulated positions (relaxed-display /
        # trajectory ``xb_pos_override``), those positions are authoritative — skip
        # the scipy bridge minimisation, which would otherwise re-seat the whole
        # insert onto the geometric junction arc and discard the simulated pose.
        _xb_overridden = (xb_pos_override is not None
                          and (xo.id, 0) in xb_pos_override)
        if _xb_overridden:
            pass
        elif n == 1 and src_s is not None and dst_s is not None:
            _mini_jobs.append(_functools.partial(
                _minimize_1_extra_base,
                atoms, src_s, dst_s, eb_sugar_serials[0],
                eb_glycosidic_ns[0], target_c1n, repel_pos,
                cache_key=_cache_key,
            ))
        elif n == 2 and src_s is not None and dst_s is not None:
            _mini_jobs.append(_functools.partial(
                _minimize_2_extra_base,
                atoms, src_s, dst_s,
                eb_sugar_serials[0], eb_sugar_serials[1],
                eb_glycosidic_ns[0], eb_glycosidic_ns[1],
                target_c1n, repel_pos,
                cache_key=_cache_key,
            ))
        elif n == 3 and src_s is not None and dst_s is not None:
            _mini_jobs.append(_functools.partial(
                _minimize_3_extra_base,
                atoms, src_s, dst_s,
                eb_sugar_serials[0], eb_sugar_serials[1], eb_sugar_serials[2],
                eb_glycosidic_ns[0], eb_glycosidic_ns[1], eb_glycosidic_ns[2],
                target_c1n, repel_pos,
                cache_key=_cache_key,
            ))
        else:
            # Fallback for >3 extra bases: sequential per-pair bridge
            for prev_s_item, next_s_item in zip(all_s, all_s[1:]):
                _minimize_backbone_bridge(atoms, prev_s_item, next_s_item)

    # ── Run all minimisation jobs ─────────────────────────────────────────────
    # Single crossover: no thread overhead.  Multiple: run in parallel (each job
    # operates on a disjoint set of atom serials, so no locking is needed on
    # atom reads/writes).  scipy releases the GIL during BLAS calls, giving true
    # parallelism on multi-core machines.
    if len(_mini_jobs) == 1:
        _mini_jobs[0]()
    elif len(_mini_jobs) > 1:
        with _ThreadPoolExecutor(max_workers=min(len(_mini_jobs), 4)) as pool:
            futures = [pool.submit(job) for job in _mini_jobs]
            for fut in futures:
                fut.result()   # re-raise any exception from the worker

    return serial


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
                "helix_id":     a.helix_id,
                "bp_index":     a.bp_index,
                "direction":    a.direction,
                "is_modified":  a.is_modified,
                "aux_helix_id": a.aux_helix_id,
                "aux_t":        a.aux_t,
                "crossover_id": a.crossover_id,
                "extra_base_k": a.extra_base_k,
            }
            for a in model.atoms
        ],
        "bonds": [[i, j] for i, j in model.bonds],
        "element_meta": _element_meta(model),
    }


def _element_meta(model: AtomisticModel) -> dict:
    """Per-element vdw radius + CPK colour for every element present in *model*.

    Always includes the four DNA elements (P/C/N/O) so existing consumers keep
    their keys; adds entries for any other element actually present (e.g. S in
    proteins), falling back to grey/mid-radius for unknowns.
    """
    elements = set(VDW_RADIUS) | {a.element for a in model.atoms}
    return {
        el: {
            "vdw_radius": VDW_RADIUS.get(el, DEFAULT_VDW_RADIUS),
            "cpk_color": CPK_COLOR.get(el, DEFAULT_CPK_COLOR),
        }
        for el in elements
    }


def atomistic_positions_flat(model: AtomisticModel) -> list[float]:
    """Return a flat [x0,y0,z0, x1,y1,z1, ...] array indexed by atom serial.

    Used by the animation batch endpoint to send compact per-frame position data
    without re-sending all atom metadata.  The frontend lerps between two such
    arrays and applies them via atomistic_renderer.applyPositionLerp().
    """
    atom_count = len(model.atoms)
    result = [0.0] * (atom_count * 3)
    for a in model.atoms:
        idx = a.serial * 3
        result[idx]     = round(a.x, 5)
        result[idx + 1] = round(a.y, 5)
        result[idx + 2] = round(a.z, 5)
    return result
