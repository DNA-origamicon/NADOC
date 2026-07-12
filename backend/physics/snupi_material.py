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
