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

    All frame constants — including the −32° helical phase offset
    (_ATOMISTIC_PHASE_OFFSET_RAD) that aligns the all-atom model with the NADOC
    CG representation — are baked in at the module level.

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
