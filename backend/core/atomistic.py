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
import math as _math
import threading as _threading
import numpy as _np
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from scipy.optimize import minimize as _scipy_minimize

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import (
    NucleotidePosition,
    nucleotide_positions,
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
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
            ))
        for i, j in model.bonds:
            bonds.append((i + offset, j + offset))
        offset += len(model.atoms)
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
            for bp in domain_bp_range(domain):
                if idx >= len(seq):
                    break
                delta = ls_lookup.get((h_id, bp), 0)
                if delta <= -1:
                    continue  # deletion: no character in scadnano sequence string
                n_copies = max(1, delta + 1)
                for copy_k in range(n_copies):
                    if idx >= len(seq):
                        break
                    # k=0 uses the plain 3-tuple key for backward compat;
                    # k≥1 uses a 4-tuple key to distinguish loop copies.
                    key: tuple = (h_id, bp, dir_str) if copy_k == 0 else (h_id, bp, dir_str, copy_k)
                    seq_map[key] = seq[idx]
                    idx += 1
    return seq_map


# ── Model builder ─────────────────────────────────────────────────────────────


def build_atomistic_model(
    design: Design,
    exclude_helix_ids: set[str] | None = None,
    nuc_pos_override: "dict[tuple[str, int, str], _np.ndarray] | None" = None,
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

            for bp in domain_bp_range(domain):
                copy_k = 0
                while True:
                    nuc_pos = nuc_positions.get((bp, direction, copy_k))
                    if nuc_pos is None:
                        break  # no more copies at this bp (includes skip positions)

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

                    # Compute helix axis point for radial correction
                    ax_start, ax_hat, bp_start = _helix_axis_cache[h_id]
                    axis_pt = ax_start + (bp - bp_start) * BDNA_RISE_PER_BP * ax_hat

                    origin, R = _atom_frame(nuc_pos, direction, axis_point=axis_pt,
                                            helix_direction=helix.direction)

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
                    # Register full sugar serial map for crossover/skip bridge
                    # (always overwritten → last copy wins, which is what src lookups want).
                    bp_to_sugar_serials[(h_id, bp, dir_str)] = dict(sugar_name_to_serial)

                    copy_k += 1  # advance to next loop copy

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
            for bp in domain_bp_range(domain):
                copy_k2 = 0
                found_any = False
                while True:
                    entry = bp_to_serials.get((h_id, bp, dir_str, copy_k2))
                    if entry is None:
                        break
                    found_any = True
                    o3_serial, p_serial = entry
                    if prev_o3_serial is not None and p_serial is not None:
                        # Skip direct bond if the previous nucleotide is the 3′
                        # junction of an extra-base crossover (handled separately).
                        if prev_nuc_key not in extra_base_xover_src:
                            bonds.append((prev_o3_serial, p_serial))
                    prev_o3_serial = o3_serial
                    prev_nuc_key   = (h_id, bp, dir_str)
                    copy_k2 += 1
                if not found_any:
                    prev_o3_serial = None
                    prev_nuc_key   = None

    # ── Crossover phosphate bridge interpolation ──────────────────────────────
    # At each crossover (consecutive domains on different helices sharing the
    # same bp position), linearly interpolate the backbone atoms between
    # C4′(N) and C3′(N+1) to reduce geometric strain in GROMACS simulations.
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
                    _interpolate_backbone_bridge(atoms, src_s, dst_s)

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

            for bp in domain_bp_range(domain):
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
    )

    # ── Apply deformations (bend/twist) and cluster rigid transforms ──────────
    # All atom positions above are placed in straight (undeformed) geometry.
    # This final pass rotates/translates every atom to match the deformed 3-D view.
    from backend.core.deformation import apply_deformations_to_atoms
    apply_deformations_to_atoms(atoms, design)

    return AtomisticModel(atoms=atoms, bonds=bonds)


def _normalise(v: _np.ndarray) -> _np.ndarray:
    n = float(_np.linalg.norm(v))
    return v / n if n > 1e-9 else v


# ── Crossover interpolation helpers ──────────────────────────────────────────

def _lerp(p0: _np.ndarray, p1: _np.ndarray, t: float) -> _np.ndarray:
    return p0 + t * (p1 - p0)


def _atom_pos(atoms: list[Atom], serial: int) -> _np.ndarray:
    a = atoms[serial]
    return _np.array([a.x, a.y, a.z])


def _set_atom_pos(atoms: list[Atom], serial: int, pos: _np.ndarray) -> None:
    a = atoms[serial]
    a.x, a.y, a.z = float(pos[0]), float(pos[1]), float(pos[2])


def _translate_atom(atoms: list[Atom], serial: int, delta: _np.ndarray) -> None:
    a = atoms[serial]
    a.x += float(delta[0])
    a.y += float(delta[1])
    a.z += float(delta[2])


# ── Backbone bridge interpolation ─────────────────────────────────────────────

def _interpolate_backbone_bridge(
    atoms: list[Atom],
    src_s: dict[str, int],
    dst_s: dict[str, int],
) -> None:
    """
    Linearly interpolate the phosphodiester linker atoms between C3′(src) and
    C5′(dst), leaving both ribose rings — and their canonical C4′ positions —
    completely undisturbed.

    C3′(src) is the ring carbon at the 3′ exit of the src ribose; C5′(dst) is
    the exocyclic carbon at the 5′ entry of the dst ribose.  Neither is moved.
    Only the three true linker atoms spanning the junction are repositioned:

      O3′(src) → t=1/4  (quarter-way from C3′(src) to C5′(dst))
      P(dst)   → t=2/4  (midpoint)
      O5′(dst) → t=3/4  (three-quarters)

    Branch atoms OP1(dst)/OP2(dst) are rigidly translated by the same delta
    as P(dst).
    """
    if "C3'" not in src_s or "C5'" not in dst_s or "P" not in dst_s:
        return
    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])

    orig_P    = _atom_pos(atoms, dst_s["P"])
    new_P_pos = _lerp(c3_src, c5_dst, 2.0 / 4.0)
    delta_P   = new_P_pos - orig_P

    for serials_dict, aname, t in (
        (src_s, "O3'", 1.0 / 4.0),
        (dst_s, "P",   2.0 / 4.0),
        (dst_s, "O5'", 3.0 / 4.0),
    ):
        s = serials_dict.get(aname)
        if s is not None:
            _set_atom_pos(atoms, s, _lerp(c3_src, c5_dst, t))

    for op in ("OP1", "OP2"):
        s = dst_s.get(op)
        if s is not None:
            _translate_atom(atoms, s, delta_P)


# ── Canonical backbone geometry (AMBER ff14SB / B-DNA) ───────────────────────

_CANON_C3O3:  float = 0.1430   # C3′–O3′ bond length (nm)
_CANON_O3P:   float = 0.1600   # O3′–P   bond length (nm)
_CANON_PO5:   float = 0.1590   # P–O5′   bond length (nm)
_CANON_O5C5:  float = 0.1440   # O5′–C5′ bond length (nm)
_CANON_C3O3P: float = 119.0    # ∠C3′–O3′–P  (degrees)
_CANON_O3PO5: float = 103.6    # ∠O3′–P–O5′  (degrees)
_CANON_PO5C5: float = 120.9    # ∠P–O5′–C5′  (degrees)
_DEG2RAD: float = _math.pi / 180.0
# Precomputed cosines of canonical backbone angles (used in joint objective functions)
_COS_C3O3P: float = _math.cos(_CANON_C3O3P * _DEG2RAD)
_COS_O3PO5: float = _math.cos(_CANON_O3PO5 * _DEG2RAD)
_COS_PO5C5: float = _math.cos(_CANON_PO5C5 * _DEG2RAD)

# Phosphate group atoms — treated as free backbone linkers, not part of the ribose rigid body
_PHOSPHATE_ATOMS: frozenset[str] = frozenset({"P", "OP1", "OP2", "O5'"})

# ── Minimisation result cache (keyed by junction geometry) ───────────────────
# Avoids re-running scipy when the atomistic view is toggled off/on without
# design changes.  Keyed by (xo.id, extra_bases, rounded C3′(src), rounded C5′(dst),
# rounded target_c1n).  Stores the optimised x vector from the solver.
_XB_CACHE:      dict[tuple, "_np.ndarray"] = {}
_XB_CACHE_MAX:  int = 512   # entries before a full eviction (simple LRU-free strategy)
_XB_CACHE_LOCK: "_threading.Lock" = _threading.Lock()

# Objective weights for joint extra-base minimisers
_W_GLYCOSIDIC: float = 2.0    # C1′→N alignment penalty (1 − cos θ; range [0, 2])
_W_REPULSION:  float = 100.0  # steric repulsion weight per clashing pair
_R_REPULSION:  float = 0.35   # nm — soft-sphere contact radius (≈ C–C vdW contact)

# Pre-computed chord fractions for proportional initial-guess placement of linker atoms.
# Placing linker atoms proportionally to canonical bond lengths (rather than using the
# template positions) reduces the initial objective by ~10×, cutting scipy iterations
# from ~150 to ~30 for typical crossover distances.
_TOTAL_LINKER_F: float = _CANON_C3O3 + _CANON_O3P + _CANON_PO5 + _CANON_O5C5   # 0.606 nm
_TOTAL_LINKER_B: float = _CANON_O3P  + _CANON_PO5 + _CANON_O5C5                # 0.463 nm
_FRAC_O3_F:  float = _CANON_C3O3                               / _TOTAL_LINKER_F
_FRAC_P_F:   float = (_CANON_C3O3 + _CANON_O3P)               / _TOTAL_LINKER_F
_FRAC_O5_F:  float = (_CANON_C3O3 + _CANON_O3P + _CANON_PO5)  / _TOTAL_LINKER_F
_FRAC_P_B:   float = _CANON_O3P                                / _TOTAL_LINKER_B
_FRAC_O5_B:  float = (_CANON_O3P   + _CANON_PO5)              / _TOTAL_LINKER_B


def _fwd_bridge_x0(
    c3_start: "_np.ndarray", c5_end: "_np.ndarray",
) -> "tuple[_np.ndarray, _np.ndarray, _np.ndarray]":
    """Proportional initial positions for O3′, P, O5′ along C3′→C5′ chord."""
    d = c5_end - c3_start
    return (
        c3_start + _FRAC_O3_F * d,
        c3_start + _FRAC_P_F  * d,
        c3_start + _FRAC_O5_F * d,
    )


def _bwd_bridge_x0(
    o3_start: "_np.ndarray", c5_end: "_np.ndarray",
) -> "tuple[_np.ndarray, _np.ndarray]":
    """Proportional initial positions for P, O5′ along O3′→C5′ chord."""
    d = c5_end - o3_start
    return (
        o3_start + _FRAC_P_B  * d,
        o3_start + _FRAC_O5_B * d,
    )


# ── Minimisation-based backbone bridge ───────────────────────────────────────

def _minimize_backbone_bridge(
    atoms: list[Atom],
    src_s: dict[str, int],
    dst_s: dict[str, int],
) -> None:
    """
    Place O3′(src), P(dst), O5′(dst) so that the C3′(src)→C5′(dst) bridge has
    bond lengths and angles close to canonical B-DNA values.

    Anchors (not moved): C3′(src), C5′(dst).
    Free atoms  (3 DOF each): O3′(src), P(dst), O5′(dst).
    OP1/OP2(dst) are rigidly translated by the same delta as P(dst).

    Objective: weighted sum of squared bond-length + bond-angle deviations.
    Bond lengths dominate (weight 1); angles are secondary (weight 0.1).
    Initial guess: 1/4, 2/4, 3/4 linear spacing (same as _interpolate_backbone_bridge).

    When the junction gap is larger than the canonical chain length (≈0.6 nm),
    the minimiser distributes the excess evenly while keeping angles as close to
    canonical as possible — strictly better than the collinear 180° interpolation.
    """
    if "C3'" not in src_s or "C5'" not in dst_s or "P" not in dst_s:
        return

    c3 = _atom_pos(atoms, src_s["C3'"])
    c5 = _atom_pos(atoms, dst_s["C5'"])

    cos_c3o3p = _math.cos(_CANON_C3O3P * _DEG2RAD)
    cos_o3po5 = _math.cos(_CANON_O3PO5 * _DEG2RAD)
    cos_po5c5 = _math.cos(_CANON_PO5C5 * _DEG2RAD)

    def _cos_angle(a: _np.ndarray, b: _np.ndarray, c: _np.ndarray) -> float:
        """Cosine of angle A–B–C."""
        ba = a - b; bc = c - b
        n1 = float(_np.linalg.norm(ba)); n2 = float(_np.linalg.norm(bc))
        if n1 < 1e-12 or n2 < 1e-12:
            return 1.0
        return float(_np.dot(ba, bc) / (n1 * n2))

    def objective(x: _np.ndarray) -> float:
        o3 = x[0:3]; p = x[3:6]; o5 = x[6:9]
        bl = (
            (_np.linalg.norm(o3 - c3) - _CANON_C3O3) ** 2 +
            (_np.linalg.norm(p  - o3) - _CANON_O3P)  ** 2 +
            (_np.linalg.norm(o5 - p)  - _CANON_PO5)  ** 2 +
            (_np.linalg.norm(c5 - o5) - _CANON_O5C5) ** 2
        )
        ba = (
            (_cos_angle(c3, o3, p)  - cos_c3o3p) ** 2 +
            (_cos_angle(o3, p,  o5) - cos_o3po5) ** 2 +
            (_cos_angle(p,  o5, c5) - cos_po5c5) ** 2
        )
        return float(bl + 0.1 * ba)

    x0 = _np.concatenate([
        _lerp(c3, c5, 1.0 / 4.0),
        _lerp(c3, c5, 2.0 / 4.0),
        _lerp(c3, c5, 3.0 / 4.0),
    ])

    res = _scipy_minimize(
        objective, x0, method="L-BFGS-B",
        options={"ftol": 1e-14, "gtol": 1e-9, "maxiter": 200},
    )
    o3_new = res.x[0:3]; p_new = res.x[3:6]; o5_new = res.x[6:9]

    orig_P  = _atom_pos(atoms, dst_s["P"])
    delta_P = p_new - orig_P

    s = src_s.get("O3'")
    if s is not None:
        _set_atom_pos(atoms, s, o3_new)
    for aname, pos in (("P", p_new), ("O5'", o5_new)):
        s = dst_s.get(aname)
        if s is not None:
            _set_atom_pos(atoms, s, pos)
    for op in ("OP1", "OP2"):
        s = dst_s.get(op)
        if s is not None:
            _translate_atom(atoms, s, delta_P)


# ── Shared helpers for joint extra-base minimisers ───────────────────────────


def _cos_angle_3pt(a: _np.ndarray, b: _np.ndarray, c: _np.ndarray) -> float:
    """Cosine of angle A–B–C; returns 1.0 for degenerate (zero-length) arms."""
    ba = a - b; bc = c - b
    n1 = float(_np.linalg.norm(ba)); n2 = float(_np.linalg.norm(bc))
    if n1 < 1e-12 or n2 < 1e-12:
        return 1.0
    return float(_np.dot(ba, bc) / (n1 * n2))


def _make_spin_rotation(axis: _np.ndarray, theta: float) -> _np.ndarray:
    """Rodrigues rotation matrix: rotation about unit *axis* by *theta* radians."""
    K = _np.array([
        [ 0.0,      -axis[2],  axis[1]],
        [ axis[2],   0.0,     -axis[0]],
        [-axis[1],   axis[0],  0.0    ],
    ])
    return _np.eye(3) + _math.sin(theta) * K + (1.0 - _math.cos(theta)) * (K @ K)


def _backbone_bridge_cost(
    c3: _np.ndarray, o3: _np.ndarray,
    p:  _np.ndarray, o5: _np.ndarray,
    c5: _np.ndarray,
) -> float:
    """
    Weighted squared-deviation cost for a C3′–O3′–P–O5′–C5′ chain.
    Bond-length weight = 1.0, bond-angle weight = 0.1.
    Uses module-level _COS_* and _CANON_* constants.
    """
    bl = (
        (_np.linalg.norm(o3 - c3) - _CANON_C3O3) ** 2 +
        (_np.linalg.norm(p  - o3) - _CANON_O3P)  ** 2 +
        (_np.linalg.norm(o5 - p)  - _CANON_PO5)  ** 2 +
        (_np.linalg.norm(c5 - o5) - _CANON_O5C5) ** 2
    )
    ba = (
        (_cos_angle_3pt(c3, o3, p)  - _COS_C3O3P) ** 2 +
        (_cos_angle_3pt(o3, p,  o5) - _COS_O3PO5) ** 2 +
        (_cos_angle_3pt(p,  o5, c5) - _COS_PO5C5) ** 2
    )
    return float(bl + 0.1 * ba)


# ── Analytical gradient helpers ───────────────────────────────────────────────


def _cos_angle_grad(
    A: _np.ndarray, B: _np.ndarray, C: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray, _np.ndarray]":
    """Cosine of angle A–B–C and its gradients w.r.t. A, B, C.

    Returns (cos, dA, dB, dC).  Returns (1.0, 0, 0, 0) for degenerate arms.
    """
    u = A - B;  nu = float(_np.linalg.norm(u))
    v = C - B;  nv = float(_np.linalg.norm(v))
    if nu < 1e-12 or nv < 1e-12:
        z = _np.zeros(3)
        return 1.0, z, z, z
    cos_t  = float(_np.dot(u, v) / (nu * nv))
    unorm  = u / nu;  vnorm = v / nv
    # d(cosθ)/dA = (v/nv − cosθ·u/nu) / nu
    dA = (vnorm - cos_t * unorm) / nu
    # d(cosθ)/dC = (u/nu − cosθ·v/nv) / nv
    dC = (unorm - cos_t * vnorm) / nv
    # d(cosθ)/dB = −(u+v)/(nu·nv) + cosθ·(u/nu² + v/nv²)
    dB = -(u + v) / (nu * nv) + cos_t * (u / (nu * nu) + v / (nv * nv))
    return cos_t, dA, dB, dC


def _backbone_bridge_cost_grad(
    c3: _np.ndarray, o3: _np.ndarray,
    p:  _np.ndarray, o5: _np.ndarray,
    c5: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray, _np.ndarray, _np.ndarray, _np.ndarray]":
    """Value and gradient of backbone bridge cost w.r.t. all 5 atoms.

    Returns (cost, g_c3, g_o3, g_p, g_o5, g_c5).
    c3/c5 gradients are used when those atoms belong to a rigid body.
    """
    d_c3o3 = o3 - c3;  n_c3o3 = float(_np.linalg.norm(d_c3o3))
    d_o3p  = p  - o3;  n_o3p  = float(_np.linalg.norm(d_o3p))
    d_po5  = o5 - p;   n_po5  = float(_np.linalg.norm(d_po5))
    d_o5c5 = c5 - o5;  n_o5c5 = float(_np.linalg.norm(d_o5c5))

    def _safe(n: float) -> float:
        return n if n > 1e-12 else 1e-12

    el1 = n_c3o3 - _CANON_C3O3
    el2 = n_o3p  - _CANON_O3P
    el3 = n_po5  - _CANON_PO5
    el4 = n_o5c5 - _CANON_O5C5

    bl = el1 ** 2 + el2 ** 2 + el3 ** 2 + el4 ** 2

    # Bond-length gradient: d/dx (|x-a|-L)² = 2(|x-a|-L)(x-a)/|x-a|
    u1 = d_c3o3 / _safe(n_c3o3);  u2 = d_o3p / _safe(n_o3p)
    u3 = d_po5  / _safe(n_po5);   u4 = d_o5c5 / _safe(n_o5c5)

    g_c3_bl = -2.0 * el1 * u1
    g_o3_bl =  2.0 * el1 * u1 - 2.0 * el2 * u2
    g_p_bl  =  2.0 * el2 * u2 - 2.0 * el3 * u3
    g_o5_bl =  2.0 * el3 * u3 - 2.0 * el4 * u4
    g_c5_bl =  2.0 * el4 * u4

    # Bond-angle gradients
    cos1, dA1, dB1, dC1 = _cos_angle_grad(c3, o3, p)   # ∠C3′-O3′-P:  A=c3, B=o3, C=p
    cos2, dA2, dB2, dC2 = _cos_angle_grad(o3, p,  o5)  # ∠O3′-P-O5′:  A=o3, B=p,  C=o5
    cos3, dA3, dB3, dC3 = _cos_angle_grad(p,  o5, c5)  # ∠P-O5′-C5′:  A=p,  B=o5, C=c5

    e1 = cos1 - _COS_C3O3P
    e2 = cos2 - _COS_O3PO5
    e3 = cos3 - _COS_PO5C5

    ba = e1 ** 2 + e2 ** 2 + e3 ** 2

    # Angle gradient: d/dx (cosθ - T)² = 2(cosθ-T) · d(cosθ)/dx
    # W = 2 * 0.1: factor of 2 from d(x²)/dx chain rule × 0.1 angle weight.
    # These g_*_ba terms are the COMPLETE angle contribution to the gradient;
    # do NOT multiply by 0.1 again in the return.
    W = 0.2
    g_c3_ba = W * e1 * dA1                              # ∠1: c3 is A
    g_o3_ba = W * (e1 * dB1 + e2 * dA2)                 # ∠1: o3 is B; ∠2: o3 is A
    g_p_ba  = W * (e1 * dC1 + e2 * dB2 + e3 * dA3)     # ∠1: p is C; ∠2: p is B; ∠3: p is A
    g_o5_ba = W * (e2 * dC2 + e3 * dB3)                 # ∠2: o5 is C; ∠3: o5 is B
    g_c5_ba = W * e3 * dC3                              # ∠3: c5 is C

    cost = float(bl + 0.1 * ba)
    return (
        cost,
        g_c3_bl + g_c3_ba,
        g_o3_bl + g_o3_ba,
        g_p_bl  + g_p_ba,
        g_o5_bl + g_o5_ba,
        g_c5_bl + g_c5_ba,
    )


def _spin_rotation_deriv(axis: _np.ndarray, theta: float) -> _np.ndarray:
    """Derivative dR/dθ of the Rodrigues rotation about *axis* by *theta*.

    dR/dθ = cos(θ)·K + sin(θ)·K² where K is the skew-symmetric cross-product
    matrix for *axis*.
    """
    K = _np.array([
        [ 0.0,      -axis[2],  axis[1]],
        [ axis[2],   0.0,     -axis[0]],
        [-axis[1],   axis[0],  0.0    ],
    ])
    return _math.cos(theta) * K + _math.sin(theta) * (K @ K)


def _glycosidic_cost_grad(
    c1_pos: _np.ndarray,
    n_pos:  _np.ndarray,
    target: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray]":
    """Glycosidic alignment cost = 1 − dot(c1n/|c1n|, target).

    Returns (cost, g_c1, g_n) — gradients w.r.t. c1_pos and n_pos.
    """
    c1n    = n_pos - c1_pos
    length = float(_np.linalg.norm(c1n))
    if length < 1e-9:
        return 0.0, _np.zeros(3), _np.zeros(3)
    c1n_hat = c1n / length
    dot_val = float(_np.dot(c1n_hat, target))
    cost    = 1.0 - dot_val
    # d/d(c1n) [1 − dot(c1n/|c1n|, t)] = −(t − dot_val·c1n_hat) / |c1n|
    g_c1n = -(target - dot_val * c1n_hat) / length
    # chain rule: d(c1n)/d(c1_pos) = −I
    return float(cost), -g_c1n, g_c1n


def _repulsion_cost_grad(
    w:         dict[str, _np.ndarray],
    repel_pos: list[_np.ndarray],
) -> "tuple[float, dict[str, _np.ndarray]]":
    """Soft-sphere repulsion cost and gradient.

    Returns (cost, g_dict) where g_dict maps atom name → gradient vector.
    """
    cost   = 0.0
    g_dict: dict[str, _np.ndarray] = {}
    for a_name in ("C1'", "C3'", "C4'"):
        if a_name not in w:
            continue
        pos = w[a_name]
        g   = _np.zeros(3)
        for rep in repel_pos:
            diff = pos - rep
            d    = float(_np.linalg.norm(diff))
            if 1e-12 < d < _R_REPULSION:
                overlap  = 1.0 - d / _R_REPULSION
                cost    += overlap ** 2
                # d/d(pos) (1−d/R)² = 2(1−d/R)(−1/R)(pos−rep)/d
                g += 2.0 * overlap * (-1.0 / _R_REPULSION) * (diff / d)
        g_dict[a_name] = g
    return cost, g_dict


def _rb_pair_repulsion_grad(
    w1: dict[str, _np.ndarray],
    w2: dict[str, _np.ndarray],
) -> "tuple[float, dict[str, _np.ndarray], dict[str, _np.ndarray]]":
    """Soft-sphere pair repulsion cost and gradient for two rigid bodies.

    Returns (cost, g1_dict, g2_dict).
    """
    cost = 0.0
    rep_names = ("C1'", "C3'", "C4'")
    g1: dict[str, _np.ndarray] = {a: _np.zeros(3) for a in rep_names if a in w1}
    g2: dict[str, _np.ndarray] = {b: _np.zeros(3) for b in rep_names if b in w2}
    for a in rep_names:
        if a not in w1:
            continue
        for b in rep_names:
            if b not in w2:
                continue
            diff = w1[a] - w2[b]
            d    = float(_np.linalg.norm(diff))
            if 1e-12 < d < _R_REPULSION:
                overlap  = 1.0 - d / _R_REPULSION
                cost    += overlap ** 2
                g_ab     = 2.0 * overlap * (-1.0 / _R_REPULSION) * (diff / d)
                # d/d(w1[a]) = same sign; d/d(w2[b]) = opposite sign
                g1[a] += g_ab
                g2[b] -= g_ab
    return cost, g1, g2


def _rb_grad_propagate(
    g_w:       dict[str, _np.ndarray],
    names:     "tuple[str, ...]",
    mat:       _np.ndarray,
    dR_dtheta: _np.ndarray,
) -> "tuple[_np.ndarray, float]":
    """Propagate world-position gradients through a rigid-body transform.

    Given accumulated gradients g_w[name] (∂f/∂w[name]) and the rigid-body
    local coordinates (mat rows), compute ∂f/∂delta and ∂f/∂theta.

    d(w[name])/d(delta) = I  →  ∂f/∂delta = Σ g_w[name]
    d(w[name])/d(theta) = dR/dθ @ local[name]  →  ∂f/∂theta = Σ g_w[name]·(dR/dθ @ local)
    """
    g_delta = _np.zeros(3)
    g_theta = 0.0
    name_to_idx = {n: i for i, n in enumerate(names)}
    for name, g in g_w.items():
        if g is None:
            continue
        g_delta += g
        idx = name_to_idx.get(name)
        if idx is not None:
            dw_dth  = dR_dtheta @ mat[idx]   # (3,)
            g_theta += float(_np.dot(g, dw_dth))
    return g_delta, g_theta


def _rb_extract(
    atoms:  list[Atom],
    s_dict: dict[str, int],
) -> "tuple[_np.ndarray, tuple[str, ...], _np.ndarray]":
    """
    Snapshot rigid-body atom positions in C2′-centred coordinates.

    Phosphate atoms (P, OP1, OP2, O5′) are excluded — they are free linkers.
    O3′ IS retained so ring-exit geometry is preserved under rigid-body motion.

    Returns (c2_world, names_tuple, local_mat) where local_mat is (N, 3) — a
    row-matrix of local coordinate vectors.  This form lets _rb_world do the
    full transform as a single (N, 3) @ (3, 3) matrix multiply instead of a
    Python loop over N atoms.
    """
    c2_w  = _atom_pos(atoms, s_dict["C2'"])
    names = tuple(name for name in s_dict if name not in _PHOSPHATE_ATOMS)
    mat   = _np.array([_atom_pos(atoms, s_dict[name]) - c2_w for name in names])
    return c2_w, names, mat


def _rb_world(
    c2_orig: _np.ndarray,
    names:   "tuple[str, ...]",
    mat:     _np.ndarray,
    delta:   _np.ndarray,
    R:       _np.ndarray,
) -> dict[str, _np.ndarray]:
    """World positions of rigid-body atoms after C2′ translation + spin rotation.

    Uses a single (N, 3) @ (3, 3) matrix multiply for all N atoms.
    """
    c2_new = c2_orig + delta
    world  = c2_new + mat @ R.T      # (N, 3); broadcasting c2_new over rows
    return dict(zip(names, world))


def _rb_apply(
    atoms:  list[Atom],
    s_dict: dict[str, int],
    rb_pos: dict[str, _np.ndarray],
) -> None:
    """Write optimised rigid-body world positions back into the atoms list."""
    for name, s in s_dict.items():
        if name not in _PHOSPHATE_ATOMS and name in rb_pos:
            _set_atom_pos(atoms, s, rb_pos[name])


def _apply_phosphate(
    atoms:  list[Atom],
    s_dict: dict[str, int],
    p_new:  _np.ndarray,
    o5_new: _np.ndarray,
) -> None:
    """
    Set P and O5′ to optimised positions; rigidly translate OP1/OP2 with P.
    Reads the current P position *before* overwriting it.
    """
    orig_p = _atom_pos(atoms, s_dict["P"]) if "P" in s_dict else None
    if "P"   in s_dict: _set_atom_pos(atoms, s_dict["P"],   p_new)
    if "O5'" in s_dict: _set_atom_pos(atoms, s_dict["O5'"], o5_new)
    if orig_p is not None:
        delta_p = p_new - orig_p
        for op in ("OP1", "OP2"):
            s = s_dict.get(op)
            if s is not None:
                _translate_atom(atoms, s, delta_p)


def _glycosidic_cost(
    w:     dict[str, _np.ndarray],
    n_name: str,
    target: _np.ndarray,
) -> float:
    """
    C1′→N alignment penalty: 1 − cos(angle to target_c1n).
    Returns 0.0 if the glycosidic N is absent from the rigid-body world dict.
    """
    if n_name not in w or "C1'" not in w:
        return 0.0
    c1n = w[n_name] - w["C1'"]
    length = float(_np.linalg.norm(c1n))
    if length < 1e-9:
        return 0.0
    return float(1.0 - _np.dot(c1n / length, target))


def _repulsion_cost(
    w:         dict[str, _np.ndarray],
    repel_pos: list[_np.ndarray],
) -> float:
    """
    Soft-sphere repulsion between C1′/C3′/C4′ of one rigid body and a list of
    fixed positions (opposite-strand junction atoms).
    Cost = Σ max(0, 1 − d / _R_REPULSION)².
    """
    cost = 0.0
    for a_name in ("C1'", "C3'", "C4'"):
        if a_name not in w:
            continue
        pos = w[a_name]
        for rep in repel_pos:
            d = float(_np.linalg.norm(pos - rep))
            if d < _R_REPULSION:
                cost += (1.0 - d / _R_REPULSION) ** 2
    return cost


def _rb_pair_repulsion(
    w1: dict[str, _np.ndarray],
    w2: dict[str, _np.ndarray],
) -> float:
    """
    Soft-sphere repulsion between C1′/C3′/C4′ atoms of two extra-base rigid bodies.
    Prevents neighbouring extra bases from clashing at the Holliday junction.
    """
    cost = 0.0
    rep_names = ("C1'", "C3'", "C4'")
    for a in rep_names:
        if a not in w1:
            continue
        for b in rep_names:
            if b not in w2:
                continue
            d = float(_np.linalg.norm(w1[a] - w2[b]))
            if d < _R_REPULSION:
                cost += (1.0 - d / _R_REPULSION) ** 2
    return cost


# ── Joint placement minimisers for 1–3 extra crossover bases ─────────────────
#
# Each function jointly optimises:
#   • The placement (C2′ translation + spin about target_c1n) of every extra
#     nucleotide rigid body  — preserving the C1′→N direction established by
#     the glycosidic alignment step.
#   • All free backbone linker atoms (O3′(src), and P/O5′ of each incoming
#     phosphate group) that stitch the chain together.
#
# This is strictly better than the sequential per-pair _minimize_backbone_bridge
# approach because it couples the nucleotide placement with both flanking bridges
# simultaneously, allowing the optimizer to slide each ring to the position that
# minimises total backbone strain rather than freezing it at the lerp point.


def _minimize_1_extra_base(
    atoms:      list[Atom],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb1_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 1 extra crossover base (19 DOF).

    Variables
    ─────────
      x[0:3]   delta_eb1  – C2′ translation of eb1 rigid body
      x[3]     theta_eb1  – spin of eb1 about target_c1n
      x[4:7]   O3′(src)
      x[7:10]  P(eb1)   x[10:13] O5′(eb1)
      x[13:16] P(dst)   x[16:19] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    if not all(k in eb1_s for k in ("C2'", "C3'", "C5'", "O3'")):
        return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)

    def _eb1(x: _np.ndarray, R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_eb1, eb1_names, eb1_mat, x[0:3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt = _spin_rotation_deriv(target_c1n, float(x[3]))
        w   = _eb1(x, R)

        c1, g_c3s, g_o3s, g_peb1, g_o5eb1, g_c5w = _backbone_bridge_cost_grad(
            c3_src, x[4:7], x[7:10], x[10:13], w["C5'"])
        c2, g_c3w, g_o3w, g_pdst, g_o5dst, _gc5d = _backbone_bridge_cost_grad(
            w["C3'"], w["O3'"], x[13:16], x[16:19], c5_dst)
        c3v, g_c1v, g_nv = _glycosidic_cost_grad(w["C1'"], w[eb1_n], target_c1n)
        c4, g_rep       = _repulsion_cost_grad(w, repel_pos)

        total = c1 + c2 + _W_GLYCOSIDIC * c3v + _W_REPULSION * c4

        # Accumulate gradients flowing back to the rigid-body world positions
        g_w: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        def _acc(name: str, g: _np.ndarray) -> None:
            if name in g_w:
                g_w[name] += g
        _acc("C5'", g_c5w)
        _acc("C3'", g_c3w)
        _acc("O3'", g_o3w)
        _acc("C1'", _W_GLYCOSIDIC * g_c1v)
        _acc(eb1_n,  _W_GLYCOSIDIC * g_nv)
        for aname, gv in g_rep.items():
            _acc(aname, _W_REPULSION * gv)

        g_delta, g_theta = _rb_grad_propagate(g_w, eb1_names, eb1_mat, dRt)

        grad = _np.empty_like(x)
        grad[0:3]   = g_delta
        grad[3]     = g_theta
        grad[4:7]   = g_o3s
        grad[7:10]  = g_peb1
        grad[10:13] = g_o5eb1
        grad[13:16] = g_pdst
        grad[16:19] = g_o5dst
        return total, grad

    def _apply1(x: _np.ndarray) -> None:
        R = _make_spin_rotation(target_c1n, float(x[3]))
        _rb_apply(atoms, eb1_s, _eb1(x, R))
        _set_atom_pos(atoms, src_s["O3'"], x[4:7])
        _apply_phosphate(atoms, eb1_s, x[7:10],  x[10:13])
        _apply_phosphate(atoms, dst_s, x[13:16], x[16:19])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply1(_XB_CACHE[cache_key])
        return

    # Better initial guess: place linker atoms proportionally along canonical
    # bond-length fractions of each bridge chord (reduces initial bond stretching
    # from ~6× canonical to ~2×, cutting scipy iterations by ~5×).
    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb1, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        o3_src_x0, p_eb1_x0, o5_eb1_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply1(x)


def _minimize_2_extra_base(
    atoms:      list[Atom],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb2_s:      dict[str, int],
    eb1_n:      str,
    eb2_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 2 extra crossover bases (29 DOF).

    Variables
    ─────────
      x[0:4]   rb eb1  (delta[3], theta[1])
      x[4:8]   rb eb2  (delta[3], theta[1])
      x[8:11]  O3′(src)
      x[11:14] P(eb1)  x[14:17] O5′(eb1)
      x[17:20] P(eb2)  x[20:23] O5′(eb2)
      x[23:26] P(dst)  x[26:29] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion (inter-strand
               and inter-extra-base)
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    for eb in (eb1_s, eb2_s):
        if not all(k in eb for k in ("C2'", "C3'", "C5'", "O3'")):
            return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)
    c2_eb2, eb2_names, eb2_mat = _rb_extract(atoms, eb2_s)

    def _eb(x: _np.ndarray, off: int, c2_0: _np.ndarray,
            names: tuple, mat: _np.ndarray,
            R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_0, names, mat, x[off:off+3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R1   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt1 = _spin_rotation_deriv(target_c1n, float(x[3]))
        R2   = _make_spin_rotation(target_c1n, float(x[7]))
        dRt2 = _spin_rotation_deriv(target_c1n, float(x[7]))
        w1 = _eb(x, 0, c2_eb1, eb1_names, eb1_mat, R1)
        w2 = _eb(x, 4, c2_eb2, eb2_names, eb2_mat, R2)

        c1, _, g_o3s, g_peb1, g_o5eb1, g_c5w1 = _backbone_bridge_cost_grad(
            c3_src, x[8:11], x[11:14], x[14:17], w1["C5'"])
        c2, g_c3w1, g_o3w1, g_peb2, g_o5eb2, g_c5w2 = _backbone_bridge_cost_grad(
            w1["C3'"], w1["O3'"], x[17:20], x[20:23], w2["C5'"])
        c3v, g_c3w2, g_o3w2, g_pdst, g_o5dst, _ = _backbone_bridge_cost_grad(
            w2["C3'"], w2["O3'"], x[23:26], x[26:29], c5_dst)
        c4a, g_c1a, g_na = _glycosidic_cost_grad(w1["C1'"], w1[eb1_n], target_c1n)
        c4b, g_c1b, g_nb = _glycosidic_cost_grad(w2["C1'"], w2[eb2_n], target_c1n)
        c5a, g_r1   = _repulsion_cost_grad(w1, repel_pos)
        c5b, g_r2   = _repulsion_cost_grad(w2, repel_pos)
        c6,  g_p1, g_p2 = _rb_pair_repulsion_grad(w1, w2)

        total = (c1 + c2 + c3v
                 + _W_GLYCOSIDIC * (c4a + c4b)
                 + _W_REPULSION  * (c5a + c5b + c6))

        gw1: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        gw2: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb2_names}

        def _acc1(n: str, g: _np.ndarray) -> None:
            if n in gw1: gw1[n] += g
        def _acc2(n: str, g: _np.ndarray) -> None:
            if n in gw2: gw2[n] += g

        _acc1("C5'", g_c5w1); _acc1("C3'", g_c3w1); _acc1("O3'", g_o3w1)
        _acc1("C1'", _W_GLYCOSIDIC * g_c1a); _acc1(eb1_n, _W_GLYCOSIDIC * g_na)
        for a, g in g_r1.items(): _acc1(a, _W_REPULSION * g)
        for a, g in g_p1.items(): _acc1(a, _W_REPULSION * g)

        _acc2("C5'", g_c5w2); _acc2("C3'", g_c3w2); _acc2("O3'", g_o3w2)
        _acc2("C1'", _W_GLYCOSIDIC * g_c1b); _acc2(eb2_n, _W_GLYCOSIDIC * g_nb)
        for a, g in g_r2.items(): _acc2(a, _W_REPULSION * g)
        for a, g in g_p2.items(): _acc2(a, _W_REPULSION * g)

        gd1, gt1 = _rb_grad_propagate(gw1, eb1_names, eb1_mat, dRt1)
        gd2, gt2 = _rb_grad_propagate(gw2, eb2_names, eb2_mat, dRt2)

        grad = _np.empty_like(x)
        grad[0:3] = gd1;   grad[3]     = gt1
        grad[4:7] = gd2;   grad[7]     = gt2
        grad[8:11]  = g_o3s
        grad[11:14] = g_peb1;  grad[14:17] = g_o5eb1
        grad[17:20] = g_peb2;  grad[20:23] = g_o5eb2
        grad[23:26] = g_pdst;  grad[26:29] = g_o5dst
        return total, grad

    def _apply2(x: _np.ndarray) -> None:
        R1 = _make_spin_rotation(target_c1n, float(x[3]))
        R2 = _make_spin_rotation(target_c1n, float(x[7]))
        _rb_apply(atoms, eb1_s, _eb(x, 0, c2_eb1, eb1_names, eb1_mat, R1))
        _rb_apply(atoms, eb2_s, _eb(x, 4, c2_eb2, eb2_names, eb2_mat, R2))
        _set_atom_pos(atoms, src_s["O3'"], x[8:11])
        _apply_phosphate(atoms, eb1_s, x[11:14], x[14:17])
        _apply_phosphate(atoms, eb2_s, x[17:20], x[20:23])
        _apply_phosphate(atoms, dst_s, x[23:26], x[26:29])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply2(_XB_CACHE[cache_key])
        return

    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    c5_eb2 = _atom_pos(atoms, eb2_s["C5'"])   # rigid body at delta=0
    o3_eb2 = _atom_pos(atoms, eb2_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_eb2_x0, o5_eb2_x0             = _bwd_bridge_x0(o3_eb1, c5_eb2)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb2, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        o3_src_x0,
        p_eb1_x0, o5_eb1_x0,
        p_eb2_x0, o5_eb2_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply2(x)


def _minimize_3_extra_base(
    atoms:      list[Atom],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb2_s:      dict[str, int],
    eb3_s:      dict[str, int],
    eb1_n:      str,
    eb2_n:      str,
    eb3_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 3 extra crossover bases (39 DOF).

    Variables
    ─────────
      x[0:4]   rb eb1  x[4:8]   rb eb2  x[8:12]  rb eb3
      x[12:15] O3′(src)
      x[15:18] P(eb1)  x[18:21] O5′(eb1)
      x[21:24] P(eb2)  x[24:27] O5′(eb2)
      x[27:30] P(eb3)  x[30:33] O5′(eb3)
      x[33:36] P(dst)  x[36:39] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion (inter-strand
               and all inter-extra-base pairs)
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    for eb in (eb1_s, eb2_s, eb3_s):
        if not all(k in eb for k in ("C2'", "C3'", "C5'", "O3'")):
            return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)
    c2_eb2, eb2_names, eb2_mat = _rb_extract(atoms, eb2_s)
    c2_eb3, eb3_names, eb3_mat = _rb_extract(atoms, eb3_s)

    def _eb(x: _np.ndarray, off: int, c2_0: _np.ndarray,
            names: tuple, mat: _np.ndarray,
            R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_0, names, mat, x[off:off+3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R1   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt1 = _spin_rotation_deriv(target_c1n, float(x[3]))
        R2   = _make_spin_rotation(target_c1n, float(x[7]))
        dRt2 = _spin_rotation_deriv(target_c1n, float(x[7]))
        R3   = _make_spin_rotation(target_c1n, float(x[11]))
        dRt3 = _spin_rotation_deriv(target_c1n, float(x[11]))
        w1 = _eb(x,  0, c2_eb1, eb1_names, eb1_mat, R1)
        w2 = _eb(x,  4, c2_eb2, eb2_names, eb2_mat, R2)
        w3 = _eb(x,  8, c2_eb3, eb3_names, eb3_mat, R3)

        c1, _, g_o3s, g_peb1, g_o5eb1, g_c5w1 = _backbone_bridge_cost_grad(
            c3_src,     x[12:15], x[15:18], x[18:21], w1["C5'"])
        c2, g_c3w1, g_o3w1, g_peb2, g_o5eb2, g_c5w2 = _backbone_bridge_cost_grad(
            w1["C3'"], w1["O3'"], x[21:24], x[24:27], w2["C5'"])
        c3v, g_c3w2, g_o3w2, g_peb3, g_o5eb3, g_c5w3 = _backbone_bridge_cost_grad(
            w2["C3'"], w2["O3'"], x[27:30], x[30:33], w3["C5'"])
        c4, g_c3w3, g_o3w3, g_pdst, g_o5dst, _ = _backbone_bridge_cost_grad(
            w3["C3'"], w3["O3'"], x[33:36], x[36:39], c5_dst)

        c5a, g_c1a, g_na = _glycosidic_cost_grad(w1["C1'"], w1[eb1_n], target_c1n)
        c5b, g_c1b, g_nb = _glycosidic_cost_grad(w2["C1'"], w2[eb2_n], target_c1n)
        c5c, g_c1c, g_nc = _glycosidic_cost_grad(w3["C1'"], w3[eb3_n], target_c1n)
        c6a, g_r1 = _repulsion_cost_grad(w1, repel_pos)
        c6b, g_r2 = _repulsion_cost_grad(w2, repel_pos)
        c6c, g_r3 = _repulsion_cost_grad(w3, repel_pos)
        c7ab, g_p1ab, g_p2ab = _rb_pair_repulsion_grad(w1, w2)
        c7ac, g_p1ac, g_p3ac = _rb_pair_repulsion_grad(w1, w3)
        c7bc, g_p2bc, g_p3bc = _rb_pair_repulsion_grad(w2, w3)

        total = (c1 + c2 + c3v + c4
                 + _W_GLYCOSIDIC * (c5a + c5b + c5c)
                 + _W_REPULSION  * (c6a + c6b + c6c + c7ab + c7ac + c7bc))

        gw1: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        gw2: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb2_names}
        gw3: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb3_names}

        def _a1(n: str, g: _np.ndarray) -> None:
            if n in gw1: gw1[n] += g
        def _a2(n: str, g: _np.ndarray) -> None:
            if n in gw2: gw2[n] += g
        def _a3(n: str, g: _np.ndarray) -> None:
            if n in gw3: gw3[n] += g

        _a1("C5'", g_c5w1); _a1("C3'", g_c3w1); _a1("O3'", g_o3w1)
        _a1("C1'", _W_GLYCOSIDIC * g_c1a); _a1(eb1_n, _W_GLYCOSIDIC * g_na)
        for a, g in g_r1.items():   _a1(a, _W_REPULSION * g)
        for a, g in g_p1ab.items(): _a1(a, _W_REPULSION * g)
        for a, g in g_p1ac.items(): _a1(a, _W_REPULSION * g)

        _a2("C5'", g_c5w2); _a2("C3'", g_c3w2); _a2("O3'", g_o3w2)
        _a2("C1'", _W_GLYCOSIDIC * g_c1b); _a2(eb2_n, _W_GLYCOSIDIC * g_nb)
        for a, g in g_r2.items():   _a2(a, _W_REPULSION * g)
        for a, g in g_p2ab.items(): _a2(a, _W_REPULSION * g)
        for a, g in g_p2bc.items(): _a2(a, _W_REPULSION * g)

        _a3("C5'", g_c5w3); _a3("C3'", g_c3w3); _a3("O3'", g_o3w3)
        _a3("C1'", _W_GLYCOSIDIC * g_c1c); _a3(eb3_n, _W_GLYCOSIDIC * g_nc)
        for a, g in g_r3.items():   _a3(a, _W_REPULSION * g)
        for a, g in g_p3ac.items(): _a3(a, _W_REPULSION * g)
        for a, g in g_p3bc.items(): _a3(a, _W_REPULSION * g)

        gd1, gt1 = _rb_grad_propagate(gw1, eb1_names, eb1_mat, dRt1)
        gd2, gt2 = _rb_grad_propagate(gw2, eb2_names, eb2_mat, dRt2)
        gd3, gt3 = _rb_grad_propagate(gw3, eb3_names, eb3_mat, dRt3)

        grad = _np.empty_like(x)
        grad[0:3]  = gd1;  grad[3]  = gt1
        grad[4:7]  = gd2;  grad[7]  = gt2
        grad[8:11] = gd3;  grad[11] = gt3
        grad[12:15] = g_o3s
        grad[15:18] = g_peb1;  grad[18:21] = g_o5eb1
        grad[21:24] = g_peb2;  grad[24:27] = g_o5eb2
        grad[27:30] = g_peb3;  grad[30:33] = g_o5eb3
        grad[33:36] = g_pdst;  grad[36:39] = g_o5dst
        return total, grad

    def _apply3(x: _np.ndarray) -> None:
        R1 = _make_spin_rotation(target_c1n, float(x[3]))
        R2 = _make_spin_rotation(target_c1n, float(x[7]))
        R3 = _make_spin_rotation(target_c1n, float(x[11]))
        _rb_apply(atoms, eb1_s, _eb(x,  0, c2_eb1, eb1_names, eb1_mat, R1))
        _rb_apply(atoms, eb2_s, _eb(x,  4, c2_eb2, eb2_names, eb2_mat, R2))
        _rb_apply(atoms, eb3_s, _eb(x,  8, c2_eb3, eb3_names, eb3_mat, R3))
        _set_atom_pos(atoms, src_s["O3'"], x[12:15])
        _apply_phosphate(atoms, eb1_s, x[15:18], x[18:21])
        _apply_phosphate(atoms, eb2_s, x[21:24], x[24:27])
        _apply_phosphate(atoms, eb3_s, x[27:30], x[30:33])
        _apply_phosphate(atoms, dst_s, x[33:36], x[36:39])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply3(_XB_CACHE[cache_key])
        return

    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    c5_eb2 = _atom_pos(atoms, eb2_s["C5'"])   # rigid body at delta=0
    o3_eb2 = _atom_pos(atoms, eb2_s["O3'"])   # rigid body at delta=0
    c5_eb3 = _atom_pos(atoms, eb3_s["C5'"])   # rigid body at delta=0
    o3_eb3 = _atom_pos(atoms, eb3_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_eb2_x0, o5_eb2_x0             = _bwd_bridge_x0(o3_eb1, c5_eb2)
    p_eb3_x0, o5_eb3_x0             = _bwd_bridge_x0(o3_eb2, c5_eb3)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb3, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        o3_src_x0,
        p_eb1_x0, o5_eb1_x0,
        p_eb2_x0, o5_eb2_x0,
        p_eb3_x0, o5_eb3_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply3(x)


# ── Extra-base arc geometry helpers ──────────────────────────────────────────

_BOW_FRAC_3D: float = 0.3  # matches crossover_connections.js BOW_FRAC_3D


def _bezier_pt(
    posA: _np.ndarray, ctrl: _np.ndarray, posB: _np.ndarray, t: float,
) -> _np.ndarray:
    """Quadratic Bezier position: (1-t)²A + 2(1-t)tC + t²B."""
    u = 1.0 - t
    return u * u * posA + 2.0 * u * t * ctrl + t * t * posB


def _bezier_tan(
    posA: _np.ndarray, ctrl: _np.ndarray, posB: _np.ndarray, t: float,
) -> _np.ndarray:
    """Normalised quadratic Bezier tangent: 2(1-t)(C-A) + 2t(B-C)."""
    u = 1.0 - t
    tan = 2.0 * u * (ctrl - posA) + 2.0 * t * (posB - ctrl)
    n = float(_np.linalg.norm(tan))
    return tan / n if n > 1e-9 else tan


def _arc_bow_dir(
    posA: _np.ndarray, posB: _np.ndarray,
    ax_a: _np.ndarray, ax_b: _np.ndarray,
) -> _np.ndarray:
    """
    Bow direction for a crossover arc: normalise(cross(chord, avg_axis)).

    Matches arcControlPoint() bow direction in crossover_connections.js.
    Points away from the Holliday junction — the direction the arc bows and
    the direction the base of each extra nucleotide faces outward.
    """
    chord = posB - posA
    dist  = float(_np.linalg.norm(chord))
    if dist < 1e-9:
        return _np.array([0.0, 0.0, 1.0])
    chord_hat = chord / dist
    avg_ax    = ax_a + ax_b
    avg_ax_n  = float(_np.linalg.norm(avg_ax))
    avg_ax    = avg_ax / avg_ax_n if avg_ax_n > 1e-9 else _np.array([0.0, 0.0, 1.0])
    bow       = _np.cross(chord_hat, avg_ax)
    bow_n     = float(_np.linalg.norm(bow))
    if bow_n < 1e-6:
        # Degenerate: chord parallel to axis — fall back to avg_ax
        return avg_ax
    return bow / bow_n


def _arc_ctrl_pt(
    posA: _np.ndarray, posB: _np.ndarray, bow_dir: _np.ndarray,
) -> _np.ndarray:
    """Quadratic Bezier control point bowing outward by BOW_FRAC_3D of chord length."""
    dist = float(_np.linalg.norm(posB - posA))
    mid  = (posA + posB) * 0.5
    return mid + bow_dir * (dist * _BOW_FRAC_3D)


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
            t_i        = i / (n + 1)
            origin_pos = _lerp(line_p0, line_p1, t_i)
            origin, R  = _extra_base_frame(origin_pos, line_dir, bow_dir)

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
                    bp_index     = ha.index,
                    direction    = ha.strand.value,
                    aux_helix_id = dst_key[0],
                    aux_t        = _aux_t,
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
                    bp_index     = ha.index,
                    direction    = ha.strand.value,
                    aux_helix_id = dst_key[0],
                    aux_t        = _aux_t,
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

        if n == 1 and src_s is not None and dst_s is not None:
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
            }
            for a in model.atoms
        ],
        "bonds": [[i, j] for i, j in model.bonds],
        "element_meta": {
            el: {"vdw_radius": r, "cpk_color": CPK_COLOR[el]}
            for el, r in VDW_RADIUS.items()
        },
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
