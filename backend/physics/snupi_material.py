"""SNUPI per-motif constitutive matrices for the FEM (Phase 2 foundation).

Loads the transcribed SNUPI SI parameters (``backend/data/parameters/snupi_params.json``,
see memory/project_snupi_mimic.md) and assembles, per motif, the 6x6 **sectional
constitutive matrix** ``D`` that relates the six beam section strains to the six
section forces/moments:

    [N, Vy, Vz, T, My, Mz]^T = D @ [eps, gamma_y, gamma_z, kappa_x, kappa_y, kappa_z]^T

with SNUPI's own beam DOF order ``q = [dx, dy, dz, theta_x, theta_y, theta_z]``
where **dx is the axial (Rise) direction**, theta_x is torsion about it, dy/dz are
shear, theta_y/theta_z are bending (Notes S3-S4).  ``D`` carries the six diagonal
rigidities (EA, GAy, GAz, GJ, EIy, EIz) and the 15 symmetric coupling terms.

This module is deliberately **formulation-independent**: it emits ``D`` in SNUPI's
frame only.  The mapping into a specific NADOC element (axial=local-z) and the
choice of element (Euler-Bernoulli diagonal vs full co-rotational/Timoshenko) live
in fem_solver.py, where the convention is pinned by a mechanical unit test rather
than reasoned about here.

Units (as stored, a valid mixed-unit sectional stiffness):
  * EA, GAy, GAz .............. pN            (strain -> force)
  * GJ, EIy, EIz ............. pN*nm^2        (curvature -> moment)
  * g(trans,trans) ........... pN
  * g(rot,rot) ............... pN*nm^2
  * g(trans,rot) ............. pN*nm
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import numpy as np

from backend.core.constants import SSDNA_CONTOUR_PER_NT_NM

_PARAMS_PATH = Path(__file__).resolve().parents[1] / "data" / "parameters" / "snupi_params.json"

# SNUPI beam DOF order (dx = axial).
DOF_ORDER: List[str] = ["dx", "dy", "dz", "theta_x", "theta_y", "theta_z"]
_DOF_IDX = {d: i for i, d in enumerate(DOF_ORDER)}

# Diagonal rigidity -> DOF.
_DIAG_MAP = {"dx": "EA", "dy": "GAy", "dz": "GAz",
             "theta_x": "GJ", "theta_y": "EIy", "theta_z": "EIz"}

# 15 coupling keys -> the (dof_a, dof_b) pair they populate off the diagonal.
_COUPLING_MAP = {
    "g_Tx_Ty": ("theta_x", "theta_y"), "g_Tx_Tz": ("theta_x", "theta_z"),
    "g_Ty_Tz": ("theta_y", "theta_z"),
    "g_Dx_Dy": ("dx", "dy"), "g_Dx_Dz": ("dx", "dz"), "g_Dy_Dz": ("dy", "dz"),
    "g_Dx_Tx": ("dx", "theta_x"), "g_Dx_Ty": ("dx", "theta_y"), "g_Dx_Tz": ("dx", "theta_z"),
    "g_Dy_Tx": ("dy", "theta_x"), "g_Dy_Ty": ("dy", "theta_y"), "g_Dy_Tz": ("dy", "theta_z"),
    "g_Dz_Tx": ("dz", "theta_x"), "g_Dz_Ty": ("dz", "theta_y"), "g_Dz_Tz": ("dz", "theta_z"),
}

MOTIF_FAMILIES = ("regular_bp", "nicked_bp", "co_nick", "double_co", "single_co")


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(_PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _assemble_D(rigidity: Dict[str, float], coupling: Dict[str, float]) -> np.ndarray:
    """Build the symmetric 6x6 sectional constitutive matrix from one motif's
    rigidity + coupling dicts, in DOF_ORDER."""
    D = np.zeros((6, 6), dtype=float)
    for dof, rk in _DIAG_MAP.items():
        D[_DOF_IDX[dof], _DOF_IDX[dof]] = rigidity[rk]
    for gk, (a, b) in _COUPLING_MAP.items():
        i, j = _DOF_IDX[a], _DOF_IDX[b]
        D[i, j] = coupling[gk]
        D[j, i] = coupling[gk]
    return D


def motif_D(family: str, motif: str) -> np.ndarray:
    """6x6 sectional constitutive matrix for a specific motif (e.g. 'regular_bp', 'AA/TT')."""
    m = _load()["motifs"][family][motif]
    return _assemble_D(m["rigidity"], m["coupling"])


_COMPLEMENT = {"A": "T", "T": "A", "G": "C", "C": "G"}


def _revcomp(step: str) -> str:
    """Reverse-complement of a dinucleotide step (5'→3')."""
    return "".join(_COMPLEMENT.get(b, "N") for b in reversed(step))


@lru_cache(maxsize=len(MOTIF_FAMILIES))
def _step_to_key(family: str) -> Dict[str, str]:
    """Map every dinucleotide step 'XY' (read 5'→3' on ONE strand) to the family's
    canonical motif key.

    The SNUPI tables list each bp step ONCE under a canonical representative (e.g.
    'AA/TT' — the left token 'AA' is the step read 5'→3' on the forward strand, the
    right token 'TT' is the SAME physical step read 5'→3' on the reverse strand =
    ``revcomp('AA')``).  So a physical step maps to the same key whether it is read
    from either strand, and this lookup accepts BOTH tokens → the one key.  For the
    ``regular_bp`` family the 16 dinucleotides collapse onto its 10 keys; the crossover /
    nicked families use their own token grammar (separators '||','|','-', or the nick
    marker 'n') and are NOT sequence-addressable — for them this returns an EMPTY map, so
    every step falls back to the family mean (see :func:`family_mean_D`).  Requiring EVERY
    token to be a pure 2-letter ATGC step is what rejects them (a nicked key like 'AnA/TT'
    has a clean-looking sibling token 'AA', which must not be resolved to a specific nick).
    """
    keys = list(_load()["motifs"][family])

    def _clean(tok: str) -> bool:
        return len(tok) == 2 and set(tok) <= set("ATGC")

    if not all("/" in k and all(_clean(t) for t in k.split("/", 1)) for k in keys):
        return {}
    out: Dict[str, str] = {}
    for key in keys:
        left = key.split("/", 1)[0]
        out.setdefault(left, key)
        out.setdefault(_revcomp(left), key)
    return out


def motif_key_for_step(family: str, step: str) -> str | None:
    """Canonical motif key for a dinucleotide ``step`` (e.g. 'AG') in ``family``, or None
    if the step is unresolvable (contains an N / not a sequence-addressable family).

    ``step`` is the two bases of the bp step read 5'→3' on the forward strand
    (increasing bp index, per the NADOC FORWARD convention).  Direction-agnostic for the
    KEY (a step and its reverse-complement share the key), but the base ORDER within the
    step matters (AG ≠ GA), so callers must pass the true 5'→3' order.
    """
    return _step_to_key(family).get(step.upper())


@lru_cache(maxsize=len(MOTIF_FAMILIES))
def family_mean_D(family: str) -> np.ndarray:
    """Sequence-averaged 6x6 sectional constitutive matrix for a motif family.

    Mean over the family's motifs of the per-motif D (== the SI Mean column, since
    D is linear in the tabulated values).  This is the Phase-2 'MEAN first' material:
    it captures the motif-level anisotropy (regular vs nicked vs CO steps) without
    per-element sequence lookup.

    NOTE (single-CO indefiniteness): ~7/16 per-motif ``single_co`` D matrices are
    numerically INDEFINITE (non-PD) — a real limitation of SNUPI's single-crossover
    fits (one backbone connection => near-singular covariance => unstable inversion,
    e.g. AT|AT has g(dx,dy)=636.5 pN > sqrt(EA*GAy)); it is NOT a transcription error
    (verified vs raw SI).  Averaging over the family regularizes this: every family
    MEAN (including single_co) is positive-definite.  Sequence-specific single-CO use
    will need PD projection first; the MEAN path does not.
    """
    entries = _load()["motifs"][family]
    Ds = [_assemble_D(m["rigidity"], m["coupling"]) for m in entries.values()]
    return np.mean(Ds, axis=0)


def family_mean_rigidity(family: str) -> Dict[str, float]:
    """The six sequence-averaged diagonal rigidities for a family (EA, GAy, ... EIz)."""
    D = family_mean_D(family)
    return {rk: float(D[_DOF_IDX[dof], _DOF_IDX[dof]]) for dof, rk in _DIAG_MAP.items()}


def temperature_K() -> float:
    return float(_load()["temperature_K"])


# ── ssDNA element (SNUPI's third connection type — gap G9) ─────────────────────
#
# SNUPI collapses every contiguous run of unpaired nucleotides into ONE 2-node beam
# between the flanking base-pair nodes ("end-to-end connection of single-stranded DNA",
# Nat Commun 2023 14:7079; the element itself is ACS Nano 2021 15(12):20430).  It is the
# only ISOTROPIC element in the model: EIy == EIz, zero shear rigidity (GAy = GAz = 0)
# and no couplings — i.e. a plain Euler-Bernoulli beam with scalar (EA, EI, GJ), unlike
# the anisotropic Timoshenko duplex/crossover steps above.
#
# Its properties are strongly LENGTH-dependent, and that is the physics: a 1-2 nt gap is a
# stiff, near-taut element, while a 20-mer relaxes to bulk-polymer floppiness.  The rest
# length is the worm-like-chain RMS END-TO-END distance, NOT the contour (24 nt -> 4.1 nm,
# not 16 nm).
#
# The published options file (~/SNUPI/Default.snp lines 88-153) exposes the INPUTS to those
# laws (SS_LCT1_*, SS_LPB_*, SS_EA_*, SS_GJ_*) but SNUPI ships as a compiled binary and the
# closed forms that combine them are not published.  Rather than guess them, the table below
# was MEASURED from the real binary: designs carrying interior scaffold gaps of every length
# n = 1..24 were run through SNUPI and the ssDNA elements' (L, GJ, EI) read straight out of
# its `PROP` array (`<name>_STT_RES.mat`).  So for n <= 24 this IS SNUPI, to 4 decimals.
# See memory/project_snupi_ssdna.md (SS-1) and scripts/snupi_ssdna_probe.py.
#
# n -> (L_rest nm, GJ pN*nm^2, EI pN*nm^2).  n = 21, 23 were not reachable in the probe
# designs (no staple nick had the capacity) and are filled from the asymptotic laws below,
# which reproduce the measured n >= 14 points to 0.11 % (L), 0.10 % (GJ) and 1.5 % (EI).
_SS_TABLE: Dict[int, tuple] = {
    1:  (0.6881, 15.0000, 10.6225),
    2:  (1.0931, 13.0453, 19.7840),
    3:  (1.4686, 11.1914, 27.6540),
    4:  (1.7897,  9.5377, 33.7518),
    5:  (2.0526,  8.1202, 38.0118),
    6:  (2.2667,  6.9368, 40.6013),
    7:  (2.4454,  5.9662, 41.7915),
    8:  (2.6000,  5.1794, 41.8763),
    9:  (2.7381,  4.5463, 41.1300),
    10: (2.8647,  4.0393, 39.7882),
    11: (2.9826,  3.6341, 38.0428),
    12: (3.0938,  3.3107, 36.0443),
    13: (3.1994,  3.0526, 33.9078),
    14: (3.3004,  2.8464, 31.7187),
    15: (3.3974,  2.6815, 29.5388),
    16: (3.4908,  2.5494, 27.4119),
    17: (3.5811,  2.4435, 25.3678),
    18: (3.6686,  2.3584, 23.4259),
    19: (3.7535,  2.2900, 21.5975),
    20: (3.8361,  2.2349, 19.8885),
    21: (3.9159,  2.1892, 18.3445),   # interpolated (see above)
    22: (3.9952,  2.1544, 16.8322),
    23: (4.0739,  2.1234, 15.6505),   # interpolated (see above)
    24: (4.1470,  2.1018, 14.2396),
}
SS_TABLE_MAX_NT = 24

# Asymptotic laws for n > SS_TABLE_MAX_NT, least-squares fits to the measured n = 14..24
# points.  L follows the ideal-chain sqrt(n) growth; GJ decays to SNUPI's long-ssDNA floor
# SS_GJ_L = 2 pN*nm^2; EI decays toward zero (a long collapsed ssDNA beam has almost no
# bending stiffness left).  Real bridging runs are short — VoltronCore's longest is 16 nt —
# so this branch is a safety net, not the hot path.
_SS_L_A, _SS_L_B = 0.631009, 3.301714      # L  = sqrt(A * (n + B))
_SS_GJ_L, _SS_GJ_C, _SS_GJ_K = 2.0, 16.837197, 0.213745   # GJ = GJ_L + C*exp(-K n)
_SS_EI_C, _SS_EI_K = 97.222944, 0.079413                  # EI = C*exp(-K n)

# Stretch rigidity, relaxed (`SS_EA_L` in Default.snp).  SNUPI additionally has a nonlinear
# extension-dependent EA that stiffens toward SS_EA_H = 710 pN as the run pulls taut; at the
# rest configuration every element sits at the relaxed value, which is what the FEM assembles
# (confirmed: every measured element with n >= 4 reported EA = 15.0000 exactly).
SS_EA_RELAXED = 15.0


def ssdna_element(n_nt: int) -> Dict[str, float]:
    """SNUPI's ssDNA beam for a run of ``n_nt`` unpaired nucleotides.

    Returns ``{"l_rest", "ea", "ei", "gj"}`` — the rest length (nm, the WLC RMS end-to-end
    distance) and the three scalar rigidities of an ISOTROPIC Euler-Bernoulli beam
    (pN and pN*nm^2).  Feed straight into ``fem_solver._beam_stiffness_local``.

    This is the COLLAPSED, end-to-end element: one beam standing in for the whole run, with
    the run's conformational entropy already folded into its (soft) rigidities.  It is the
    right model for a BRIDGE (two anchors) and the wrong one for a per-nucleotide link in an
    explicit chain — see :func:`ssdna_link_element`.
    """
    n = int(n_nt)
    if n < 1:
        raise ValueError(f"ssdna_element needs n_nt >= 1, got {n_nt}")
    if n in _SS_TABLE:
        l_rest, gj, ei = _SS_TABLE[n]
    else:
        l_rest = float(np.sqrt(_SS_L_A * (n + _SS_L_B)))
        gj = _SS_GJ_L + _SS_GJ_C * float(np.exp(-_SS_GJ_K * n))
        ei = _SS_EI_C * float(np.exp(-_SS_EI_K * n))
    return {"l_rest": float(l_rest), "ea": SS_EA_RELAXED, "ei": float(ei), "gj": float(gj)}


# ── Per-nucleotide ssDNA link (SS-2: the EXPLICIT free-tail chain) ──────────────
#
# A free tail (overhang / toehold / dangling scaffold end) has no distal base pair, so SNUPI's
# collapsed end-to-end element above cannot represent it AT ALL — there is nothing to connect
# to.  NADOC extends the model with an EXPLICIT chain: one bead per nucleotide, linked by these
# beams, integrated in the Langevin engine only.  This is a documented NADOC extension beyond
# published SNUPI (memory/project_snupi_ssdna.md, decision 3).
#
# The link's constants are NOT `ssdna_element(1)`, and reusing that would DOUBLE-COUNT the
# entropy.  `ssdna_element(n)` is an effective element whose softness *is* the run's
# conformational freedom, integrated out.  In an explicit chain that freedom is represented
# explicitly by the beads, so each link must carry the INTRINSIC (enthalpic) polymer constants:
#
#   * contour per nt   b   = SS_LCT1_L = 0.68 nm       (long/relaxed ssDNA — the tail regime)
#   * bending          EI  = k_B T · L_p, L_p = SS_LPB_L = 0.67 nm  → 2.775 pN·nm^2.  This is the
#     definition of persistence length, and it is confirmed by SNUPI itself: the one element in
#     its own output whose run is short enough to be near-taut (TALOS poly-T) reports EI = 2.775.
#   * stretch          EA  = SS_EA_H = 710 pN          (TAUT/backbone modulus — the covalent
#     backbone barely stretches.  The RELAXED SS_EA_L = 15 pN is the *entropic* spring constant
#     of a whole coiled run; using it per link would let a single bond stretch by ±64% of its own
#     length at 300 K, which is nonsense for a covalent bond.)
#   * torsion          GJ  = SS_GJ_H = 15 pN·nm^2      (short-ssDNA torsional rigidity)
#
# Sourced from ~/SNUPI/Default.snp lines 88-153.  The resulting chain is validated against the
# WLC end-to-end oracle, NOT against SNUPI (which has no such element to compare to) — see
# `tests/test_snupi_ssdna.py::test_free_tail_reproduces_the_wlc_end_to_end_distribution`.
SS_CONTOUR_PER_NT = SSDNA_CONTOUR_PER_NT_NM   # nm — SS_LCT1_L (shared with the oxDNA tail seed)
SS_PERSISTENCE_NM = 0.67     # nm  — SS_LPB_L
SS_EA_TAUT = 710.0           # pN  — SS_EA_H
SS_GJ_SHORT = 15.0           # pN·nm^2 — SS_GJ_H

# k_B T at SNUPI's simulation temperature (300 K), pN·nm.  Local to the EI = k_BT·L_p identity;
# snupi_dynamics.KBT_300 is the same number and fem_solver.KBT (4.11) is the 298 K NMA value.
_KBT_300 = 4.142

# Discretisation correction on the bending rigidity — MEASURED, not assumed.
#
# `EI = k_BT·L_p` is a CONTINUUM identity: it assumes the discretisation is much finer than the
# persistence length.  An ssDNA tail is the opposite regime — one bead per nucleotide gives a bond
# b = 0.68 nm while ssDNA's L_p = 0.67 nm, so b/L_p ≈ 1.01 and the chain is discretised AT its own
# persistence length.  The discrete chain is measurably stiffer than the identity implies: with the
# uncorrected EI = 2.775 its emergent persistence length is 0.89 nm, not 0.67.
#
# So the factor is calibrated against the polymer statistics themselves — `scripts/
# snupi_tail_calibrate.py` sweeps the rigidity, samples each chain to equilibrium, and inverts the
# WLC end-to-end relation for L_p.  A 5-point sweep is linear in the factor (residual rms 0.011 nm)
# and crosses L_p = 0.67 nm at 0.574, i.e. EI = 1.593 pN·nm², 1.74x softer than the identity.
#
# ⚠️ Do NOT "verify" this with a quick MD run.  A chain's end-to-end distance is a slow,
# long-wavelength mode: molecular dynamics (and local-move Monte Carlo) converge the local bond
# angles orders of magnitude sooner and then report a confidently wrong, far-too-extended answer,
# with the tangent correlation plateauing instead of decaying.  Both happened during SS-2 and both
# samplers agreed with each other while being wrong.  Use the pivot sampler
# (`snupi_tails.pivot_sample_chain`); see memory/project_snupi_ssdna.md, SS-2.
SS_EI_DISCRETE_FACTOR = 0.574


def ssdna_link_element() -> Dict[str, float]:
    """One per-nucleotide ssDNA link of an EXPLICIT free-tail chain (SS-2, a NADOC extension).

    Returns ``{"l_rest", "ea", "ei", "gj"}`` for a single Euler-Bernoulli beam between two
    adjacent nucleotide beads.  Length-independent by construction (the chain's length is carried
    by the number of beads, not by the element).  See the block comment above for why these are
    the intrinsic constants rather than ``ssdna_element(1)``.
    """
    return {
        "l_rest": SS_CONTOUR_PER_NT,
        "ea": SS_EA_TAUT,
        "ei": _KBT_300 * SS_PERSISTENCE_NM * SS_EI_DISCRETE_FACTOR,
        "gj": SS_GJ_SHORT,
    }
