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
    _minimize_backbone_bridge,
    _set_atom_pos,
)
from backend.core.constants import BDNA_MINOR_GROOVE_ANGLE_RAD, BDNA_RISE_PER_BP
from backend.core.geometry import (
    NucleotidePosition,
    nucleotide_positions,
    site_from_bead as _site_from_bead,
    site_from_beads_arrays as _site_from_beads_arrays,
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
    "P": 0xFF8C00,  # orange
    "C": 0x505050,  # dark grey
    "N": 0x3050F8,  # blue
    "O": 0xFF0D0D,  # red
    "S": 0xFFFF30,  # yellow
    "H": 0xFFFFFF,  # white
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
    ("P", "P", -0.1020, 0.1588, 0.2560),
    ("OP1", "O", -0.2263, 0.1547, 0.3352),
    ("OP2", "O", -0.0584, 0.0376, 0.1803),
    ("O5'", "O", -0.0629, 0.2645, 0.1684),
    ("C5'", "C", -0.0543, 0.4005, 0.2139),
    ("C4'", "C", 0.0331, 0.4838, 0.1220),
    ("O4'", "O", 0.1733, 0.4481, 0.1316),
    ("C3'", "C", -0.0013, 0.4772, -0.0269),
    ("O3'", "O", -0.0605, 0.5756, -0.1253),
    ("C2'", "C", 0.1079, 0.3896, -0.0850),
    ("C1'", "C", 0.2248, 0.4334, 0.0000),
)

# ── Intra-residue bond table (by atom name pairs) ─────────────────────────────
# Used to build the per-residue bond list.  Inter-residue backbone bonds
# (O3′ → next P) are added during build_atomistic_model().

_SUGAR_BONDS: tuple[tuple[str, str], ...] = (
    ("P", "OP1"),
    ("P", "OP2"),
    ("P", "O5'"),
    ("O5'", "C5'"),
    ("C5'", "C4'"),
    ("C4'", "O4'"),
    ("C4'", "C3'"),
    ("O4'", "C1'"),
    ("C3'", "O3'"),
    ("C3'", "C2'"),
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
    ("N1", "N", 0.3323, 0.3376, -0.0216),
    ("C2", "C", 0.4595, 0.3874, -0.0278),
    ("O2", "O", 0.4844, 0.5044, -0.0154),
    ("N3", "N", 0.5569, 0.2956, -0.0491),
    ("C4", "C", 0.5402, 0.1621, -0.0638),
    ("O4", "O", 0.6374, 0.0912, -0.0824),
    ("C5", "C", 0.4043, 0.1167, -0.0557),
    ("C6", "C", 0.3080, 0.2053, -0.0356),
    ("C7", "C", 0.3775, -0.0261, -0.0697),
)

_DT_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"),
    ("N1", "C2"),
    ("C2", "N3"),
    ("N3", "C4"),
    ("C4", "C5"),
    ("C5", "C6"),
    ("C6", "N1"),
    ("C2", "O2"),
    ("C4", "O4"),
    ("C5", "C7"),
)

# ── Cytosine (DC) ─────────────────────────────────────────────────────────────

_DC_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A DC residue A:4 (single residue, only DC available).
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation −13.031° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N", 0.3036, 0.3102, -0.0184),
    ("C2", "C", 0.4417, 0.3222, -0.0336),
    ("O2", "O", 0.4927, 0.4348, -0.0267),
    ("N3", "N", 0.5162, 0.2113, -0.0550),
    ("C4", "C", 0.4574, 0.0919, -0.0605),
    ("N4", "N", 0.5344, -0.0146, -0.0837),
    ("C5", "C", 0.3168, 0.0765, -0.0426),
    ("C6", "C", 0.2444, 0.1874, -0.0220),
)

_DC_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N1"),
    ("N1", "C2"),
    ("C2", "N3"),
    ("N3", "C4"),
    ("C4", "C5"),
    ("C5", "C6"),
    ("C6", "N1"),
    ("C2", "O2"),
    ("C4", "N4"),
)

# ── Adenine (DA) ──────────────────────────────────────────────────────────────

_DA_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A inner DA residues A:6, A:8.
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation +2.255° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N", 0.3294, 0.3340, -0.0197),
    ("C8", "C", 0.3150, 0.1998, -0.0436),
    ("N7", "N", 0.4280, 0.1362, -0.0562),
    ("C5", "C", 0.5236, 0.2354, -0.0393),
    ("C4", "C", 0.4641, 0.3576, -0.0173),
    ("N3", "N", 0.5259, 0.4751, 0.0026),
    ("C2", "C", 0.6577, 0.4597, -0.0013),
    ("N1", "N", 0.7290, 0.3488, -0.0211),
    ("C6", "C", 0.6635, 0.2325, -0.0405),
    ("N6", "N", 0.7341, 0.1216, -0.0589),
)

_DA_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9", "C8"),
    ("C8", "N7"),
    ("N7", "C5"),
    ("C5", "C4"),
    ("C4", "N9"),  # 5-ring
    ("C4", "N3"),
    ("N3", "C2"),
    ("C2", "N1"),
    ("N1", "C6"),
    ("C6", "C5"),  # 6-ring
    ("C6", "N6"),
)

# ── Guanine (DG) ──────────────────────────────────────────────────────────────

_DG_BASE: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain A DG residue A:7 (single residue, only DG available).
    # NADOC synthetic frame (34.3°/bp, 0.334 nm/bp).  C1′ z = 0 convention.
    # Rigid-body rotation +16.962° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N", 0.3499, 0.3595, 0.0046),
    ("C8", "C", 0.3675, 0.2235, 0.0094),
    ("N7", "N", 0.4934, 0.1882, 0.0109),
    ("C5", "C", 0.5625, 0.3088, 0.0071),
    ("C4", "C", 0.4750, 0.4149, 0.0034),
    ("N3", "N", 0.5027, 0.5468, -0.0009),
    ("C2", "C", 0.6323, 0.5701, -0.0006),
    ("N2", "N", 0.6768, 0.6966, -0.0027),
    ("N1", "N", 0.7279, 0.4717, 0.0024),
    ("C6", "C", 0.7020, 0.3352, 0.0063),
    ("O6", "O", 0.7954, 0.2550, 0.0088),
)

_DG_BONDS: tuple[tuple[str, str], ...] = (
    ("C1'", "N9"),
    ("N9", "C8"),
    ("C8", "N7"),
    ("N7", "C5"),
    ("C5", "C4"),
    ("C4", "N9"),  # 5-ring
    ("C4", "N3"),
    ("N3", "C2"),
    ("C2", "N1"),
    ("N1", "C6"),
    ("C6", "C5"),  # 6-ring
    ("C6", "O6"),
    ("C2", "N2"),
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
    ("N1", "N", 0.3496, 0.3665, -0.0261),
    ("C2", "C", 0.4634, 0.4436, -0.0334),
    ("O2", "O", 0.4649, 0.5642, -0.0229),
    ("N3", "N", 0.5762, 0.3735, -0.0534),
    ("C4", "C", 0.5866, 0.2378, -0.0667),
    ("O4", "O", 0.6958, 0.1884, -0.0818),
    ("C5", "C", 0.4633, 0.1636, -0.0602),
    ("C6", "C", 0.3525, 0.2311, -0.0410),
    ("C7", "C", 0.4647, 0.0158, -0.0747),
)

_DC_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B DC residue B:14 (single residue, only DC available).
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation −36.459° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N1", "N", 0.3085, 0.3159, -0.0303),
    ("C2", "C", 0.4427, 0.3362, -0.0634),
    ("O2", "O", 0.4866, 0.4517, -0.0667),
    ("N3", "N", 0.5210, 0.2297, -0.0911),
    ("C4", "C", 0.4700, 0.1062, -0.0866),
    ("N4", "N", 0.5510, 0.0041, -0.1146),
    ("C5", "C", 0.3335, 0.0825, -0.0536),
    ("C6", "C", 0.2568, 0.1893, -0.0265),
)

_DA_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B inner DA residues B:16, B:18.
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation +0.997° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N", 0.3501, 0.3637, -0.0302),
    ("C8", "C", 0.3649, 0.2310, -0.0607),
    ("N7", "N", 0.4892, 0.1941, -0.0782),
    ("C5", "C", 0.5614, 0.3104, -0.0588),
    ("C4", "C", 0.4769, 0.4161, -0.0309),
    ("N3", "N", 0.5126, 0.5431, -0.0078),
    ("C2", "C", 0.6452, 0.5565, -0.0150),
    ("N1", "N", 0.7387, 0.4644, -0.0400),
    ("C6", "C", 0.6995, 0.3375, -0.0624),
    ("N6", "N", 0.7927, 0.2449, -0.0861),
)

_DG_BASE_REV: tuple[_AtomDef, ...] = (
    # C1′-referenced. 1ZEW chain B DG residue B:17 (single residue, only DG available).
    # NADOC synthetic REV frame (_atom_frame +58.2° P-P correction).  C1′ z = 0.
    # Rigid-body rotation −10.173° around C1′ (z-axis) from Entry 4 (equidistant WC).
    ("N9", "N", 0.3494, 0.3590, 0.0079),
    ("C8", "C", 0.3648, 0.2232, -0.0015),
    ("N7", "N", 0.4886, 0.1847, 0.0126),
    ("C5", "C", 0.5591, 0.3026, 0.0319),
    ("C4", "C", 0.4744, 0.4109, 0.0288),
    ("N3", "N", 0.5044, 0.5416, 0.0434),
    ("C2", "C", 0.6339, 0.5607, 0.0621),
    ("N2", "N", 0.6814, 0.6847, 0.0781),
    ("N1", "N", 0.7261, 0.4595, 0.0666),
    ("C6", "C", 0.6973, 0.3244, 0.0523),
    ("O6", "O", 0.7880, 0.2414, 0.0588),
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
BASE_TEMPLATES_REV: dict[
    str, tuple[tuple[_AtomDef, ...], tuple[tuple[str, str], ...]]
] = {
    "DA": (_DA_BASE_REV, _DA_BONDS),
    "DT": (_DT_BASE_REV, _DT_BONDS),
    "DG": (_DG_BASE_REV, _DG_BONDS),
    "DC": (_DC_BASE_REV, _DC_BONDS),
}

_BASE_CHAR_TO_RESIDUE: dict[str, str] = {
    "A": "DA",
    "T": "DT",
    "G": "DG",
    "C": "DC",
    "a": "DA",
    "t": "DT",
    "g": "DG",
    "c": "DC",
}

# ── Output dataclass ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class Atom:
    serial: int
    name: str
    element: str
    residue: str  # DA / DT / DG / DC
    chain_id: str  # A / B / C … (one per strand, wrapping at Z)
    seq_num: int  # 1-based residue number within chain
    x: float  # nm, world frame
    y: float
    z: float
    strand_id: str
    helix_id: str
    bp_index: int
    direction: str  # "FORWARD" | "REVERSE"
    is_modified: bool = False
    # Extra-crossover-base interpolation (empty / 0.0 for regular nucleotides)
    aux_helix_id: str = ""  # destination helix for extra-base lerp during Q expansion
    aux_t: float = 0.0  # lerp weight 0→1 (src helix → aux_helix_id)
    # Extra-crossover-base identity (None for regular nucleotides).  The stored
    # helix_id/bp_index/direction stay the SOURCE nucleotide's key (so the topology
    # writers are unchanged); these let the relaxed-display reconstruction and the MD
    # P-atom mapping address each insert as ``("__xb__", crossover_id, extra_base_k)``.
    crossover_id: Optional[str] = None
    extra_base_k: Optional[int] = None
    # Intra-helix loop-insertion identity (None/0 for regular nucleotides).  A ``+1``
    # loop emits a SECOND nucleotide sharing this atom's (helix_id, bp_index, direction);
    # ``copy_k`` (geometry emission order, 0 = base) disambiguates the copies so the MD
    # P-atom mapping can address each via ``(helix_id, bp_index, direction, copy_k)``
    # instead of collapsing them (the analogue of ``extra_base_k`` for crossover inserts).
    copy_k: Optional[int] = None
    # Strand-extension tail identity (None for regular nucleotides).  Like the
    # extra-base fields above, the stored helix_id/bp_index/direction remain the
    # ANCHOR nucleotide's key so the existing topology writers are unchanged; these
    # let the display + MD P-atom mapping address each tail base as
    # ``("__ext_<id>", ext_k, direction)`` — the same key the oxDNA walk emits.
    extension_id: Optional[str] = None
    ext_k: Optional[int] = None


@dataclass
class AtomisticModel:
    atoms: list[Atom]
    bonds: list[tuple[int, int]]  # 0-based serial pairs


def merge_models(*models: AtomisticModel) -> AtomisticModel:
    """Merge multiple AtomisticModels into one, renumbering serials."""
    atoms: list[Atom] = []
    bonds: list[tuple[int, int]] = []
    offset = 0
    for model in models:
        if not model.atoms:
            continue
        for a in model.atoms:
            atoms.append(
                Atom(
                    serial=a.serial + offset,
                    name=a.name,
                    element=a.element,
                    residue=a.residue,
                    chain_id=a.chain_id,
                    seq_num=a.seq_num,
                    x=a.x,
                    y=a.y,
                    z=a.z,
                    strand_id=a.strand_id,
                    helix_id=a.helix_id,
                    bp_index=a.bp_index,
                    direction=a.direction,
                    is_modified=a.is_modified,
                    aux_helix_id=a.aux_helix_id,
                    aux_t=a.aux_t,
                    crossover_id=a.crossover_id,
                    extra_base_k=a.extra_base_k,
                    copy_k=getattr(a, "copy_k", None),
                    extension_id=getattr(a, "extension_id", None),
                    ext_k=getattr(a, "ext_k", None),
                )
            )
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
    if ref.topology_hash and ref.topology_hash != atomistic_reference_topology_hash(
        design
    ):
        return None

    atoms: list[Atom] = []
    old_to_new: dict[int, int] = {}
    for ref_atom in ref.atoms:
        if exclude_helix_ids and ref_atom.helix_id in exclude_helix_ids:
            continue
        new_serial = len(atoms)
        old_to_new[int(ref_atom.serial)] = new_serial
        atoms.append(
            Atom(
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
                copy_k=getattr(ref_atom, "copy_k", None),
                extension_id=getattr(ref_atom, "extension_id", None),
                ext_k=getattr(ref_atom, "ext_k", None),
            )
        )

    bonds: list[tuple[int, int]] = []
    for i, j in ref.bonds:
        ni = old_to_new.get(int(i))
        nj = old_to_new.get(int(j))
        if ni is not None and nj is not None:
            bonds.append((ni, nj))
    return AtomisticModel(atoms=atoms, bonds=bonds)


# ── Frame constants ───────────────────────────────────────────────────────────
# _FRAME_ROT_RAD un-rotates the frame by the +37.05° pre-compensation baked into the
# template literals (_SUGAR, BASE_TEMPLATES, BASE_TEMPLATES_REV).
#
# ⚠ It is NOT a no-op, and a previous version of this comment claiming "net effect = 0°"
# read as an invitation to delete it.  The PAIR (rotated frame × pre-rotated templates)
# is the no-op; the constant alone is load-bearing.  It is applied as R = R @ Rz(θ), i.e.
# it DEFINES the local frame the template coordinates are quoted in, so removing it
# without re-quoting them rotates every nucleotide ∓37° about its own helix axis (e_z
# flips sign by strand).  It also cannot be folded into _ATOMISTIC_PHASE_OFFSET_RAD: that
# one rotates the frame ORIGIN about the HELIX axis and is strand-symmetric, this one
# rotates the BASIS about the frame's own z and is strand-ANTI-symmetric.
#
# Retiring it means, in ONE commit: re-quoting ~300 1ZEW coordinates at full precision
# AND dropping the same factor from _extra_base_frame (the third application site).  That
# is blocked on the extra-base and strand-extension tail placers, which are calibrated
# against these templates' local origin.  Tracked as TD-27; listed as locked alongside
# the _PHASE_* constants in atomistic_minimisers.py.
_FRAME_ROT_RAD: float = -0.646577  # −37.05° (template pre-compensation cancel)

# Built once instead of at each of the three application sites (_atom_frame,
# _atom_frames_batch, _extra_base_frame), so they cannot drift apart.  Read-only: it is
# only ever the right operand of `R @ _FRAME_ROT_M`.
_FRAME_ROT_M: "_np.ndarray" = _np.array(
    [
        [_math.cos(_FRAME_ROT_RAD), -_math.sin(_FRAME_ROT_RAD), 0.0],
        [_math.sin(_FRAME_ROT_RAD), _math.cos(_FRAME_ROT_RAD), 0.0],
        [0.0, 0.0, 1.0],
    ]
)
_FRAME_ROT_M.setflags(write=False)

# The geometric layer places backbone beads at HELIX_RADIUS (1.0 nm).
# Correcting to _ATOMISTIC_P_RADIUS places the radial frame origin at the
# real P-to-axis distance measured from 1ZEW inner residues.
_ATOMISTIC_P_RADIUS: float = (
    0.886  # nm  (measured mean P-to-axis from 1ZEW inner residues)
)

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
_ATOMISTIC_PP_SEP_RAD: float = _math.radians(208.2)  # 1ZEW empirical mean
# The topology-layer groove constant, imported rather than re-declared: a local
# `radians(150.0)` would silently keep 150° if constants.py ever moved, rotating every
# REVERSE nucleotide by the difference.
_ATOMISTIC_TOPOLOGY_GROOVE_RAD: float = BDNA_MINOR_GROOVE_ANGLE_RAD

# The per-lattice-cell REVERSE-P corrections, derived once instead of at every call site.
# Both _atom_frame (scalar) and _atom_frames_batch (vectorised) consume these, which is
# what keeps the two implementations of the correction chain from drifting apart.
_REV_P_DELTA_FWD_CELL: float = _ATOMISTIC_PP_SEP_RAD - _ATOMISTIC_TOPOLOGY_GROOVE_RAD
"""+58.2° — FORWARD-cell helices place REV P at fwd+150°; target is fwd+208.2°."""
_REV_P_DELTA_REV_CELL: float = _ATOMISTIC_PP_SEP_RAD - (
    2 * _math.pi - _ATOMISTIC_TOPOLOGY_GROOVE_RAD
)
"""−1.8° — REVERSE-cell (and direction-unknown) helices place REV P at fwd+210°."""

# ── Atomistic phase offset ────────────────────────────────────────────────────
# Rigid-body rotation of every nucleotide about its helix axis, applied after
# all P azimuthal corrections.  Rotates e_radial (moving the frame origin and
# co-rotating e_n/e_y) so all atoms in the template orbit the axis as one body.
#
# ⚠ RE-JUSTIFIED 2026-08-07 — the value did not change, its reason did.  It used to read
# "calibrated by overlaying the atomistic model on the NADOC bead/slab representation:
# −32° aligns the backbone groove phase of the all-atom model with the coarse-grained
# model at phase_offset=0", i.e. the DISPLAY deciding where atoms go.  Under
# atomistic-as-ground-truth that is not a justification, so it was checked against the
# only measurement that can settle it: the crossover-backbone azimuth of equilibrated
# free-NAMD origami (`scripts/measure_interhelix_phase.py` — the azimuth of the crossing
# phosphate about its own helix axis, 0° = the inter-helix direction).
#
# On `workspace/18hb.nadoc`, 1420 crossover measurements in that exact convention:
#
#   roll                       φ mean     R      |φ| median
#   −32° alone                 +5.72     0.920     15.68
#   −32° + junction balance    −1.22     0.924     21.53   ← what ships
#   junction balance alone    +13.93     0.896      3.48
#   MD (free NAMD, 18hb)       +7.30       —       19.10
#
# So −32° is 1.6° from the MD mean and the value stands on ITS OWN atomistic evidence.
#
# ⚠ The number that is NOT settled is the TOTAL.  `atomistic_phase_offset_rad` adds the
# measured DX-junction balance (−14.6° on honeycomb), which takes the crossover azimuth
# 8.5° to the far side of the MD mean.  Two measured criteria disagree by 14.6°: junction
# linker SYMMETRY (user-reported, fixed by the balance roll) and equilibrium crossover
# AZIMUTH (best near −32°).  They measure different things — a built structure's local linker
# strain versus where relaxed DNA settles.
#
# SETTLED 2026-08-07, owner decision: symmetry-first, i.e. this total stays.  The balanced
# build is the one inspected in the app on both lattices; MD-first (≈−38.1°) was rejected
# because it gives back roughly half the 0.500 nm junction-gap asymmetry.  This is a
# decision, not an accident — do NOT "fix" the 8.5° against MD.
# `test_the_atomistic_crossover_azimuth_stays_in_the_md_envelope` is deliberately loose so it
# guards the physical range without re-litigating it.
#
# NOT the same constant as `_FRAME_ROT_RAD`, and not gated on it: this rotates e_radial
# (orbiting the whole nucleotide about the helix axis), `_FRAME_ROT_M` post-multiplies the
# frame (spinning the template in place, origin fixed).  Retiring _FRAME_ROT_RAD needs
# ~300 template coordinates re-quoted; re-justifying this one needed a measurement.
_ATOMISTIC_PHASE_OFFSET_RAD: float = _math.radians(-32.0)

# ── Junction-balance roll for the ATOMISTIC rep (2026-08-07) ──────────────────
#
# Same defect as the full rep's `constants.FULL_REP_BALANCE_ROLL_*`, in the layer that is
# the source of truth: the two crossovers of a DX junction (bp i and i+1 between one helix
# pair) did not have equal geometry, so one phosphodiester linker of every pair was drawn
# and EXPORTED badly overstretched.  User-visible, user-reported on honeycomb.
#
# Measured on the anchor gap the linker has to span, C3'(src)→C5'(dst) — never on the
# O3'-P bond, which `_minimize_backbone_bridge` places between those fixed anchors and so
# reports a junction as balanced (0.204/0.217) when its anchors are 0.694/0.746
# (LESSONS H15/H19: never measure through a minimiser).  Canonical span ≈ 0.394 nm;
# `_PHOSPHODIESTER_LINKER_CONTOUR_NM` = 0.606 is the stretched limit.
#
#   honeycomb, roll 0 : 0.586 / 1.086 nm  (the 1.086 is what the user saw)
#   square,    roll 0 : 0.694 / 0.746 nm
#
# The balance point is the roll where the pair is equal, which is also where the WORST of
# the two is smallest.  Measured per design: honeycomb −14.602° / −14.747°; square
# −1.327° / −1.526° / −1.445°.  Both lattices then land on the same gap (0.724 / 0.719),
# and both linkers of a pair are equally, mildly over contour instead of one being 0.48 nm
# over.  The residual 0.3° spread between designs is sequence-dependent (per-residue
# templates) and worth 0.012 nm — against the 0.500 nm imbalance it removes.
#
# Expressed as ONE measured quantity rather than two per-lattice numbers, because it IS
# one: the atomistic balance sits a CONSTANT 14.6° off the full rep's on both lattices
# (honeycomb 14.60/14.75, square 14.45/14.65/14.57 — mean 14.61, spread 0.3°).  That
# offset is the measured template's 130.2° C3'-C3' separation against the CG layer's ±150°
# lattice groove, i.e. a property of the TEMPLATE convention, not of the lattice.  So the
# atomistic roll follows the full rep's constant automatically:
#
#     atomistic_roll(lattice) = FULL_REP_BALANCE_ROLL[lattice] − 14.6°
#
# ⚠ This moves ATOMS: the all-atom display, the PDB/PSF exports and the NAMD/GROMACS seeds
# all shift.  That is the point — they are the ground truth and they were wrong.  The CG
# layer is NOT touched, so the oxDNA / mrDNA / LAMMPS seeds and every pose fitter are
# byte-identical; rolling the SHARED phase instead would have put half of every design's
# crossover bonds over the FENE cliff (measured: honeycomb 114/228, square 305/610).
_ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG: float = 14.6


def atomistic_phase_offset_rad(design: "Design") -> float:
    """The total rigid roll every nucleotide gets, including the junction balance.

    ``_ATOMISTIC_PHASE_OFFSET_RAD`` alone is the historical CG-alignment constant; the
    second term is what makes the two crossovers of a DX junction equal.  See
    ``_ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG`` for the measurement and why it is one
    constant rather than one per lattice.
    """
    from backend.core.constants import (
        FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG, FULL_REP_BALANCE_ROLL_SQUARE_DEG,
    )
    from backend.core.models import LatticeType
    full_rep_deg = (FULL_REP_BALANCE_ROLL_SQUARE_DEG
                    if design.lattice_type == LatticeType.SQUARE
                    else FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG)
    return _ATOMISTIC_PHASE_OFFSET_RAD + _math.radians(
        full_rep_deg - _ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG)


_PHOSPHODIESTER_LINKER_CONTOUR_NM: float = 0.606  # C3'-O3'-P-O5'-C5' contour length


def _native_local_defs(residue: str, dir_str: str):
    """MD-measured template for one (residue, strand), in ``_atom_frame``-local coords.

    The measured placement is NATIVE: this is what NADOC draws and what it exports to
    every simulation, and the 1ZEW-derived ``_SUGAR``/``BASE_TEMPLATES`` below survive
    only as the comparison the Help ▸ New Positioning toggle switches back to.

    Returned in the LEGACY frame's local coordinates on purpose.  The legacy frame is a
    fixed rigid transform of the measured base-pair frame (proved exactly — it is even
    independent of lattice cell type), so every path that already builds a frame with
    ``_atom_frame`` / ``_atom_frames_batch`` and stamps a fixed template becomes
    measured-native by swapping these numbers in, with no frame changes at all.
    Round-trip against the direct base-pair-frame stamp: 5.7e-16 nm.

    Returns ``None`` if the measured data file is unavailable, so every caller degrades
    to the legacy templates rather than failing.
    """
    from backend.core import measured_atomistic as _ma

    try:
        sugar, base = _ma.legacy_local_templates()[(dir_str, residue)]
    except (_ma.MeasuredTemplateUnavailable, KeyError):
        return None
    return list(sugar) + list(base)


def _cross3(a, b):
    """Cross product of two 3-vectors — the SAME arithmetic ``np.cross`` performs, without
    its generic-axis dispatch.

    ``np.cross`` is written for arbitrary shapes/axes: every call runs ``moveaxis`` and
    ``normalize_axis_tuple`` before doing three multiplies. On (3,) inputs that overhead
    dwarfs the arithmetic. Profiling one export frame of a 16k-nt design (330k atoms) showed
    57,500 such calls costing ~3.0 s of the 7 s frame — ~2.1 s of it inside moveaxis and
    normalize_axis_tuple alone.

    Bit-identical to ``np.cross`` for 3-vectors (identical IEEE ops in the same order), so it
    is a drop-in for the SCALAR call sites only. The batched ``(N,3)`` sites in this module
    (``_rot``'s Rodrigues term and the vectorised frame builder) still use ``np.cross``, where
    the dispatch cost is amortised across the whole array and the semantics differ.
    """
    a0, a1, a2 = a[0], a[1], a[2]
    b0, b1, b2 = b[0], b[1], b[2]
    return _np.array((a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0))


# ── Frame builder ─────────────────────────────────────────────────────────────


def _phase_invalidated(nuc_pos: "NucleotidePosition") -> "NucleotidePosition":
    """Drop the carried helical phase — the caller has moved this nucleotide.

    ``radial_hat`` / ``axis_point`` / ``azimuth_rad`` describe where LATTICE geometry put
    the nucleotide.  A CG position override (a relaxed oxDNA/mrDNA structure, a folded
    ssDNA seed) or a deformed axis override means that phase no longer describes this
    nucleotide, so the frame must go back to measuring the phase off the supplied bead —
    which is exactly what those overrides exist to control.  Forgetting this makes an
    override silently apply only its AXIAL component (caught by
    ``test_displaced_nucleotide_flags_backbone_and_hidden`` and four siblings).
    """
    import dataclasses as _dc
    return _dc.replace(nuc_pos, radial_hat=None, axis_point=None, azimuth_rad=None)


def _atom_frame(
    nuc_pos: NucleotidePosition,
    direction: Direction,
    axis_point: _np.ndarray | None = None,
    helix_direction: Direction | None = None,
    phase_rad: float | None = None,
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
        # TWO PRODUCERS, ONE SITE (project_helical_site.md).  Either the nucleotide carries
        # an ANALYTIC site — the phase geometry.py computed from the lattice — or it does
        # not, and the site is MEASURED off wherever the nucleotide actually is.  The stamp
        # places the P at its own radius from that site, identically either way.
        #
        # Neither branch reads the display bead as a PHASE carrier, which is what the stamp
        # used to do.  The measured branch reads a POSITION, which is the whole point of an
        # override: a relaxed oxDNA frame, an MD trajectory frame, a folded ssDNA seed, an
        # mrDNA read-back, or a nucleotide re-placed onto a deformed centreline.
        #
        # `axis_point` (the caller's) wins over `nuc_pos.axis_point` (geometry's): they are
        # the same for a lattice helix, and the deformed / axis_override paths legitimately
        # supply a different one.
        if nuc_pos.radial_hat is not None:
            e_radial = nuc_pos.radial_hat
            axial = float(_np.dot(nuc_pos.position - axis_point, nuc_pos.axis_tangent))
        else:
            e_radial, axial = _site_from_bead(
                nuc_pos.position, axis_point, nuc_pos.axis_tangent)
        if e_radial is not None:
            bb = axis_point + axial * nuc_pos.axis_tangent + _ATOMISTIC_P_RADIUS * e_radial

    # Correct the REVERSE strand P azimuthal angle to the real B-DNA value (1ZEW: 208.2°).
    # FORWARD helix topology places REV P at fwd+150° (CCW); target fwd+208.2° → +58.2°.
    # REVERSE helix topology places REV P at fwd−150° (= fwd+210° CCW); target fwd+208.2° → −1.8°.
    if direction == Direction.REVERSE and e_radial is not None:
        delta = (
            _REV_P_DELTA_FWD_CELL
            if helix_direction == Direction.FORWARD
            else _REV_P_DELTA_REV_CELL
        )
        if abs(delta) > 1e-9:
            ax = nuc_pos.axis_tangent
            cd, sd = _math.cos(delta), _math.sin(delta)
            bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
            e_radial = cd * e_radial + sd * _cross3(ax, e_radial)
            bb = bb_axial + _ATOMISTIC_P_RADIUS * e_radial

    # Phase offset: rotate e_radial around the helix axis by _ATOMISTIC_PHASE_OFFSET_RAD.
    # Moves the frame origin (P) along the circle at _ATOMISTIC_P_RADIUS and co-rotates
    # e_n/e_y so the entire nucleotide orbits the axis as a rigid body.
    phase = _ATOMISTIC_PHASE_OFFSET_RAD if phase_rad is None else phase_rad
    if e_radial is not None and abs(phase) > 1e-9:
        ax = nuc_pos.axis_tangent
        cc, ss = _math.cos(phase), _math.sin(phase)
        bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
        e_radial = cc * e_radial + ss * _cross3(ax, e_radial)
        bb = bb_axial + _ATOMISTIC_P_RADIUS * e_radial

    # e_n: inward radial (toward helix axis).  e_radial-based is parity-symmetric
    # across FORWARD/REVERSE; base_normal fallback used only without axis_point.
    e_n = -e_radial if e_radial is not None else nuc_pos.base_normal
    # e_z: 3′→5′ direction so O5′ is at +z and O3′ at −z in the template, which
    # preserves D-deoxyribose chirality when the same template is used for both
    # strand directions.
    e_z = (
        -nuc_pos.axis_tangent
        if direction == Direction.FORWARD
        else nuc_pos.axis_tangent
    )
    e_y = _cross3(e_z, e_n)
    norm = _np.linalg.norm(e_y)
    if norm < 1e-9:
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(_np.dot(e_n, fallback)) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        e_y = _cross3(e_z, fallback)
        norm = _np.linalg.norm(e_y)
    e_y /= norm

    # Origin at the radial-corrected (and phase-shifted) backbone bead.
    origin = bb
    R = _np.column_stack([e_n, e_y, e_z])

    # Cancel template pre-compensation (+37.05° baked into all templates).
    R = R @ _FRAME_ROT_M

    return origin, R


def _atom_frames_batch(
    pos: _np.ndarray, axt: _np.ndarray, base_normal: _np.ndarray,
    axis_pt: _np.ndarray, dir_fwd: _np.ndarray, helix_fwd: _np.ndarray,
    phase_rad: float | None = None,
    radial_hat: _np.ndarray | None = None,
) -> tuple[_np.ndarray, _np.ndarray]:
    """Vectorised :func:`_atom_frame` over N nucleotides at once — the SAME arithmetic on
    ``(N,3)`` stacks, so 37k tiny ``numpy.cross`` / ``normalize_axis_tuple`` calls collapse
    into a handful of array ops (the surface build's dominant cost).  Bit-identical to the
    scalar frame on real designs (pinned by ``test_surface_atom_cloud``); a per-row scalar
    fallback covers the rare degenerate rows (no axis point, zero radial, or a collinear
    e_z/e_n) so nothing silently drifts.

    Inputs (all length N; axis_pt rows may be NaN = "no axis point"):
      pos/axt/base_normal/axis_pt : (N,3)   ; dir_fwd/helix_fwd : (N,) bool
    Returns (origins (N,3), R (N,3,3)) matching ``_atom_frame``'s (origin, R) per row."""
    N = len(pos)
    bb = pos.astype(float).copy()
    axt = axt.astype(float)
    has_axis = ~_np.isnan(axis_pt[:, 0])
    measured, dot_rt, radial_ok = _site_from_beads_arrays(bb, axis_pt, axt)
    ok = has_axis & radial_ok                             # radial frame available
    e_radial = _np.where(ok[:, None], measured, 0.0)
    # The two producers, as in _atom_frame: the ANALYTIC site where one was carried, the
    # MEASURED site otherwise.  NaN rows carry no analytic phase.
    if radial_hat is not None:
        carried = ~_np.isnan(radial_hat[:, 0])
        e_radial = _np.where((ok & carried)[:, None], radial_hat, e_radial)
    bb = _np.where(ok[:, None], axis_pt + dot_rt[:, None] * axt + _ATOMISTIC_P_RADIUS * e_radial, bb)

    def _rot(er, ang_mask, ang):
        # Rotate e_radial about the axis tangent by `ang` (Rodrigues, ⟂ so no parallel term).
        c = _np.cos(ang)
        s = _np.sin(ang)
        rotated = c[:, None] * er + s[:, None] * _np.cross(axt, er)
        return _np.where(ang_mask[:, None], rotated, er)

    # REVERSE-strand P azimuthal correction (branch on the helix's lattice direction).
    delta = _np.where(helix_fwd, _REV_P_DELTA_FWD_CELL, _REV_P_DELTA_REV_CELL)
    m = ok & (~dir_fwd) & (_np.abs(delta) > 1e-9)
    if m.any():
        bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
        e_radial = _rot(e_radial, m, delta)
        bb = _np.where(m[:, None], bb_axial + _ATOMISTIC_P_RADIUS * e_radial, bb)

    # Rigid phase offset about the axis (all nucleotides).
    phase = _ATOMISTIC_PHASE_OFFSET_RAD if phase_rad is None else phase_rad
    if abs(phase) > 1e-9:
        bb_axial = bb - _ATOMISTIC_P_RADIUS * e_radial
        e_radial = _rot(e_radial, ok, _np.full(N, phase))
        bb = _np.where(ok[:, None], bb_axial + _ATOMISTIC_P_RADIUS * e_radial, bb)

    e_n = _np.where(ok[:, None], -e_radial, base_normal.astype(float))
    e_z = _np.where(dir_fwd[:, None], -axt, axt)
    e_y = _np.cross(e_z, e_n)
    y_norm = _np.linalg.norm(e_y, axis=1)
    degen = y_norm < 1e-9  # collinear e_z/e_n (rare)
    y_norm_safe = _np.where(degen, 1.0, y_norm)
    e_y = e_y / y_norm_safe[:, None]

    R = _np.stack([e_n, e_y, e_z], axis=2)  # per-row column_stack → (N,3,3)
    R = R @ _FRAME_ROT_M

    # Repair the rare rows the vectorised path can't express (no radial frame or a
    # degenerate e_y fallback) with the authoritative scalar frame — keeps parity exact.
    bad = (~ok) | degen
    if bad.any():
        from backend.core.geometry import NucleotidePosition

        for i in _np.nonzero(bad)[0]:
            ax_pt = None if _np.isnan(axis_pt[i, 0]) else axis_pt[i]
            npos = NucleotidePosition(
                helix_id="",
                bp_index=0,
                direction=Direction.FORWARD if dir_fwd[i] else Direction.REVERSE,
                position=pos[i],
                base_position=pos[i],
                base_normal=base_normal[i],
                axis_tangent=axt[i],
            )
            o_i, R_i = _atom_frame(
                npos,
                Direction.FORWARD if dir_fwd[i] else Direction.REVERSE,
                axis_point=ax_pt,
                helix_direction=Direction.FORWARD if helix_fwd[i] else Direction.REVERSE,
                phase_rad=phase_rad)
            bb[i] = o_i; R[i] = R_i
    return bb, R


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
    cm_nm: _np.ndarray,
    a1: _np.ndarray,
    a3: _np.ndarray,
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
    a2 = _cross3(a3, a1)
    F = _np.column_stack([a1, a2, a3])
    return F, oxdna_backbone_site(cm_nm, a1, a3)


@_functools.lru_cache(maxsize=1)
def _rigid_frame_calibration() -> dict:
    """Fit the constant rigid transform (Q rotation, c offset) per
    (strand_direction, helix_is_forward) bucket that maps an oxDNA particle frame to
    the all-atom template stamping build_atomistic_model produces.

    Method (empirical, machine-precision):  build a clean ideal duplex (no
    crossovers / insertions) spanning all four buckets, take each nucleotide's oxDNA
    particle frame (CM, a1, a3) straight from its HELICAL SITE, and read its
    KNOWN-GOOD atom placement from build_atomistic_model(design).  For each
    nucleotide recover (R_kg, origin_kg) by Kabsch between the template-local atom
    coordinates and the built world coordinates, then  Q = Fᵀ·R_kg,
    c = Fᵀ·(origin_kg − backbone_site).  Q is residue-independent (the frame is set
    by the sugar-phosphate, not the base) and constant within a bucket; we average
    + re-orthonormalise (SVD).  The 4-bucket split mirrors _atom_frame's only
    direction branches (the REVERSE-strand P azimuthal correction differs for a
    FORWARD helix vs a REVERSE/None helix).  Asserts the per-nucleotide residual is
    negligible, so a silent calibration drift can never ship.

    The frames used to come from writing an oxDNA .dat to a temp file and reading it back
    (project_helical_site.md Phase 6).  That round trip served only to turn CG geometry
    into (CM, a1, a3) — which the site gives directly — and it cost two things: the conf
    is text at ``%.6f`` oxDNA units, so every frame was QUANTISED to 8.5e-7 nm and that
    noise landed in the fit's own residual; and it made a cached constant depend on
    ``_geometry_for_design``, the DISPLAY serialiser, so a display-side default (measured
    re-placement, the junction-balance roll) could have moved the calibration.  Reading
    ``nucleotide_positions`` instead depends on the raw geometric layer and nothing else.
    """
    from backend.core.models import Helix, Strand, Domain, Vec3, Design, LatticeType

    L = 14
    rise = BDNA_RISE_PER_BP

    def _helix(idx: str, direction: Direction) -> Helix:
        return Helix(
            id=idx,
            direction=direction,
            length_bp=L,
            bp_start=0,
            axis_start=Vec3(x=float(idx_x[idx]), y=0.0, z=0.0),
            axis_end=Vec3(x=float(idx_x[idx]), y=0.0, z=L * rise),
        )

    idx_x = {"h0": 0.0, "h1": 3.0}
    helices = [_helix("h0", Direction.FORWARD), _helix("h1", Direction.REVERSE)]
    strands: list[Strand] = []
    # One forward + one reverse single-domain strand on each helix → all 4 buckets.
    for hid in ("h0", "h1"):
        strands.append(
            Strand(
                id=f"{hid}_f",
                strand_type=StrandType.SCAFFOLD,
                domains=[
                    Domain(
                        helix_id=hid,
                        start_bp=0,
                        end_bp=L - 1,
                        direction=Direction.FORWARD,
                    )
                ],
            )
        )
        strands.append(
            Strand(
                id=f"{hid}_r",
                strand_type=StrandType.STAPLE,
                domains=[
                    Domain(
                        helix_id=hid,
                        start_bp=L - 1,
                        end_bp=0,
                        direction=Direction.REVERSE,
                    )
                ],
            )
        )
    design = Design(
        helices=helices, strands=strands, lattice_type=LatticeType.HONEYCOMB
    )

    # The oxDNA particle frame, per nucleotide, exactly as `nuc_conf_line` defines it:
    # the conf's first three floats are the CM (the backbone bead), a1 is the base normal
    # and a3 runs 5'->3' (the axis tangent, negated on the REVERSE strand).
    frames: dict[tuple, dict] = {}
    for helix in design.helices:
        for n in nucleotide_positions(helix):
            a1 = n.base_normal / (_np.linalg.norm(n.base_normal) + 1e-14)
            a3 = (n.axis_tangent if n.direction == Direction.FORWARD else -n.axis_tangent)
            a3 = a3 / (_np.linalg.norm(a3) + 1e-14)
            frames[(helix.id, n.bp_index, n.direction.value)] = {
                "backbone_position": n.position, "a1": a1, "a3": a3,
            }

    model = build_atomistic_model(design)
    hdir = {h.id: h.direction for h in design.helices}

    # Group built atoms by nucleotide (helix, bp, dir); each carries .name/.residue.
    groups: dict[tuple, list] = {}
    for a in model.atoms:
        if a.helix_id is None or a.bp_index is None:
            continue
        groups.setdefault((a.helix_id, a.bp_index, a.direction), []).append(a)

    def _local(residue: str, direction: Direction) -> dict:
        # Must match whatever ``build_atomistic_model`` above actually stamped — the
        # calibration is a fit of the oxDNA rigid frame ONTO the built nucleotide, so
        # reading a different template here would bake the difference into the
        # calibration and the placer would stop reproducing the design build.
        defs = _native_local_defs(residue, direction.name)
        if defs is not None:
            return {n: _np.array([x, y, z]) for n, _e, x, y, z in defs}
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
        F, bb = _oxdna_frame_basis(
            frames[key]["backbone_position"], frames[key]["a1"], frames[key]["a3"]
        )
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
            f"rotation residual {m_res:.2e}, offset residual {c_res:.2e} nm"
        )
        calib[bucket] = (Q, cmean)
    return calib


def _oxdna_rigid_frame(
    cm_nm: _np.ndarray,
    a1: _np.ndarray,
    a3: _np.ndarray,
    direction: Direction,
    helix_direction: "Direction | None",
) -> tuple[_np.ndarray, _np.ndarray]:
    """Stamp position: return (origin, R) placing the nucleotide's template so its
    atoms land at the oxDNA-relaxed rigid pose (CM + a1/a3).  origin = backbone_site
    + F·c, R = F·Q with (Q, c) the calibrated per-bucket constant."""
    F, bb = _oxdna_frame_basis(
        _np.asarray(cm_nm, float), _np.asarray(a1, float), _np.asarray(a3, float)
    )
    Q, c = _rigid_frame_calibration()[
        (direction.value, helix_direction == Direction.FORWARD)
    ]
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
        key = frozenset(
            {
                (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value),
                (xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand.value),
            }
        )
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

    def _sugar_atom_world(
        helix_id: str, bp: int, direction: Direction, atom_name: str
    ) -> _np.ndarray | None:
        helix = helix_map.get(helix_id)
        nuc = pos_cache.get(helix_id, {}).get((bp, direction, 0))
        axis_info = axis_cache.get(helix_id)
        if helix is None or nuc is None or axis_info is None:
            return None
        axis_start, axis_hat, bp_start = axis_info
        axis_pt = axis_start + (bp - bp_start) * BDNA_RISE_PER_BP * axis_hat
        origin, R = _atom_frame(nuc, direction, axis_point=axis_pt,
                                helix_direction=helix.direction,
                                phase_rad=atomistic_phase_offset_rad(design))
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
                site_key = frozenset(
                    {
                        (
                            prev_domain.helix_id,
                            prev_domain.end_bp,
                            prev_domain.direction.value,
                        ),
                        (domain.helix_id, domain.start_bp, domain.direction.value),
                    }
                )
                xo = crossover_by_site.get(site_key)
                if xo is None:
                    prev_domain = domain
                    continue
                c3_src = _sugar_atom_world(
                    prev_domain.helix_id,
                    prev_domain.end_bp,
                    prev_domain.direction,
                    "C3'",
                )
                c5_dst = _sugar_atom_world(
                    domain.helix_id,
                    domain.start_bp,
                    domain.direction,
                    "C5'",
                )
                if c3_src is None or c5_dst is None:
                    rows.append(
                        {
                            "crossover_id": xo.id,
                            "strand_id": strand.id,
                            "status": "missing_endpoint_geometry",
                        }
                    )
                    prev_domain = domain
                    continue

                explicit_extra_bases = len(xo.extra_bases or "")
                linker_segments = explicit_extra_bases + 1
                contour_nm = linker_segments * _PHOSPHODIESTER_LINKER_CONTOUR_NM
                span_nm = float(_np.linalg.norm(c5_dst - c3_src))
                stretch_ratio = span_nm / contour_nm if contour_nm > 0 else float("inf")
                rows.append(
                    {
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
                    }
                )
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

    def _rot(
        pivot: _np.ndarray, axis_vec: _np.ndarray, names: list[str], angle: float
    ) -> None:
        ax = axis_vec / _np.linalg.norm(axis_vec)
        c, s = _np.cos(angle), _np.sin(angle)
        for nm in names:
            v = pos[nm] - pivot
            pos[nm] = (
                pivot + v * c + _np.cross(ax, v) * s + ax * _np.dot(ax, v) * (1.0 - c)
            )

    if delta_rad:
        # Rotate C5′/O5′/P/OP1/OP2 around C3′→C4′ axis, pivot at C4′
        pivot = pos["C4'"].copy()
        axis = pos["C4'"] - pos["C3'"]
        _rot(pivot, axis, ["C5'", "O5'", "P", "OP1", "OP2"], delta_rad)

    if gamma_rad:
        # Rotate O5′/P/OP1/OP2 around C4′→C5′ axis, pivot at C5′ (post-δ position)
        pivot = pos["C5'"].copy()
        axis = pos["C5'"] - pos["C4'"]
        _rot(pivot, axis, ["O5'", "P", "OP1", "OP2"], gamma_rad)

    if beta_rad:
        # Rotate P/OP1/OP2 around C5′→O5′ axis, pivot at O5′ (post-γ position)
        pivot = pos["O5'"].copy()
        axis = pos["O5'"] - pos["C5'"]
        _rot(pivot, axis, ["P", "OP1", "OP2"], beta_rad)

    return tuple(
        (
            name,
            elem_map[name],
            float(pos[name][0]),
            float(pos[name][1]),
            float(pos[name][2]),
        )
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
    return (
        range(n_copies)
        if direction == Direction.FORWARD
        else range(n_copies - 1, -1, -1)
    )


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
                    key: tuple = (
                        (h_id, bp, dir_str)
                        if copy_k == 0
                        else (h_id, bp, dir_str, copy_k)
                    )
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

    p_atoms, p_bonds, _ = build_protein_attachment_atoms(
        design, serial_start=len(model.atoms)
    )
    if not p_atoms:
        return model
    model.atoms.extend(p_atoms)
    model.bonds.extend(p_bonds)
    return model


def build_atomistic_model(
    design: Design,
    exclude_helix_ids: set[str] | None = None,
    nuc_pos_override: "dict[tuple, _np.ndarray] | None" = None,
    nuc_frame_override: "dict[tuple[str, int, str], NucleotidePosition] | None" = None,
    include_proteins: bool = False,
    axis_override: "dict[tuple[str, int], tuple[_np.ndarray, _np.ndarray]] | None" = None,
    frame_override: "dict[tuple, tuple[_np.ndarray, _np.ndarray, _np.ndarray]] | None" = None,
    xb_pos_override: "dict[tuple[str, int], _np.ndarray] | None" = None,
    ext_pos_override: "dict[tuple[str, int], _np.ndarray] | None" = None,
    close_backbone: bool = False,
    relaxed_oxdna_phase: bool = False,
    apply_design_geometry: bool = True,
    frame_sink: "dict[tuple, tuple[_np.ndarray, _np.ndarray]] | None" = None,
    fast_bridges: bool = False,
    measured_positioning: bool = True,
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
    - Extra crossover bases: full ribose + base stamped AT the CG representation's
      own insert positions, with only the phosphodiester linker atoms minimised to
      close the O3′→P chain.  Nothing here decides where an extra base belongs —
      the CG view does, and this follows it.

    ``measured_positioning`` (DEFAULT, i.e. native) uses the MD-measured templates in
    ``measured_atomistic.py`` — see that module for what was measured and how.  This is
    what NADOC draws AND what it hands to every simulation and export; passing False
    reverts to the 1ZEW-derived templates, which is what the Help ▸ New Positioning
    toggle switches back to for comparison.

    Measured placement covers the duplex stamping path, the surface point cloud, the
    fast client-side stamp descriptor and the oxDNA rigid-frame calibration.

    Extra crossover bases and strand-extension tails deliberately KEEP the 1ZEW
    templates.  Their placers are calibrated against that template's local origin —
    insert atoms are required to sit on the CG chord (an extra base's position is a
    READ of the CG representation, never an independent placement), and the tail linker
    geometry is fitted the same way.  Swapping the template under them moved the insert
    origin 0.41 nm off the chord and stretched a tail backbone bond to 3.5 A against a
    3.2 A limit.  Making them native means re-deriving both placers, which is separable
    from the duplex and not done here.  Their POSITIONS still follow the CG layer, and
    the junction linkers are minimised afterwards, so they join measured duplex.
    """
    measured_tmpl = None
    if measured_positioning:
        from backend.core import measured_atomistic as _ma

        try:
            measured_tmpl = _ma.measured_templates()
        except _ma.MeasuredTemplateUnavailable:
            measured_tmpl = None  # fall back to legacy rather than fail the view

    # frame_sink requires the full per-nucleotide loop (the cached-reference fast
    # path never computes per-nucleotide frames), so requesting one forces it.
    #
    # The reference is honoured whatever the positioning mode: it holds coordinates
    # measured from an actual simulation of THIS design, which outranks any template.
    if frame_sink is None and nuc_pos_override is None and nuc_frame_override is None:
        ref_model = atomistic_model_from_reference(design, exclude_helix_ids)
        if ref_model is not None:
            return (
                _append_protein_atoms(ref_model, design)
                if include_proteins
                else ref_model
            )

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
            if (
                _prev_d is not None
                and _prev_d.helix_id != _d.helix_id
                and _prev_d.end_bp == _d.start_bp
                and (_prev_d.helix_id, _prev_d.end_bp) in _eb_junction_pos
            ):
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

    atoms: list[Atom] = []
    bonds: list[tuple[int, int]] = []
    serial = 0

    # Total rigid roll per nucleotide, including the DX-junction balance term.
    _phase_rad = atomistic_phase_offset_rad(design)

    # DISPLAY speed: the crossover/skip/insert phosphate bridges are placed by an
    # L-BFGS-B minimiser for MD-SEED-quality bond angles — that dominates the build on
    # a large crossover-dense structure (≈42 s of a 58 s VoltronCore build) and is
    # pointless for a viewer.  `fast_bridges` swaps it for the cheap linear
    # interpolation that is ALREADY the minimiser's initial guess: 6× faster, only the
    # ~1.5% phosphate-linker atoms move (≤2.4 Å at junctions).  Default False keeps the
    # exact geometry for MD seeds / PDB export / NAMD / periodic-cell.
    _bridge_fn = (
        _interpolate_backbone_bridge if fast_bridges else _minimize_backbone_bridge
    )

    for strand in design.strands:
        chain_id = strand_to_chain[strand.id]
        seq_num_in_chain = 0

        for domain in strand.domains:
            h_id = domain.helix_id
            dir_str = domain.direction.value
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
            _helix_hi = helix.bp_start + helix.length_bp  # exclusive upper bound
            if direction == Direction.FORWARD:
                _dom_lo, _dom_hi = domain.start_bp, domain.end_bp
            else:
                _dom_lo, _dom_hi = domain.end_bp, domain.start_bp

            if _dom_lo < _helix_lo:
                _ea = nucleotide_positions_arrays_extended(helix, _dom_lo)
                for _i in range(len(_ea["bp_indices"])):
                    _bp = int(_ea["bp_indices"][_i])
                    _d = (
                        Direction.FORWARD
                        if _ea["directions"][_i] == 0
                        else Direction.REVERSE
                    )
                    _k = (_bp, _d, 0)  # overhang extensions are always copy 0
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id=helix.id,
                            bp_index=_bp,
                            direction=_d,
                            position=_ea["positions"][_i].copy(),
                            base_position=_ea["base_positions"][_i].copy(),
                            base_normal=_ea["base_normals"][_i].copy(),
                            axis_tangent=_ea["axis_tangents"][_i].copy(),
                        )
            if _dom_hi >= _helix_hi:
                _ea = nucleotide_positions_arrays_extended_right(helix, _dom_hi)
                for _i in range(len(_ea["bp_indices"])):
                    _bp = int(_ea["bp_indices"][_i])
                    _d = (
                        Direction.FORWARD
                        if _ea["directions"][_i] == 0
                        else Direction.REVERSE
                    )
                    _k = (_bp, _d, 0)  # overhang extensions are always copy 0
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id=helix.id,
                            bp_index=_bp,
                            direction=_d,
                            position=_ea["positions"][_i].copy(),
                            base_position=_ea["base_positions"][_i].copy(),
                            base_normal=_ea["base_normals"][_i].copy(),
                            axis_tangent=_ea["axis_tangents"][_i].copy(),
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

                    # Apply a CG position override. Four-part keys address loop
                    # copies; the legacy three-part key addresses copy 0.
                    if nuc_pos_override is not None:
                        cg_pos = nuc_pos_override.get((h_id, bp, dir_str, copy_k))
                        if cg_pos is None and copy_k == 0:
                            cg_pos = nuc_pos_override.get((h_id, bp, dir_str))
                        if cg_pos is not None:
                            import dataclasses as _dc
                            nuc_pos = _phase_invalidated(
                                _dc.replace(nuc_pos, position=cg_pos))

                    seq_num_in_chain += 1
                    _seq_key: tuple = (
                        (h_id, bp, dir_str)
                        if copy_k == 0
                        else (h_id, bp, dir_str, copy_k)
                    )
                    base_char = seq_map.get(_seq_key, "N")
                    residue = _BASE_CHAR_TO_RESIDUE.get(base_char, "DT")

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
                    # Bound on EVERY path: the frame_override branch below never
                    # computes an axis point, and the measured-placement block after
                    # this if/else reads it to decide whether a base-pair frame exists.
                    axis_pt = None
                    _fo = None
                    if frame_override is not None:
                        _fo = frame_override.get((h_id, bp, dir_str, copy_k))
                        if _fo is None and copy_k == 0:
                            _fo = frame_override.get((h_id, bp, dir_str))
                    if _fo is not None:
                        if len(_fo) == 2:
                            # Direct (origin, R) frame prepared for flexible ssDNA
                            # from its simulated 5'->3' neighbours.
                            origin, R = _fo
                        else:
                            origin, R = _oxdna_rigid_frame(
                                _fo[0], _fo[1], _fo[2], direction, helix.direction
                            )
                    else:
                        _frame_key = (h_id, bp, dir_str)
                        _use_prepared_frame = False
                        if nuc_frame_override is not None and copy_k == 0:
                            _nfo = nuc_frame_override.get(_frame_key)
                            if _nfo is not None:
                                nuc_pos = _nfo
                                _use_prepared_frame = True

                        # Apply CG position override (including explicit loop copies).
                        if nuc_pos_override is not None:
                            cg_pos = nuc_pos_override.get((h_id, bp, dir_str, copy_k))
                            if cg_pos is None and copy_k == 0:
                                cg_pos = nuc_pos_override.get(_frame_key)
                            if cg_pos is not None:
                                import dataclasses as _dc
                                nuc_pos = _phase_invalidated(
                                    _dc.replace(nuc_pos, position=cg_pos))

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
                                # A bent axis: the lattice radial is no longer perpendicular
                                # to the local tangent, so it must be re-measured off the
                                # bead against THIS axis (the seed-clash bug above).
                                nuc_pos = _phase_invalidated(
                                    _dc.replace(nuc_pos, axis_tangent=_ov[1]))

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
                                                helix_direction=_hd,
                                                phase_rad=_phase_rad)

                    # Measured placement swaps the TEMPLATE only — the frame is
                    # whatever this nucleotide was going to get anyway.  The measured
                    # coordinates are supplied in the legacy frame's own convention
                    # (see _native_local_defs), so this reproduces the measured
                    # base-pair geometry exactly on the axis path, and stays correct on
                    # the paths that build their frame some other way: an oxDNA rigid
                    # frame, a prepared display frame, a deformed axis.  Those branches
                    # never compute an axis point, so a frame-based swap would have
                    # silently left them on 1ZEW geometry while everything else moved.
                    _sugar_defs, _base_defs = sugar_template, None
                    if measured_tmpl is not None:
                        _mt = _native_local_defs(residue, dir_str)
                        if _mt is not None:
                            _sugar_defs, _base_defs = (
                                _mt[: len(_SUGAR)],
                                _mt[len(_SUGAR) :],
                            )

                    # Record the per-nucleotide rigid frame (UNDEFORMED — the
                    # deformation/cluster post-pass below runs after this loop) so a
                    # fast display path can ship (origin, R) and expand the fixed
                    # template client-side instead of re-serialising every atom.  See
                    # atomistic_stamp_descriptor + oxdna_health.display_frames_payload.
                    if frame_sink is not None:
                        frame_sink[(h_id, bp, dir_str, copy_k)] = (origin, R)

                    # ── Sugar + phosphate atoms ───────────────────────────────
                    # NB: stamped per-atom (origin + R @ local), NOT batched. A
                    # batched (local_stack @ R.T) matmul differs at the last ULP,
                    # and the backbone-bridge L-BFGS-B minimiser downstream has
                    # near-degenerate minima that amplify that ULP into ~0.1–0.8 Å
                    # geometry swings on crossover/skip designs. Keep it per-atom
                    # so the display stays byte-identical (test_atomistic_batch_stamp).
                    sugar_name_to_serial: dict[str, int] = {}
                    for atom_name, element, n, y, z_local in _sugar_defs:
                        local = _np.array([n, y, z_local])
                        world = origin + R @ local
                        atoms.append(
                            Atom(
                                serial=serial,
                                name=atom_name,
                                element=element,
                                residue=residue,
                                chain_id=chain_id,
                                seq_num=seq_num_in_chain,
                                x=float(world[0]),
                                y=float(world[1]),
                                z=float(world[2]),
                                strand_id=strand.id,
                                helix_id=h_id,
                                bp_index=bp,
                                direction=dir_str,
                                copy_k=copy_k or None,  # 0 → None (plain 3-tuple key)
                            )
                        )
                        sugar_name_to_serial[atom_name] = serial
                        serial += 1

                    # ── Base atoms ────────────────────────────────────────────
                    tmpl_dict = (
                        BASE_TEMPLATES
                        if direction == Direction.FORWARD
                        else BASE_TEMPLATES_REV
                    )
                    base_atoms_def, base_bond_defs = tmpl_dict[residue]
                    if _base_defs is not None:
                        # Bond table is unchanged — the measured template carries the
                        # same atom names, which is why it drops straight in here.
                        base_atoms_def = _base_defs
                    base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
                    for atom_name, element, n, y, z_local in base_atoms_def:
                        local = _np.array([n, y, z_local])
                        world = origin + R @ local
                        atoms.append(
                            Atom(
                                serial=serial,
                                name=atom_name,
                                element=element,
                                residue=residue,
                                chain_id=chain_id,
                                seq_num=seq_num_in_chain,
                                x=float(world[0]),
                                y=float(world[1]),
                                z=float(world[2]),
                                strand_id=strand.id,
                                helix_id=h_id,
                                bp_index=bp,
                                direction=dir_str,
                                copy_k=copy_k or None,  # 0 → None (plain 3-tuple key)
                            )
                        )
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
                        bp_to_sugar_serials[(h_id, bp, dir_str)] = dict(
                            sugar_name_to_serial
                        )

    # ── Inter-residue backbone bonds (O3′ → P of next residue) ───────────────
    # Walk each strand's domains in 5′→3′ order; connect consecutive bp.
    # Crossovers that carry extra bases are skipped here — _build_extra_base_atoms
    # adds the correct O3′→P chain through the extra-base loop instead.
    for strand in design.strands:
        direction = None
        prev_o3_serial: Optional[int] = None
        prev_nuc_key: Optional[tuple[str, int, str]] = None
        for domain in strand.domains:
            h_id = domain.helix_id
            dir_str = domain.direction.value
            direction = domain.direction
            for bp in _atomistic_domain_bp_range(domain, strand):
                _n_copies = 0
                while (h_id, bp, dir_str, _n_copies) in bp_to_serials:
                    _n_copies += 1
                if _n_copies == 0:
                    prev_o3_serial = None
                    prev_nuc_key = None
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
                    prev_nuc_key = (h_id, bp, dir_str)

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
            if (
                prev_domain is not None
                and prev_domain.helix_id != domain.helix_id
                and prev_domain.end_bp == domain.start_bp
            ):
                src_key = (
                    prev_domain.helix_id,
                    prev_domain.end_bp,
                    prev_domain.direction.value,
                )
                if src_key in extra_base_xover_src:
                    prev_domain = domain
                    continue
                dst_key = (domain.helix_id, domain.start_bp, domain.direction.value)
                src_s = bp_to_sugar_serials.get(src_key)
                dst_s = bp_to_sugar_serials.get(dst_key)
                if src_s and dst_s:
                    _bridge_fn(atoms, src_s, dst_s)

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
            h_id = domain.helix_id
            dir_str = domain.direction.value
            helix = helix_map.get(h_id)
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
                            _bridge_fn(atoms, src_s, dst_s)

                prev_key_bb = cur_key_bb

            # Reset at domain boundary: next domain is either a different helix
            # (crossover, handled above) or a different position on the same helix.
            prev_key_bb = None

    # ── Extra crossover base atoms ────────────────────────────────────────────
    serial = _build_extra_base_atoms(
        design=design,
        atoms=atoms,
        bonds=bonds,
        serial=serial,
        strand_to_chain=strand_to_chain,
        nuc_pos_cache=nuc_pos_cache,
        helix_map=helix_map,
        bp_to_sugar_serials=bp_to_sugar_serials,
        exclude_helix_ids=exclude_helix_ids,
        xb_pos_override=xb_pos_override,
        bridge_fn=_bridge_fn,
        fast_bridges=fast_bridges,
    )

    # ── Strand-extension tail atoms (5′/3′ terminal tails) ────────────────────
    serial = _build_extension_atoms(
        design=design,
        atoms=atoms,
        bonds=bonds,
        serial=serial,
        strand_to_chain=strand_to_chain,
        nuc_pos_cache=nuc_pos_cache,
        bp_to_sugar_serials=bp_to_sugar_serials,
        ext_pos_override=ext_pos_override,
        bridge_fn=_bridge_fn,
    )

    # ── Thread inserts + tails into the per-chain residue numbering ───────────
    # Both builders append their residues at the END of each chain's seq_num range.
    # The psfgen topology writer bonds residues in seq_num order, so end-appended
    # inserts get threaded prev_real → eb → eb → next-crossover's eb (a 55 Å junk
    # bond) instead of prev_real → eb → eb → next_real at the actual junction, and an
    # end-appended 5′ tail would sit after the 3′ end of its own strand.  Renumber
    # every chain into true chain order (see _thread_inserts_inline) — which is also
    # what lands psfgen's 5TER/3TER/DEO5 patches on the tails.
    _thread_inserts_inline(atoms, design)

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
    #
    # SKIPPED for an oxDNA/mrDNA SEED (apply_design_geometry=False): a CG-relaxed
    # override already supplies each nucleotide's FINAL world position (the deformed +
    # cluster-transformed, then simulated geometry).  Re-applying the design's
    # deformations/cluster transforms on top would double them — the source of the
    # ~N× "explosion" when seeding a design built from copy-pasted, rotated clusters.
    # The seed is purely a function of the oxDNA positions; pre-oxDNA transforms have
    # no place here.
    if apply_design_geometry:
        from backend.core.deformation import apply_deformations_to_atoms

        apply_deformations_to_atoms(atoms, design)

    model = AtomisticModel(atoms=atoms, bonds=bonds)
    if include_proteins:
        model = _append_protein_atoms(model, design)
    return model


# ── Fast CG→atomistic display: stamp descriptor ──────────────────────────────
# The relaxed-display all-atom set is, per nucleotide, a fixed local template
# rigidly stamped by that nucleotide's frame (world = origin + R @ local), EXCEPT
# a small "non-rigid" minority that later passes move off the stamp: sequential
# phosphate linkers (_close_sequential_backbone), crossover/skip bridges
# (_minimize_backbone_bridge), extra-base inserts, extension tails, proteins.
# The descriptor captures the FIXED (design-determined) part — which serial is
# rigid, its template-local coord, and which nucleotide it belongs to — so a fast
# path can ship only per-nucleotide frames (origin, R) + the non-rigid positions
# and let the client expand the rest. See oxdna_health.display_frames_payload.


@dataclass(slots=True)
class StampDescriptor:
    nuc_keys: list  # [(helix_id, bp_index, dir_str, copy_k)] in emission order
    atom_nuc: list  # per serial: index into nuc_keys, or -1 (non-rigid)
    atom_local: list  # per serial: (n, y, z) template-local; (0,0,0) if non-rigid
    nonrigid_serials: list  # sorted serials where atom_nuc == -1
    topology_hash: str


from collections import OrderedDict as _OrderedDict

_STAMP_DESC_CACHE: "_OrderedDict[str, StampDescriptor]" = _OrderedDict()
_STAMP_DESC_CACHE_MAX = 8


def _template_local_map(residue: str, dir_str: str) -> dict:
    """{atom_name: (n, y, z)} template-local coords for one (residue, direction) —
    the sugar/phosphate (direction-independent) merged with the direction-specific
    base template.  Mirrors the calibration's _local helper (one source of truth for
    what 'the fixed template' is)."""
    defs = _native_local_defs(residue, dir_str)
    if defs is not None:
        return {name: (n, y, z) for name, _e, n, y, z in defs}
    d = {name: (n, y, z) for name, _e, n, y, z in _SUGAR}
    base = BASE_TEMPLATES if dir_str == "FORWARD" else BASE_TEMPLATES_REV
    for name, _e, n, y, z in base[residue][0]:
        d[name] = (n, y, z)
    return d


@_functools.lru_cache(maxsize=8)
def _surface_stamp_templates() -> dict:
    """Per-(residue, direction) local template atoms for the surface point cloud:
    ``{(residue, dir_str): (local (K,3) float64, radii (K,) float64)}`` — sugar + base
    atoms with their VdW radii (element → VDW_RADIUS).  The cloud stamps ``world =
    origin + R @ local`` per group, so the base-identity split just picks which fixed
    template."""
    out: dict = {}
    for residue in BASE_TEMPLATES:
        for dir_str, base_tmpl in (
            ("FORWARD", BASE_TEMPLATES),
            ("REVERSE", BASE_TEMPLATES_REV),
        ):
            defs = _native_local_defs(residue, dir_str)
            if defs is None:
                defs = list(_SUGAR) + list(base_tmpl[residue][0])
            local = _np.array([[n, y, z] for _name, _e, n, y, z in defs], dtype=float)
            radii = _np.array(
                [VDW_RADIUS.get(e, VDW_RADIUS["C"]) for _name, e, *_ in defs],
                dtype=float,
            )
            out[(residue, dir_str)] = (local, radii)
    return out


def surface_atom_cloud(
    design: Design,
) -> tuple[_np.ndarray, _np.ndarray, list[str], list[str]]:
    """FAST vectorised all-atom point cloud for the DESIGN molecular surface — positions +
    per-atom VdW radius + per-atom strand id + per-atom nucleotide key
    (``helix:bp:direction``), WITHOUT the ~300k ``Atom`` dataclass objects
    or the per-nucleotide ``numpy.cross`` overhead that dominate ``build_atomistic_model``.

    Reproduces the design-surface build (``build_atomistic_model(design, fast_bridges=True)``
    with ``close_backbone=False``): the SAME per-nucleotide rigid frame (via the byte-identical
    ``_atom_frames_batch``) stamping the SAME fixed sugar+base templates, then the SAME
    deformation / cluster fold (``apply_deformations_to_atoms``, folded through 4 markers per
    nucleotide instead of per atom).  It SKIPS the crossover/skip phosphate bridges, the
    extra-base and extension tail atoms, and all bonds — none of which change the VdW envelope
    at the display grid (validated ≤~1 Å p99 vs the full fine surface by
    ``tests/test_surface_visual_regression.py``).

    Returns ``(positions (N,3) float32, radii (N,) float32, strand_ids list[str])``.
    Honeycomb/square, routed/unrouted, deformed/clustered.  Not for MD seeds / PDB export
    (those need the exact bridge geometry + every atom) — display surface only."""
    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.geometry import nucleotide_positions

    helix_map = {h.id: effective_helix_for_geometry(h, design) for h in design.helices}
    seq_map = _build_sequence_map(design)
    templates = _surface_stamp_templates()

    # Per-helix nucleotide dict + axis geometry — mirrors build_atomistic_model's caches so
    # the frame inputs are identical (nucleotide_positions is the same geometry source).
    nuc_pos_cache: dict[str, dict[tuple, "NucleotidePosition"]] = {}
    axis_cache: dict[str, tuple[_np.ndarray, _np.ndarray, int]] = {}
    for h in helix_map.values():
        s = _np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        e = _np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z])
        ax = e - s
        ln = _np.linalg.norm(ax)
        axis_cache[h.id] = (s, ax / ln if ln > 1e-9 else ax, h.bp_start)

    def _nuc_dict(h_id):
        npc = nuc_pos_cache.get(h_id)
        if npc is None:
            npc = {}
            copy_cnt: dict[tuple, int] = {}
            for nuc in nucleotide_positions(helix_map[h_id]):
                base = (nuc.bp_index, nuc.direction)
                k = copy_cnt.get(base, 0)
                npc[(nuc.bp_index, nuc.direction, k)] = nuc
                copy_cnt[base] = k + 1
            nuc_pos_cache[h_id] = npc
        return npc

    # ── Gather ordered per-nucleotide frame inputs (strand → domain → bp → copy) ──
    positions: list = []; tangents: list = []; normals: list = []; axis_pts: list = []
    radials: list = []          # the carried helical phase (see NucleotidePosition)
    dir_fwd: list = []; helix_fwd: list = []
    residues: list = []; strand_ids: list = []
    keys_hbd: list = []                                  # (helix, bp, dir_str) for deform fold

    for strand in design.strands:
        for domain in strand.domains:
            h_id = domain.helix_id
            helix = helix_map.get(h_id)
            if helix is None:
                continue
            direction = domain.direction
            dir_str = direction.value
            nuc_positions = _nuc_dict(h_id)

            # Overhang crossover extensions reach beyond the helix bp range — extend the
            # cache exactly as build_atomistic_model does so those nucleotides aren't dropped.
            if direction == Direction.FORWARD:
                _dom_lo, _dom_hi = domain.start_bp, domain.end_bp
            else:
                _dom_lo, _dom_hi = domain.end_bp, domain.start_bp
            if _dom_lo < helix.bp_start:
                _ea = nucleotide_positions_arrays_extended(helix, _dom_lo)
                for _i in range(len(_ea["bp_indices"])):
                    _bp = int(_ea["bp_indices"][_i])
                    _d = (
                        Direction.FORWARD
                        if _ea["directions"][_i] == 0
                        else Direction.REVERSE
                    )
                    _k = (_bp, _d, 0)
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id=helix.id,
                            bp_index=_bp,
                            direction=_d,
                            position=_ea["positions"][_i].copy(),
                            base_position=_ea["base_positions"][_i].copy(),
                            base_normal=_ea["base_normals"][_i].copy(),
                            axis_tangent=_ea["axis_tangents"][_i].copy(),
                        )
            if _dom_hi >= helix.bp_start + helix.length_bp:
                _ea = nucleotide_positions_arrays_extended_right(helix, _dom_hi)
                for _i in range(len(_ea["bp_indices"])):
                    _bp = int(_ea["bp_indices"][_i])
                    _d = (
                        Direction.FORWARD
                        if _ea["directions"][_i] == 0
                        else Direction.REVERSE
                    )
                    _k = (_bp, _d, 0)
                    if _k not in nuc_positions:
                        nuc_positions[_k] = NucleotidePosition(
                            helix_id=helix.id,
                            bp_index=_bp,
                            direction=_d,
                            position=_ea["positions"][_i].copy(),
                            base_position=_ea["base_positions"][_i].copy(),
                            base_normal=_ea["base_normals"][_i].copy(),
                            axis_tangent=_ea["axis_tangents"][_i].copy(),
                        )

            ax_start, ax_hat, bp_start0 = axis_cache[h_id]
            for bp in _atomistic_domain_bp_range(domain, strand):
                _n_copies = 0
                while (bp, direction, _n_copies) in nuc_positions:
                    _n_copies += 1
                for copy_k in _loop_copy_order(direction, _n_copies):
                    nuc_pos = nuc_positions.get((bp, direction, copy_k))
                    if nuc_pos is None:
                        continue
                    _seq_key = (
                        (h_id, bp, dir_str)
                        if copy_k == 0
                        else (h_id, bp, dir_str, copy_k)
                    )
                    residue = _BASE_CHAR_TO_RESIDUE.get(
                        seq_map.get(_seq_key, "N"), "DT"
                    )
                    positions.append(nuc_pos.position)
                    radials.append(nuc_pos.radial_hat if nuc_pos.radial_hat is not None
                                   else _np.full(3, _np.nan))
                    tangents.append(nuc_pos.axis_tangent)
                    normals.append(nuc_pos.base_normal)
                    axis_pts.append(
                        ax_start + (bp - bp_start0) * BDNA_RISE_PER_BP * ax_hat
                    )
                    dir_fwd.append(direction == Direction.FORWARD)
                    helix_fwd.append(helix.direction == Direction.FORWARD)
                    residues.append(residue)
                    strand_ids.append(strand.id or "")
                    keys_hbd.append((h_id, bp, dir_str))

    n = len(positions)
    if n == 0:
        return (_np.empty((0, 3), _np.float32), _np.empty(0, _np.float32), [], [])

    pos = _np.asarray(positions, float); axt = _np.asarray(tangents, float)
    bn = _np.asarray(normals, float); axp = _np.asarray(axis_pts, float)
    dfwd = _np.asarray(dir_fwd, bool); hfwd = _np.asarray(helix_fwd, bool)
    rad = _np.asarray(radials, float)      # NaN rows = no analytic phase, bead fallback

    origins, R = _atom_frames_batch(pos, axt, bn, axp, dfwd, hfwd,
                                    phase_rad=atomistic_phase_offset_rad(design),
                                    radial_hat=rad)

    # Fold design geometry (deformations + cluster transforms) into the frames via 4 markers
    # per nucleotide — one rigid transform per (helix, bp, dir), the SAME apply_deformations_
    # to_atoms math the full build runs per atom, but on 4·N markers not ~14·N atoms.
    origins, R = _fold_design_geometry_into_frames(design, origins, R, keys_hbd)

    # ── Per-nucleotide atom counts + global row offsets (nucleotide atoms stay contiguous,
    # sugar first, so the crossover/skip bridge can address O3'/P/… by a fixed local index) ──
    residues_arr = _np.asarray(residues)
    dfwd_str = _np.where(dfwd, "FORWARD", "REVERSE")
    k_per = _np.array([len(templates[(residues[i], dfwd_str[i])][0]) for i in range(n)])
    offsets = _np.zeros(n, dtype=_np.int64)
    offsets[1:] = _np.cumsum(k_per)[:-1]
    total = int(k_per.sum())

    positions_out = _np.empty((total, 3), dtype=_np.float64)
    radii_out = _np.empty(total, dtype=_np.float64)
    strand_ids_arr = _np.asarray(strand_ids, dtype=object)
    sids_out = _np.empty(total, dtype=object)
    # Per-point nucleotide key, expanded exactly like the strand id below. The surface
    # needs it so per-cluster colour can resolve per nucleotide rather than per strand
    # (a strand — the scaffold above all — can span several clusters; LESSONS D15).
    nkeys_arr = _np.asarray([f"{h}:{b}:{d}" for (h, b, d) in keys_hbd], dtype=object)
    nkeys_out = _np.empty(total, dtype=object)

    # ── Batch-stamp per (residue, direction) group, scattered to each nucleotide's rows ──
    for (residue, dstr), (local, radii) in templates.items():
        sel = _np.nonzero((residues_arr == residue) & (dfwd_str == dstr))[0]
        if sel.size == 0:
            continue
        K = len(local)
        world = origins[sel][:, None, :] + _np.einsum(
            "aij,kj->aki", R[sel], local
        )  # (m,K,3)
        rows = (offsets[sel][:, None] + _np.arange(K)[None, :]).ravel()  # (m*K,)
        positions_out[rows] = world.reshape(-1, 3)
        radii_out[rows] = _np.tile(radii, sel.size)
        sids_out[rows] = _np.repeat(strand_ids_arr[sel], K)
        nkeys_out[rows] = _np.repeat(nkeys_arr[sel], K)

    # ── Crossover + skip-site phosphate-bridge interpolation (fast_bridges) ──
    # Reproduces build_atomistic_model's _interpolate_backbone_bridge at each junction so the
    # phosphate linkers land where the full build puts them (else ~2.4 Å off at ~1% of atoms,
    # concentrated on the envelope near crossovers).  All bridge atoms live in the fixed sugar
    # template at constant local indices, so we address them by (offset + index).
    key3_to_off: dict[tuple, int] = {keys_hbd[i]: int(offsets[i]) for i in range(n)}
    _apply_cloud_bridges(design, helix_map, positions_out, key3_to_off)

    return (
        positions_out.astype(_np.float32),
        radii_out.astype(_np.float32),
        list(sids_out),
        list(nkeys_out),
    )


# Sugar-template local atom indices (order fixed by _SUGAR) — the bridge atoms.
_SUGAR_IDX = {name: i for i, (name, *_rest) in enumerate(_SUGAR)}


def _apply_cloud_bridges(design, helix_map, P, key3_to_off) -> None:
    """Apply the fast_bridges (linear) phosphodiester-linker interpolation at every crossover
    and skip gap to the surface point cloud ``P`` — the array analogue of
    ``_interpolate_backbone_bridge`` + the crossover/skip passes in ``build_atomistic_model``.
    O3'(src)→¼, P(dst)→½, O5'(dst)→¾ along C3'(src)→C5'(dst); OP1/OP2(dst) ride P's delta."""
    iC3, iO3, iC5, iP, iO5, iOP1, iOP2 = (
        _SUGAR_IDX["C3'"],
        _SUGAR_IDX["O3'"],
        _SUGAR_IDX["C5'"],
        _SUGAR_IDX["P"],
        _SUGAR_IDX["O5'"],
        _SUGAR_IDX["OP1"],
        _SUGAR_IDX["OP2"],
    )

    def _bridge(src_off, dst_off):
        c3 = P[src_off + iC3]
        c5 = P[dst_off + iC5]
        new_p = c3 + (c5 - c3) * 0.5
        delta = new_p - P[dst_off + iP]
        P[src_off + iO3] = c3 + (c5 - c3) * 0.25
        P[dst_off + iP] = new_p
        P[dst_off + iO5] = c3 + (c5 - c3) * 0.75
        P[dst_off + iOP1] += delta
        P[dst_off + iOP2] += delta

    # Crossovers: consecutive domains on different helices sharing a bp position.  (Extra-base
    # crossovers are handled by a separate atom builder in the full model; the cloud omits
    # those added atoms — no panel design has them.)
    eb_src = set()
    for _s in design.strands:
        prev = None
        for dom in _s.domains:
            if (
                prev is not None
                and prev.helix_id != dom.helix_id
                and prev.end_bp == dom.start_bp
            ):
                sk = (prev.helix_id, prev.end_bp, prev.direction.value)
                dk = (dom.helix_id, dom.start_bp, dom.direction.value)
                is_eb = any(
                    xo.extra_bases
                    and (
                        (xo.half_a.helix_id, xo.half_a.index)
                        == (prev.helix_id, prev.end_bp)
                        or (xo.half_b.helix_id, xo.half_b.index)
                        == (prev.helix_id, prev.end_bp)
                    )
                    for xo in design.crossovers
                )
                if is_eb:
                    eb_src.add(sk)
                elif sk in key3_to_off and dk in key3_to_off:
                    _bridge(key3_to_off[sk], key3_to_off[dk])
            prev = dom

    # Skip sites: a gap of >1 bp on the same helix/direction (deleted positions).
    for _s in design.strands:
        skip_cache: dict[str, set] = {}
        prev_key = None
        for dom in _s.domains:
            h_id = dom.helix_id
            dir_str = dom.direction.value
            helix = helix_map.get(h_id)
            if helix is None:
                prev_key = None
                continue
            if h_id not in skip_cache:
                acc: dict[int, int] = {}
                for ls in helix.loop_skips:
                    acc[ls.bp_index] = acc.get(ls.bp_index, 0) + ls.delta
                skip_cache[h_id] = {bp for bp, dd in acc.items() if dd <= -1}
            skips = skip_cache[h_id]
            if not skips:
                prev_key = None
                continue
            for bp in _atomistic_domain_bp_range(dom, _s):
                if bp in skips:
                    continue
                cur_key = (h_id, bp, dir_str)
                if cur_key not in key3_to_off:
                    prev_key = None
                    continue
                if prev_key is not None:
                    pv_h, pv_bp, pv_dir = prev_key
                    if pv_h == h_id and pv_dir == dir_str and abs(bp - pv_bp) > 1:
                        _bridge(key3_to_off[prev_key], key3_to_off[cur_key])
                prev_key = cur_key
            prev_key = None


def _fold_design_geometry_into_frames(design, origins, R, keys_hbd):
    """Apply the design's deformation + cluster rigid transforms to per-nucleotide frames.

    ``apply_deformations_to_atoms`` transforms atom POSITIONS by a per-(helix, bp) rigid
    transform; every atom of a nucleotide shares it, so we recover that transform once per
    nucleotide from 4 markers (origin + the three frame-axis tips), then fold it into
    ``(origin, R)`` — exact for a rigid transform (T(o+R·l) = T(o) + (rot·R)·l).  No-op when
    the design has no deformations/cluster transforms."""
    if not design.deformations and not design.cluster_transforms:
        return origins, R
    from backend.core.deformation import apply_deformations_to_atoms

    n = len(origins)

    class _M:
        __slots__ = ("x", "y", "z", "helix_id", "bp_index", "direction")

        def __init__(self, p, h, bp, d):
            self.x, self.y, self.z = float(p[0]), float(p[1]), float(p[2])
            self.helix_id = h
            self.bp_index = bp
            self.direction = d

    markers = []
    for i in range(n):
        h, bp, dstr = keys_hbd[i]
        o = origins[i]
        markers.append(_M(o, h, bp, dstr))
        markers.append(_M(o + R[i, :, 0], h, bp, dstr))
        markers.append(_M(o + R[i, :, 1], h, bp, dstr))
        markers.append(_M(o + R[i, :, 2], h, bp, dstr))
    apply_deformations_to_atoms(markers, design)

    new_o = _np.empty((n, 3))
    new_R = _np.empty((n, 3, 3))
    for i in range(n):
        m0 = markers[4 * i]
        o = _np.array([m0.x, m0.y, m0.z])
        new_o[i] = o
        for c in range(3):
            mc = markers[4 * i + 1 + c]
            new_R[i, :, c] = _np.array([mc.x, mc.y, mc.z]) - o
    return new_o, new_R


def atomistic_stamp_descriptor(design: Design) -> StampDescriptor:
    """Design-fixed descriptor for the fast CG→atomistic display path (cached by
    topology hash).  Classifies each atom RIGID (a pure origin+R@local stamp) vs
    NON-RIGID (moved by closure / bridge / insert / extension) EMPIRICALLY, from ONE
    display build (backbone closure ON, ideal geometry): an atom is non-rigid iff its
    built position deviates from its own template stamp.  Robust — closure moves the 5
    phosphate-linker atoms by ~1 Å per sequential pair and the bridge minimisers move
    their linkers too, both far above the 1e-6 nm threshold, while the ring/base atoms
    sit exactly on the stamp."""
    thash = atomistic_reference_topology_hash(design)
    cached = _STAMP_DESC_CACHE.get(thash)
    if cached is not None:
        _STAMP_DESC_CACHE.move_to_end(thash)
        return cached

    sink: dict = {}
    m = build_atomistic_model(
        design,
        close_backbone=True,
        relaxed_oxdna_phase=True,
        apply_design_geometry=False,
        frame_sink=sink,
        fast_bridges=True,
    )
    desc = _classify_stamp(m, sink, thash)
    _STAMP_DESC_CACHE[thash] = desc
    while len(_STAMP_DESC_CACHE) > _STAMP_DESC_CACHE_MAX:
        _STAMP_DESC_CACHE.popitem(last=False)
    return desc


def _classify_stamp(model, sink: dict, thash: str) -> StampDescriptor:
    """Classify each atom of a display build (close_backbone=True, ideal geometry, its
    `frame_sink`) rigid vs non-rigid — shared by `atomistic_stamp_descriptor` and the
    combined `atomistic_display_bundle` so one build serves both."""
    atoms = model.atoms
    TOL = 1e-6
    n = len(atoms)
    nuc_keys: list = []
    key_to_idx: dict = {}
    atom_nuc = [-1] * n
    atom_local: list = [(0.0, 0.0, 0.0)] * n
    nonrigid: list = []
    _tl_cache: dict = {}

    for s in range(n):
        a = atoms[s]
        # Inserts / tails / proteins: never a plain nucleotide stamp.
        if a.extra_base_k is not None or a.extension_id is not None or not a.helix_id:
            nonrigid.append(s)
            continue
        key = (a.helix_id, a.bp_index, a.direction, a.copy_k or 0)
        fr = sink.get(key)
        tk = (a.residue, a.direction)
        tl = _tl_cache.get(tk)
        if tl is None:
            tl = _template_local_map(a.residue, a.direction)
            _tl_cache[tk] = tl
        local = tl.get(a.name)
        if fr is None or local is None:
            nonrigid.append(s)
            continue
        origin, R = fr
        exp = origin + R @ _np.asarray(local, dtype=float)
        d_stamp = (
            (a.x - exp[0]) ** 2 + (a.y - exp[1]) ** 2 + (a.z - exp[2]) ** 2
        ) ** 0.5
        if d_stamp > TOL:
            nonrigid.append(s)  # moved by a bridge minimiser or by sequential closure
            continue
        idx = key_to_idx.get(key)
        if idx is None:
            idx = len(nuc_keys)
            key_to_idx[key] = idx
            nuc_keys.append(key)
        atom_nuc[s] = idx
        atom_local[s] = (float(local[0]), float(local[1]), float(local[2]))

    return StampDescriptor(
        nuc_keys=nuc_keys,
        atom_nuc=atom_nuc,
        atom_local=atom_local,
        nonrigid_serials=nonrigid,
        topology_hash=thash,
    )


def atomistic_display_bundle(design: Design) -> dict:
    """ONE build serving BOTH the renderer topology AND the stamp descriptor (fast
    bridges), so the display path pays a single build instead of two.  Returns the wire
    dict: atoms + bonds (atomistic_to_json) merged with the descriptor arrays + hashes.
    Route-level disk caching makes it a one-time-per-job cost."""
    thash = atomistic_reference_topology_hash(design)
    sink: dict = {}
    m = build_atomistic_model(
        design,
        close_backbone=True,
        relaxed_oxdna_phase=True,
        apply_design_geometry=False,
        frame_sink=sink,
        fast_bridges=True,
    )
    desc = _classify_stamp(m, sink, thash)
    _STAMP_DESC_CACHE[thash] = desc  # warm the in-proc descriptor cache too
    while len(_STAMP_DESC_CACHE) > _STAMP_DESC_CACHE_MAX:
        _STAMP_DESC_CACHE.popitem(last=False)
    out = atomistic_to_json(m)
    atom_local_flat: list = []
    for nx, ny, nz in desc.atom_local:
        atom_local_flat.extend((nx, ny, nz))
    out.update(
        {
            "topology_hash": thash,
            "n_nuc": len(desc.nuc_keys),
            "n_atoms": len(desc.atom_nuc),
            "nuc_keys": [list(k) for k in desc.nuc_keys],
            "atom_nuc": desc.atom_nuc,
            "atom_local": atom_local_flat,
            "nonrigid_serials": desc.nonrigid_serials,
        }
    )
    return out


_BUNDLE_BIN_MAGIC = 0x4E414231  # "NAB1"
_BUNDLE_BIN_VERSION = 1

# Fields the FRONTEND actually reads off an atom.  The other seven the JSON bundle
# carries (name, residue, chain_id, seq_num, is_modified, crossover_id, extra_base_k)
# are not read anywhere in frontend/src — they were ~40% of the atom payload.
# Keep in sync with ATOM_FIELDS in frontend/src/scene/atom_table.js.


class BundleNotPackable(ValueError):
    """The bundle violates an invariant the columnar format depends on, so the caller
    must fall back to the JSON route rather than ship a subtly-wrong payload."""


def pack_bundle_bin(bundle: dict) -> bytes:
    """Pack a JSON display bundle into the compact columnar/binary wire format.

    Pure function over the dict `atomistic_display_bundle` already produces (and that the
    per-job disk cache already holds), so the cache stays the single source of truth and
    this stays trivially testable.

    Why: 330k atoms as JSON dicts is ~112 MB and `JSON.parse` builds 330k objects before
    anything renders.  Here every atom column is a typed array and the five string fields
    become an index + a small interned table (a whole origami has ~200 strands, ~60
    helices, 2 directions, 4 elements), so the same information is ~7× smaller AND costs
    no per-atom allocation on the client.  See frontend/src/scene/atomistic_bundle_bin.js
    for the layout, which this function is the only producer of.

    Raises BundleNotPackable when an invariant the format relies on does not hold.
    """
    import json
    import struct

    import numpy as np

    atoms = bundle.get("atoms") or []
    n = len(atoms)
    if n == 0:
        raise BundleNotPackable("empty bundle")
    # A bundle missing any column the format carries is a fallback case, not a crash:
    # the route turns BundleNotPackable into a 409 and the client re-fetches the JSON.
    required = (
        "serial",
        "element",
        "x",
        "y",
        "z",
        "strand_id",
        "helix_id",
        "bp_index",
        "direction",
    )
    missing = [k for k in required if k not in atoms[0]]
    if missing:
        raise BundleNotPackable(
            f"atoms are missing required field(s): {', '.join(missing)}"
        )
    # serial IS the row index in this format (that is what lets us drop the column
    # entirely AND index the serial-keyed relaxed-frame arrays directly).
    for i, a in enumerate(atoms):
        if a["serial"] != i:
            raise BundleNotPackable(
                f"atom serials are not dense 0..n-1 (row {i} has serial {a['serial']})"
            )

    def _intern(field: str, width: int) -> tuple[list[str], np.ndarray]:
        table: list[str] = []
        index: dict[str, int] = {}
        out = np.empty(n, dtype=np.uint16 if width == 16 else np.uint8)
        for i, a in enumerate(atoms):
            v = a.get(field)
            v = "" if v is None else str(v)
            k = index.get(v)
            if k is None:
                k = index[v] = len(table)
                table.append(v)
            out[i] = k
        limit = 65536 if width == 16 else 256
        if len(table) > limit:
            raise BundleNotPackable(
                f"{field} has {len(table)} distinct values, exceeds u{width}"
            )
        return table, out

    strand_table, strand_idx = _intern("strand_id", 16)
    helix_table, helix_idx = _intern("helix_id", 16)
    aux_table, aux_idx = _intern("aux_helix_id", 16)
    element_table, element_idx = _intern("element", 8)
    dir_table, dir_idx = _intern("direction", 8)

    x = np.fromiter((a["x"] for a in atoms), dtype=np.float32, count=n)
    y = np.fromiter((a["y"] for a in atoms), dtype=np.float32, count=n)
    z = np.fromiter((a["z"] for a in atoms), dtype=np.float32, count=n)
    bp = np.fromiter((a["bp_index"] for a in atoms), dtype=np.int32, count=n)
    aux_t = np.fromiter(
        (a.get("aux_t") or 0.0 for a in atoms), dtype=np.float32, count=n
    )

    bonds = bundle.get("bonds") or []
    bonds_arr = (
        np.asarray(bonds, dtype=np.uint32).reshape(-1)
        if bonds
        else np.empty(0, np.uint32)
    )

    atom_nuc = np.asarray(
        bundle.get("atom_nuc") or [], dtype=np.int32
    )  # -1 = non-rigid
    atom_local = np.asarray(bundle.get("atom_local") or [], dtype=np.float32)
    nonrigid = np.asarray(bundle.get("nonrigid_serials") or [], dtype=np.uint32)
    if atom_nuc.size != n or atom_local.size != n * 3:
        raise BundleNotPackable("stamp descriptor length does not match the atom count")

    header = json.dumps(
        {
            "strand_table": strand_table,
            "helix_table": helix_table,
            "aux_helix_table": aux_table,
            "element_table": element_table,
            "dir_table": dir_table,
            "element_meta": bundle.get("element_meta") or {},
            "topology_hash": bundle.get("topology_hash"),
        }
    ).encode()

    parts: list[bytes] = [
        struct.pack(
            "<IIIII", _BUNDLE_BIN_MAGIC, _BUNDLE_BIN_VERSION, n, len(bonds), len(header)
        ),
        header,
    ]
    written = 20 + len(header)

    def _pad(to: int = 4) -> None:
        nonlocal written
        gap = (-written) % to
        if gap:
            parts.append(b"\x00" * gap)
            written += gap

    def _put(arr: np.ndarray) -> None:
        nonlocal written
        b = arr.tobytes()
        parts.append(b)
        written += len(b)

    # Widest-first so every typed-array view on the client lands naturally aligned.
    _pad()
    for col in (x, y, z, bp, aux_t):
        _put(col)
    for col in (strand_idx, helix_idx, aux_idx):
        _put(col)
    for col in (element_idx, dir_idx):
        _put(col)
    _pad()  # the two u8 columns can leave an odd offset
    _put(bonds_arr)
    parts.append(struct.pack("<II", int(bundle.get("n_nuc") or 0), nonrigid.size))
    written += 8
    _put(atom_nuc)
    _put(atom_local)
    _put(nonrigid)
    return b"".join(parts)


def _thread_inserts_inline(atoms: list[Atom], design: "Design") -> None:
    """Re-number per-chain ``seq_num`` so crossover extra-base inserts AND
    strand-extension tail bases sit at their true chain positions, in place.

    Both builders append their residues to the END of the chain's ``seq_num`` range.
    Consumers that rely on ``seq_num`` order to define backbone connectivity — the
    CHARMM psfgen topology builder above all — then bond them as one contiguous run at
    the chain tail (``prev_real → eb → eb → the next crossover's eb``), producing
    wildly stretched O3′→P bonds between inserts that belong to different junctions.
    Threading them restores ``prev_real → eb… → next_real`` at each real junction.

    Order per chain (a chain IS a strand — ``strand_to_chain`` gives each strand a
    unique letter, going two-letter past Z, so there is no wrap collision)::

        [5′ tail, OUTERMOST first] + [real residue, each trailed by its inserts] + [3′ tail]

    The 5′ tail comes first and its outermost base is emitted first because that base
    IS the strand's 5′ terminus.  This is also what makes the CHARMM terminal patches
    correct for free: ``namd_topology`` derives them purely from residue ORDER
    (``first 5TER`` / ``last 3TER`` / ``patch DEO5 {first_resid}``), so after the
    contiguous 1-based renumber below the outermost 5′ tail base becomes ``resid 1``
    and the 3′ tail tip becomes ``resid N``.  The anchor correctly stops being a
    terminus and becomes an internal ``DEOX`` residue.  No negative seq_num, no
    patch-list change.

    Each extra-base insert carries its source (owning, 3′) flank nucleotide's
    ``(helix_id, bp_index, direction)``; the insert is placed right after the real
    residue with that key, ordered by ``extra_base_k``.  An insert whose flank can't be
    resolved uniquely (e.g. a looped helix where ``(helix, bp, dir)`` is not unique) is
    left at the chain tail — the same position as before, so no regression for that
    case.  Extension residues are excluded from that flank lookup: they carry their
    ANCHOR's key, so they would otherwise masquerade as the anchor residue.

    Physical-layer only: touches ``seq_num`` (a residue counter), never topology.
    """
    from collections import defaultdict

    # residue key:  real   → ("r",  seq_num)
    #               insert → ("x",  crossover_id, extra_base_k)
    #               5′ tail→ ("e5", extension_id, ext_k)
    #               3′ tail→ ("e3", extension_id, ext_k)
    ext_end_by_id: dict[str, str] = {e.id: e.end for e in design.extensions}

    def _rkey(a: Atom):
        if getattr(a, "crossover_id", None) is not None:
            return ("x", a.crossover_id, a.extra_base_k)
        eid = getattr(a, "extension_id", None)
        if eid is not None:
            return (
                "e5" if ext_end_by_id.get(eid) == "five_prime" else "e3",
                eid,
                a.ext_k,
            )
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
        e5_rkeys = [k for k in residues if k[0] == "e5"]
        e3_rkeys = [k for k in residues if k[0] == "e3"]
        if not insert_rkeys and not e5_rkeys and not e3_rkeys:
            continue  # nothing to thread on this chain

        real_rkeys.sort(key=lambda k: k[1])  # by existing seq_num

        # (helix, bp, dir) → real residue key, dropping non-unique keys (loops).
        # Extension residues never enter here: they carry their ANCHOR's key.
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

        # 5′ tail: OUTERMOST base first (highest ext_k) — it is the 5′ terminus.
        # 3′ tail: innermost base first (lowest ext_k) — it adjoins the anchor.
        e5_rkeys.sort(key=lambda k: -k[2])
        e3_rkeys.sort(key=lambda k: k[2])

        ordered: list[tuple] = list(e5_rkeys)
        for k in real_rkeys:
            ordered.append(k)
            ordered.extend(inserts_after.get(k, ()))
        ordered.extend(e3_rkeys)
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
        regular_run = (
            src.helix_id == dst.helix_id
            and src.direction == dst.direction
            and abs(src.bp_index - dst.bp_index) == 1
        )
        extension_junction = (
            getattr(src, "extension_id", None) is not None
            or getattr(dst, "extension_id", None) is not None
        )
        if not (regular_run or extension_junction):
            continue  # crossover / skip / extra-base bridge — already handled
        key = ((src.strand_id, src.seq_num), (dst.strand_id, dst.seq_num))
        if key in seen:
            continue
        seen.add(key)
        if extension_junction:
            src_s, dst_s = by_res[key[0]], by_res[key[1]]
            # Distribute any residual CG/atomistic span mismatch across the whole
            # C3'-O3'-P-O5'-C5' linker. Pinning only O3'-P merely transfers the
            # break into C3'-O3' and P-O5'. This deterministic closure is also fast
            # enough for hundreds of Voltron tail junctions per trajectory frame.
            _interpolate_backbone_bridge(atoms, src_s, dst_s)
        else:
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


def _align_glycosidic(
    atoms: list[Atom],
    residue: str,
    sugar_name_to_serial: dict[str, int],
    base_name_to_serial: dict[str, int],
    target_c1n: _np.ndarray,
    rotate_phosphate: bool = False,
) -> str:
    """Rotate a single-stranded residue's ribose + base as a rigid body about C2′ so
    its C1′→N glycosidic bond points along *target_c1n*, in place.  Returns the
    glycosidic nitrogen's atom name (``N9`` for purines, ``N1`` for pyrimidines).

    The phosphate group (P, OP1, OP2, O5′) is normally held fixed — it is the anchor
    the backbone bridge minimiser then works against.  Shared verbatim by the crossover
    extra-base placer and the strand-extension tail placer, which need the identical
    base orientation.

    ``rotate_phosphate=True`` rotates the WHOLE nucleotide (phosphate included) as one
    rigid unit.  Use it when the bridge minimiser is SKIPPED (a position-only override
    insert): excluding the phosphate would strand P/OP1/OP2/O5′ at the template position
    and stretch the intra-residue O5′-C5′ bond to ~0.6 nm — a fatal 4 fs RATTLE start
    (the 24hb 4 fs blocker; see NAMD_4FS_RATTLE_RESEARCH.md).
    """
    _glycosidic_n = "N9" if residue in ("DA", "DG") else "N1"
    _n_serial = base_name_to_serial.get(_glycosidic_n)
    _c1_serial = sugar_name_to_serial.get("C1'")
    _c2_serial = sugar_name_to_serial.get("C2'")
    if _n_serial is None or _c1_serial is None or _c2_serial is None:
        return _glycosidic_n

    _c1_pos = _atom_pos(atoms, _c1_serial)
    _n_pos = _atom_pos(atoms, _n_serial)
    _c2_pos = _atom_pos(atoms, _c2_serial)
    _c1n_dir = _normalise(_n_pos - _c1_pos)
    _rot_ax = _np.cross(_c1n_dir, target_c1n)
    _sin_t = float(_np.linalg.norm(_rot_ax))
    _cos_t = float(_np.dot(_c1n_dir, target_c1n))
    if _sin_t < 1e-9:
        if _cos_t < 0.0:
            # 180° rotation — pick an arbitrary perpendicular axis
            _perp = _np.array([0.0, 0.0, 1.0])
            if abs(float(_np.dot(_c1n_dir, _perp))) > 0.9:
                _perp = _np.array([1.0, 0.0, 0.0])
            _rot_ax = _normalise(_np.cross(_c1n_dir, _perp))
            _R_align = 2.0 * _np.outer(_rot_ax, _rot_ax) - _np.eye(3)
        else:
            _R_align = _np.eye(3)
    else:
        _k = _rot_ax / _sin_t
        _K = _np.array(
            [
                [0.0, -_k[2], _k[1]],
                [_k[2], 0.0, -_k[0]],
                [-_k[1], _k[0], 0.0],
            ]
        )
        _R_align = _np.eye(3) + _sin_t * _K + (1.0 - _cos_t) * (_K @ _K)

    _phosphate = set() if rotate_phosphate else {"P", "OP1", "OP2", "O5'"}
    for _aname, _s in sugar_name_to_serial.items():
        if _aname not in _phosphate:
            _p_rel = _atom_pos(atoms, _s) - _c2_pos
            _set_atom_pos(atoms, _s, _c2_pos + _R_align @ _p_rel)
    for _aname, _s in base_name_to_serial.items():
        if _aname not in sugar_name_to_serial:
            _p_rel = _atom_pos(atoms, _s) - _c2_pos
            _set_atom_pos(atoms, _s, _c2_pos + _R_align @ _p_rel)

    return _glycosidic_n


def _extra_base_frame(
    origin: _np.ndarray,
    line_dir: _np.ndarray,
    bow_dir: _np.ndarray,
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

    e_y = _cross3(e_z, e_n)
    norm_y = float(_np.linalg.norm(e_y))
    if norm_y < 1e-9:
        fallback = _np.array([0.0, 0.0, 1.0])
        if abs(float(_np.dot(e_n, fallback))) > 0.9:
            fallback = _np.array([1.0, 0.0, 0.0])
        e_y = _cross3(e_z, fallback)
        norm_y = float(_np.linalg.norm(e_y))
    e_y = e_y / norm_y

    R = _np.column_stack([e_n, e_y, e_z])
    # Cancel template pre-compensation (+37.05° baked into all templates)
    R = R @ _FRAME_ROT_M
    return origin.copy(), R


def _sim_override_parts(
    value,
) -> tuple[_np.ndarray, "tuple[_np.ndarray, _np.ndarray] | None"]:
    """Normalise a synthetic-nucleotide override.

    Historical callers pass only a backbone-site ``ndarray``.  oxDNA display/export
    callers may additionally pass ``{"position", "a1", "a3"}``, allowing inserts
    and extensions to retain the simulated rigid orientation instead of being put
    back onto their native NADOC crossover/tail frame.
    """
    if isinstance(value, dict):
        pos = _np.asarray(value["position"], dtype=float)
        if value.get("a1") is not None and value.get("a3") is not None:
            return pos, (
                _np.asarray(value["a1"], dtype=float),
                _np.asarray(value["a3"], dtype=float),
            )
        return pos, None
    return _np.asarray(value, dtype=float), None


# ── Extra-base atom builder ───────────────────────────────────────────────────


def _build_extra_base_atoms(
    design: "Design",
    atoms: list[Atom],
    bonds: list[tuple[int, int]],
    serial: int,
    strand_to_chain: dict[str, str],
    nuc_pos_cache: dict[str, dict[tuple[int, "Direction"], "NucleotidePosition"]],
    helix_map: dict[str, object],
    bp_to_sugar_serials: dict[tuple[str, int, str], dict[str, int]],
    exclude_helix_ids: "set[str] | None",
    xb_pos_override: "dict[tuple[str, int], _np.ndarray] | None" = None,
    bridge_fn=_minimize_backbone_bridge,
    fast_bridges: bool = False,
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
        ha = _NS(
            helix_id=fl.three_prime_helix_id,
            index=fl.three_prime_bp,
            strand=fl.three_prime_direction,
        )
        hb = _NS(
            helix_id=fl.five_prime_helix_id,
            index=fl.five_prime_bp,
            strand=fl.five_prime_direction,
        )
        xovers_with_extra.append(
            _NS(id=fl.id, extra_bases=fl.extra_bases, half_a=ha, half_b=hb)
        )

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

        posA = nucA.position
        posB = nucB.position
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
        chain_id = strand_to_chain.get(strand_id, "A") if strand_id else "A"

        # Sugar serial dicts for junction nucleotides (may be None if excluded)
        src_s = bp_to_sugar_serials.get(src_key)
        dst_s = bp_to_sugar_serials.get(dst_key)

        # Interpolation line: the two junction nucleotides' CG BACKBONE positions.
        #
        # These atoms are placed FROM the CG representation, not independently of it:
        # the CG view is the single definition of where an extra base sits, and this
        # reproduces it. Same endpoints, same quadratic Bezier, same bow as
        # crossover_connections.js — so an insert's atoms land on the bead the user
        # is looking at, by construction rather than by agreement.
        line_p0 = _np.array(pos_src)
        line_p1 = _np.array(pos_dst)
        line_len = float(_np.linalg.norm(line_p1 - line_p0))
        arc_ctrl = _arc_ctrl_pt(line_p0, line_p1, bow_dir)

        # Chain-direction endpoints for a SIMULATED insert stay the real C3'/C5'
        # ATOMS.  That path orients a nucleotide from measured a1 against the
        # direction of its bonded neighbours, which is a fact about the atoms, not
        # about where the CG view draws the bead.
        chain_p0 = (
            _atom_pos(atoms, src_s["C3'"])
            if src_s is not None and "C3'" in src_s
            else line_p0
        )
        chain_p1 = (
            _atom_pos(atoms, dst_s["C5'"])
            if dst_s is not None and "C5'" in dst_s
            else line_p1
        )

        n = len(xo.extra_bases)
        eb_sugar_serials: list[dict[str, int]] = []
        eb_glycosidic_ns: list[str] = []

        simulated_insert_sites = {
            k: _sim_override_parts(xb_pos_override[(xo.id, k)])[0]
            for k in range(n)
            if xb_pos_override is not None and (xo.id, k) in xb_pos_override
        }

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
            _xb_sim = (
                xb_pos_override.get((xo.id, i - 1))
                if xb_pos_override is not None
                else None
            )
            _xb_frame = None
            if _xb_sim is not None:
                origin_pos, _xb_frame = _sim_override_parts(_xb_sim)
                prev_site = simulated_insert_sites.get(i - 2, chain_p0)
                next_site = simulated_insert_sites.get(i, chain_p1)
                relaxed_dir = next_site - prev_site
                if float(_np.linalg.norm(relaxed_dir)) > 1e-9:
                    arc_dir = _normalise(relaxed_dir)
            if _xb_frame is not None:
                sim_a1, _sim_a3 = _xb_frame
                # Chemical chain direction comes from the actual simulated 5'/3'
                # neighbours.  a1 contributes only the base-facing axis, projected
                # perpendicular to that chain.  Raw a3 is a nucleotide body axis,
                # not a guarantee that C5'/C3' point at the bonded neighbours.
                origin, R = _extra_base_frame(origin_pos, arc_dir, _normalise(sim_a1))
            else:
                origin, R = _extra_base_frame(origin_pos, arc_dir, bow_dir)

            residue = _BASE_CHAR_TO_RESIDUE.get(base_char.upper(), "DT")
            extra_seq_num[chain_id] = extra_seq_num.get(chain_id, 0) + 1
            seq_num = extra_seq_num[chain_id]

            # ── Sugar atoms ──────────────────────────────────────────────────
            _aux_t = float(i) / float(n + 1)
            sugar_name_to_serial: dict[str, int] = {}
            # NOT switched to the measured template, deliberately.  The insert placer
            # is calibrated against the legacy template's local origin: its atoms are
            # required to sit ON the CG chord (extra-base positions are a READ of the CG
            # representation, never an independent placement), and swapping the template
            # under it moved the insert origin 0.41 nm off that chord.  Making these
            # native means re-deriving the placer against the new local origin — real
            # work, and separable from the duplex.
            for atom_name, element, n_c, y_c, z_c in _SUGAR:
                local = _np.array([n_c, y_c, z_c])
                world = origin + R @ local
                atoms.append(
                    Atom(
                        serial=serial,
                        name=atom_name,
                        element=element,
                        residue=residue,
                        chain_id=chain_id,
                        seq_num=seq_num,
                        x=float(world[0]),
                        y=float(world[1]),
                        z=float(world[2]),
                        strand_id=strand_id or "",
                        helix_id=src_key[0],
                        bp_index=src_key[1],
                        direction=src_key[2],
                        aux_helix_id=dst_key[0],
                        aux_t=_aux_t,
                        crossover_id=xo.id,
                        extra_base_k=i - 1,
                    )
                )
                sugar_name_to_serial[atom_name] = serial
                serial += 1

            # ── Base atoms (FORWARD template convention for all extra bases) ─
            base_atoms_def, base_bond_defs = BASE_TEMPLATES[residue]
            base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
            for atom_name, element, n_c, y_c, z_c in base_atoms_def:
                local = _np.array([n_c, y_c, z_c])
                world = origin + R @ local
                atoms.append(
                    Atom(
                        serial=serial,
                        name=atom_name,
                        element=element,
                        residue=residue,
                        chain_id=chain_id,
                        seq_num=seq_num,
                        x=float(world[0]),
                        y=float(world[1]),
                        z=float(world[2]),
                        strand_id=strand_id or "",
                        helix_id=src_key[0],
                        bp_index=src_key[1],
                        direction=src_key[2],
                        aux_helix_id=dst_key[0],
                        aux_t=_aux_t,
                        crossover_id=xo.id,
                        extra_base_k=i - 1,
                    )
                )
                base_name_to_serial[atom_name] = serial
                serial += 1

            # Glycosidic nitrogen — the bond partner's NAME only.  The residue is
            # stamped in the frame above and is not rotated afterwards.
            _glycosidic_n = "N9" if residue in {"DA", "DG"} else "N1"

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
            p = next_s_item.get("P")
            if o3 is not None and p is not None:
                bonds.append((o3, p))

        # Simulated insert centres are authoritative, but their coarse frames do not
        # contain explicit phosphodiester atoms.  Close only the linker atoms after
        # the chain-aware rigid placement above; never translate the ribose/base off
        # its oxDNA site and never reuse a native-junction minimiser cache.
        _xb_overridden = xb_pos_override is not None and (xo.id, 0) in xb_pos_override
        first_override = (
            (xb_pos_override or {}).get((xo.id, 0)) if _xb_overridden else None
        )
        _xb_constrained = (
            isinstance(first_override, dict) and first_override.get("cm") is not None
        )
        if _xb_constrained:
            # Coarse oxDNA sites are particle centres, not atomistic sugar anchors.
            # After orienting every rigid nucleotide, make a small tethered
            # translation (max 0.35 nm) of insert bodies so adjacent C3'->C5'
            # spans approach the ~0.60 nm available contour length.  This preserves
            # each base's oxDNA orientation and keeps its centre close to the
            # simulated site, while avoiding transferring the entire frame mismatch
            # into O3'/P/O5' covalent bonds.
            shifts = [_np.zeros(3) for _ in eb_sugar_serials]
            body_index = {id(s): i for i, s in enumerate(eb_sugar_serials)}
            target_span = 0.60
            max_shift = 0.35
            for _ in range(10):
                corr = [_np.zeros(3) for _ in eb_sugar_serials]
                weight = [0 for _ in eb_sugar_serials]
                for prev_s_item, next_s_item in zip(all_s, all_s[1:]):
                    if "C3'" not in prev_s_item or "C5'" not in next_s_item:
                        continue
                    gap = _atom_pos(atoms, next_s_item["C5'"]) - _atom_pos(
                        atoms, prev_s_item["C3'"]
                    )
                    gl = float(_np.linalg.norm(gap))
                    if gl <= target_span or gl < 1e-12:
                        continue
                    excess = gap * ((gl - target_span) / gl)
                    pi = body_index.get(id(prev_s_item))
                    ni = body_index.get(id(next_s_item))
                    movable = int(pi is not None) + int(ni is not None)
                    if movable == 0:
                        continue
                    if pi is not None:
                        corr[pi] += excess / movable
                        weight[pi] += 1
                    if ni is not None:
                        corr[ni] -= excess / movable
                        weight[ni] += 1
                moved = False
                for bi, sdict in enumerate(eb_sugar_serials):
                    if not weight[bi]:
                        continue
                    step = 0.55 * corr[bi] / weight[bi]
                    proposed = shifts[bi] + step
                    pn = float(_np.linalg.norm(proposed))
                    if pn > max_shift:
                        proposed *= max_shift / pn
                    delta = proposed - shifts[bi]
                    if float(_np.linalg.norm(delta)) < 1e-7:
                        continue
                    shifts[bi] = proposed
                    for serial_i in set(sdict.values()):
                        a = atoms[serial_i]
                        a.x += float(delta[0])
                        a.y += float(delta[1])
                        a.z += float(delta[2])
                    moved = True
                if not moved:
                    break
            for prev_s_item, next_s_item in zip(all_s, all_s[1:]):
                bridge_fn(atoms, prev_s_item, next_s_item)
        elif _xb_overridden:
            pass  # legacy position-only override remains strictly authoritative
        else:
            # Close the phosphodiester linker; the inserts are left where the CG
            # mapping above placed them.
            for prev_s_item, next_s_item in zip(all_s, all_s[1:]):
                bridge_fn(atoms, prev_s_item, next_s_item)

    return serial


def _reciprocal_crossover_id_pairs(design) -> list:
    """(crossover_id_a, crossover_id_b) for every antiparallel reciprocal pair."""
    from backend.core.junction_topology import (  # noqa: PLC0415
        crossover_connectors,
        reciprocal_pairs,
    )

    conns = crossover_connectors(design)
    out = []
    for i, j in reciprocal_pairs(conns):
        a, b = conns[i].crossover_id, conns[j].crossover_id
        if a and b:
            out.append((a, b))
    return out


def _build_extension_atoms(
    design: "Design",
    atoms: list[Atom],
    bonds: list[tuple[int, int]],
    serial: int,
    strand_to_chain: dict[str, str],
    nuc_pos_cache: dict[str, dict[tuple[int, "Direction"], "NucleotidePosition"]],
    bp_to_sugar_serials: dict[tuple[str, int, str], dict[str, int]],
    ext_pos_override: "dict[tuple[str, int], _np.ndarray] | None" = None,
    bridge_fn=_minimize_backbone_bridge,
) -> int:
    """Place all-atom residues for every strand extension (5′/3′ terminal tail).

    The sibling of :func:`_build_extra_base_atoms`, and simpler in exactly one way
    that matters: an extra base BRIDGES two anchors (C3′(src) → C5′(dst)), whereas a
    tail hangs off ONE.  That is why the bridge minimisers ``_minimize_{1,2,3}_extra_base``
    cannot be reused here — they solve for a linker pinned at both ends.  Each
    consecutive pair along the tail instead gets ``_minimize_backbone_bridge`` (already
    the ``n > 3`` fallback for extra bases), and the tail's FREE terminus gets no bridge
    at all: its dangling O3′ (3′ tail) or P/O5′ (5′ tail) is exactly what a chain
    terminus is.

    Positions reuse the SAME Bézier arc the CG geometry lays down
    (``design_geometry._strand_extension_geometry``) so the all-atom and coarse-grained
    tails agree, but rooted on the anchor's real C3′/C5′ ATOM rather than its CG bead —
    the trick ``_build_extra_base_atoms`` uses to get physical O3′→P bond lengths.

    Modification-only extensions (a fluorophore, no ``sequence``) contribute nothing:
    they are not DNA and have no residue.

    ``ext_pos_override`` maps ``(extension_id, k)`` → a real simulated backbone
    position; when present the tail is placed at its RELAXED pose (heavy-rep display)
    and the bridge minimisation is skipped, mirroring ``xb_pos_override``.
    """
    from backend.core.constants import SSDNA_CONTOUR_PER_NT_NM

    strand_by_id = {s.id: s for s in design.strands}

    # Continue each chain's residue numbering; _thread_inserts_inline re-threads later.
    tail_seq_num: dict[str, int] = {}
    for a in atoms:
        cur = tail_seq_num.get(a.chain_id, 0)
        if a.seq_num > cur:
            tail_seq_num[a.chain_id] = a.seq_num

    for ext in design.extensions:
        if not ext.sequence:
            continue
        strand = strand_by_id.get(ext.strand_id)
        if strand is None or not strand.domains:
            continue

        five = ext.end == "five_prime"
        dom = strand.domains[0] if five else strand.domains[-1]
        bp = dom.start_bp if five else dom.end_bp
        anchor_key = (dom.helix_id, bp, dom.direction.value)

        anchor_s = bp_to_sugar_serials.get(anchor_key)
        if anchor_s is None:
            continue  # anchor is on an excluded helix — nothing to hang from

        # nuc_pos_cache is keyed (bp, Direction, copy_k); copy 0 is the base nucleotide
        # (a loop insertion adds copies 1…n, which a terminal anchor never is).
        nuc = (nuc_pos_cache.get(dom.helix_id) or {}).get((bp, dom.direction, 0))
        if nuc is None:
            continue

        # Root the arc on the real terminal sugar atom the tail bonds THROUGH:
        # a 3′ tail leaves via the anchor's O3′/C3′, a 5′ tail enters via its C5′.
        root_name = "C3'" if not five else "C5'"
        root_serial = anchor_s.get(root_name)
        if root_serial is None:
            continue
        p0 = _atom_pos(atoms, root_serial)

        # Same construction as the CG arc: radially outward in the DEFORMED frame,
        # bowing the way the strand was already heading as it left the duplex.
        radial = _normalise(-_np.asarray(nuc.base_normal, dtype=float))
        chain_tan = _np.asarray(nuc.axis_tangent, dtype=float)
        if dom.direction == Direction.REVERSE:
            chain_tan = -chain_tan
        bow_dir = chain_tan if not five else -chain_tan
        bow_dir = bow_dir - float(_np.dot(bow_dir, radial)) * radial
        if float(_np.linalg.norm(bow_dir)) < 1e-6:
            bow_dir = _np.cross(radial, _np.array([0.0, 0.0, 1.0]))
            if float(_np.linalg.norm(bow_dir)) < 1e-6:
                bow_dir = _np.cross(radial, _np.array([0.0, 1.0, 0.0]))
        bow_dir = _normalise(bow_dir)

        n = len(ext.sequence)
        arc_len = n * SSDNA_CONTOUR_PER_NT_NM
        p2 = p0 + radial * arc_len
        ctrl = (p0 + p2) * 0.5 + bow_dir * (arc_len * 0.30)

        simulated_sites = {
            i: _sim_override_parts(ext_pos_override[(ext.id, i)])[0]
            for i in range(n)
            if ext_pos_override and (ext.id, i) in ext_pos_override
        }

        chain_id = strand_to_chain.get(strand.id, "A")
        strand_id = strand.id

        # Base orientation target, mirroring the extra-base rule.
        avg_axis = _normalise(_np.asarray(nuc.axis_tangent, dtype=float))
        tail_sugars: list[dict[str, int]] = []

        for i in range(n):  # i = distance rank from the anchor
            t = (i + 1) / n
            origin_pos = _bezier_pt(p0, ctrl, p2, t)
            arc_tan = _bezier_tan(p0, ctrl, p2, t)
            # 5′→3′ runs OUTWARD along the arc for a 3′ tail, INWARD for a 5′ tail.
            chain_dir = arc_tan if not five else -arc_tan

            sim = (ext_pos_override or {}).get((ext.id, i))
            sim_frame = None
            if sim is not None:
                origin_pos, sim_frame = _sim_override_parts(sim)

                # A relaxed ssDNA tail is free to fold past its original Bezier
                # tangent. Orient its atom template from the SIMULATED polyline,
                # always in chemical 5'->3' order, rather than retaining a stale
                # design tangent that can swap the C3'/C5' ends. ext_k increases
                # away from the anchor for both tail types.
                if five:
                    three_side = simulated_sites.get(i - 1, p0)
                    five_side = simulated_sites.get(i + 1)
                    relaxed_dir = (
                        three_side - origin_pos
                        if five_side is None
                        else three_side - five_side
                    )
                else:
                    five_side = simulated_sites.get(i - 1, p0)
                    three_side = simulated_sites.get(i + 1)
                    relaxed_dir = (
                        origin_pos - five_side
                        if three_side is None
                        else three_side - five_side
                    )
                if float(_np.linalg.norm(relaxed_dir)) > 1e-9:
                    chain_dir = _normalise(relaxed_dir)

            if sim_frame is not None:
                sim_a1, _sim_a3 = sim_frame
                origin, R = _extra_base_frame(origin_pos, chain_dir, _normalise(sim_a1))
            else:
                origin, R = _extra_base_frame(origin_pos, chain_dir, bow_dir)

            # The tail's sequence is stored 5′→3′.  For a 3′ tail bead i IS the i-th
            # base from the 5′ end of the tail; for a 5′ tail the OUTERMOST bead
            # (i = n-1) is the 5′ terminus, so the order reverses.
            base_char = ext.sequence[i] if not five else ext.sequence[n - 1 - i]
            residue = _BASE_CHAR_TO_RESIDUE.get(base_char.upper(), "DT")

            z_sign = float(_np.dot(_np.cross(bow_dir, chain_dir), avg_axis))
            target_c1n = avg_axis if z_sign > 0.0 else -avg_axis

            tail_seq_num[chain_id] = tail_seq_num.get(chain_id, 0) + 1
            seq_num = tail_seq_num[chain_id]

            def _emit(atom_name, element, local) -> int:
                nonlocal serial
                world = origin + R @ local
                atoms.append(
                    Atom(
                        serial=serial,
                        name=atom_name,
                        element=element,
                        residue=residue,
                        chain_id=chain_id,
                        seq_num=seq_num,
                        x=float(world[0]),
                        y=float(world[1]),
                        z=float(world[2]),
                        strand_id=strand_id or "",
                        # Anchor's key (like extra bases): the topology writers are
                        # unchanged; extension_id/ext_k give the tail its own identity.
                        helix_id=anchor_key[0],
                        bp_index=anchor_key[1],
                        direction=anchor_key[2],
                        extension_id=ext.id,
                        ext_k=i,
                    )
                )
                s = serial
                serial += 1
                return s

            sugar_name_to_serial: dict[str, int] = {}
            # Legacy template, for the same reason as the extra-base placer above:
            # the tail linker geometry is calibrated against it, and swapping it
            # stretched a tail backbone bond to 3.5 A (physical limit 3.2).
            for atom_name, element, n_c, y_c, z_c in _SUGAR:
                sugar_name_to_serial[atom_name] = _emit(
                    atom_name, element, _np.array([n_c, y_c, z_c])
                )

            base_atoms_def, base_bond_defs = BASE_TEMPLATES[residue]
            base_name_to_serial: dict[str, int] = {**sugar_name_to_serial}
            for atom_name, element, n_c, y_c, z_c in base_atoms_def:
                base_name_to_serial[atom_name] = _emit(
                    atom_name, element, _np.array([n_c, y_c, z_c])
                )

            if sim_frame is None:
                # Same phosphate-stranding guard as the crossover placer: a position-only
                # override tail (sim set, no frame) skips the bridge minimiser, so rotate the
                # phosphate rigidly with its sugar; a geometric tail (sim is None) keeps it
                # fixed (byte-unchanged) for the minimiser to place.
                _align_glycosidic(
                    atoms,
                    residue,
                    sugar_name_to_serial,
                    base_name_to_serial,
                    target_c1n,
                    rotate_phosphate=sim is not None,
                )

            for a_name, b_name in _SUGAR_BONDS:
                sa, sb = (
                    sugar_name_to_serial.get(a_name),
                    sugar_name_to_serial.get(b_name),
                )
                if sa is not None and sb is not None:
                    bonds.append((sa, sb))
            for a_name, b_name in base_bond_defs:
                sa, sb = (
                    base_name_to_serial.get(a_name),
                    base_name_to_serial.get(b_name),
                )
                if sa is not None and sb is not None:
                    bonds.append((sa, sb))

            tail_sugars.append(dict(base_name_to_serial))

        # ── Backbone through the tail, in 5′→3′ chain order ───────────────────
        #   3′ tail: anchor → bead0 → … → bead(n-1)   (free O3′ at the tip)
        #   5′ tail: bead(n-1) → … → bead0 → anchor   (free P/O5′ at the tip; the
        #            ANCHOR's phosphate is now an internal linkage, not the 5′ end)
        chain_s = (
            ([anchor_s] + tail_sugars) if not five else (tail_sugars[::-1] + [anchor_s])
        )
        for prev_s, next_s in zip(chain_s, chain_s[1:]):
            o3, p = prev_s.get("O3'"), next_s.get("P")
            if o3 is not None and p is not None:
                bonds.append((o3, p))

        # The simulated bead centres stay fixed; only the explicit linker atoms are
        # re-seated because oxDNA does not provide atomistic O3'/P/O5' coordinates.
        for prev_s, next_s in zip(chain_s, chain_s[1:]):
            bridge_fn(atoms, prev_s, next_s)

    return serial


# ── Serialisation helper ──────────────────────────────────────────────────────


def atomistic_to_json(model: AtomisticModel) -> dict:
    """Convert AtomisticModel to a JSON-serialisable dict for the API."""
    return {
        "atoms": [
            {
                "serial": a.serial,
                "name": a.name,
                "element": a.element,
                "residue": a.residue,
                "chain_id": a.chain_id,
                "seq_num": a.seq_num,
                "x": round(a.x, 5),
                "y": round(a.y, 5),
                "z": round(a.z, 5),
                "strand_id": a.strand_id,
                "helix_id": a.helix_id,
                "bp_index": a.bp_index,
                "direction": a.direction,
                "is_modified": a.is_modified,
                "aux_helix_id": a.aux_helix_id,
                "aux_t": a.aux_t,
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

    Vectorised: the per-atom ``round()`` loop cost ~997k builtin calls (~0.6 s) per frame
    on a 330k-atom design, which a trajectory export pays once per frame. Both Python's
    ``round`` and ``np.round`` round half-to-even on float64; any residual disagreement is
    a sub-ULP tie at the 5th decimal (1e-5 nm = 1e-4 Å), far below the model's precision.
    Pinned against the original loop by ``TestAtomisticPositionsFlat``.
    """
    atoms = model.atoms
    if not atoms:
        return []
    atom_count = len(atoms)
    # Atom serials are dense and 0-based but not necessarily in list order — scatter by
    # serial exactly as the old loop did, rather than assuming atoms[i].serial == i.
    # zeros (not empty): a gap in the serials must read 0.0, as it did in the loop.
    xyz = _np.zeros((atom_count, 3), dtype=float)
    serials = _np.fromiter((a.serial for a in atoms), dtype=_np.intp, count=atom_count)
    xyz[serials, 0] = _np.fromiter((a.x for a in atoms), dtype=float, count=atom_count)
    xyz[serials, 1] = _np.fromiter((a.y for a in atoms), dtype=float, count=atom_count)
    xyz[serials, 2] = _np.fromiter((a.z for a in atoms), dtype=float, count=atom_count)
    return _np.round(xyz, 5).reshape(-1).tolist()
