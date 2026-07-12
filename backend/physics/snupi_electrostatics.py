"""
SNUPI inter-helix electrostatics — Debye–Hückel repulsion elements (SI Notes S6/S7).

The genuinely-new SNUPI solver piece over CanDo (the mimic's "delta #3"): the assembled
beam/crossover network has NO interaction *between* helices except through crossovers, so
SNUPI adds an explicit electrostatic repulsion between base-pair nodes of DIFFERENT helices.
This sets the equilibrium inter-helical spacing and contributes to bend/twist/RMSF.

Model (SI S6):
    Π_ES(r) = q² · l_B · kBT / r · exp(−r / λ_D)          [pN·nm]   (Debye–Hückel, per BP-pair)
where q is the effective charge (e), l_B the Bjerrum length (nm), λ_D the Debye screening
length (nm).  Modeled as a NONLINEAR axial spring (truss) element — axial deformation only,
no rotational DOF (S6.2).  A repulsive pair spring is only generated between nodes closer
than a cutoff r_cut (SI S7: r_cut = 2.5 nm) and only across helices.

Characteristic values (SI S7, the mimic default = 20 mM MgCl₂, T = 300 K):
    q = 0.7 e   (1.5 e at 100 mM MgCl₂);   r_cut = 2.5 nm.

This module is PURE (numpy + optional scipy KDTree) — no Design/topology access, no I/O.
The per-pair force + consistent tangent are finite-difference-verified in the test.
Physical-layer only (Three-Layer Law): affects the FEM shape/RMSF display, never topology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

# ── Physical constants (SI base) ───────────────────────────────────────────────
_KB = 1.380649e-23        # J/K
_E = 1.602176634e-19      # C
_EPS0 = 8.8541878128e-12  # F/m
_NA = 6.02214076e23       # 1/mol
_EPS_WATER = 78.0         # relative permittivity of water

KBT_PN_NM_300 = _KB * 300.0 / 1e-21   # kBT at 300 K in pN·nm ≈ 4.142
R_CUT_NM = 2.5                         # SI S7 electrostatic cutoff
Q_EFF_20MM = 0.7                       # SI S7 effective charge at 20 mM MgCl₂ (1.5 at 100 mM)


def bjerrum_length_nm(T_K: float = 300.0, eps_r: float = _EPS_WATER) -> float:
    """l_B = e²/(4πε₀ε_r kBT)  in nm (≈ 0.71 nm for water at 300 K)."""
    l_b_m = _E * _E / (4.0 * math.pi * _EPS0 * eps_r * _KB * T_K)
    return l_b_m * 1e9


def debye_length_nm(ionic_strength_M: float, T_K: float = 300.0,
                    eps_r: float = _EPS_WATER) -> float:
    """λ_D = sqrt(ε₀ε_r kBT / (2 N_A e² I)) in nm (SI eq 6.2).  ``ionic_strength_M`` in mol/L."""
    I = max(ionic_strength_M, 1e-9) * 1000.0   # mol/L → mol/m³
    lam_m = math.sqrt(_EPS0 * eps_r * _KB * T_K / (2.0 * _NA * _E * _E * I))
    return lam_m * 1e9


def ionic_strength_mgcl2_M(mgcl2_M: float) -> float:
    """Ionic strength of a MgCl₂ solution: I = ½Σcᵢzᵢ² = ½(c·2² + 2c·1²) = 3c (SI eq 6.3)."""
    return 3.0 * mgcl2_M


@dataclass(frozen=True)
class ESParams:
    """Resolved Debye–Hückel parameters in the solver's pN·nm units."""
    prefactor: float   # A = q² · l_B · kBT   (pN·nm², so Π = A/r·exp(−r/λ))
    lambda_d: float    # Debye length (nm)
    r_cut: float       # cutoff (nm)

    @classmethod
    def for_conditions(cls, *, mgcl2_M: float = 0.02, q_eff: float = Q_EFF_20MM,
                       T_K: float = 300.0, r_cut: float = R_CUT_NM) -> "ESParams":
        l_b = bjerrum_length_nm(T_K)
        kbt = _KB * T_K / 1e-21
        lam = debye_length_nm(ionic_strength_mgcl2_M(mgcl2_M), T_K)
        return cls(prefactor=q_eff * q_eff * l_b * kbt, lambda_d=lam, r_cut=r_cut)


# ── Per-pair energy / force / stiffness ────────────────────────────────────────

def pair_energy(r: float, prm: ESParams) -> float:
    """Debye–Hückel pair energy Π(r) (pN·nm)."""
    return prm.prefactor / r * math.exp(-r / prm.lambda_d)


def _dPi_dr(r: float, prm: ESParams) -> float:
    """dΠ/dr (< 0 — repulsive potential decreases with distance)."""
    e = math.exp(-r / prm.lambda_d)
    return -prm.prefactor * e * (1.0 / (r * r) + 1.0 / (r * prm.lambda_d))


def _d2Pi_dr2(r: float, prm: ESParams) -> float:
    """d²Π/dr² (> 0 — convex)."""
    lam = prm.lambda_d
    e = math.exp(-r / lam)
    # Π = A r⁻¹ e^{−r/λ}; Π'' = A e^{−r/λ} (2/r³ + 2/(r²λ) + 1/(r λ²))
    return prm.prefactor * e * (2.0 / r**3 + 2.0 / (r * r * lam) + 1.0 / (r * lam * lam))


def pair_force_stiffness(rvec: np.ndarray, prm: ESParams, *, axial_only: bool = False
                         ) -> Tuple[np.ndarray, np.ndarray]:
    """Repulsive force on node j + the 3×3 consistent stiffness block for a pair (i, j),
    where ``rvec = x_j − x_i``.

    Returns ``(f_j, K)``:
      * ``f_j`` — force on node j (pN), pushing j away from i (repulsive); force on i is −f_j.
      * ``K`` = ∂²Π/∂x_j∂x_j = Π''(r)·(n⊗n) + (Π'(r)/r)·(I − n⊗n) — the energy Hessian block
        (the truss tangent).  ``K_jj = K``, ``K_ii = K``, ``K_ij = K_ji = −K`` for the pair.

    The perpendicular term (Π'/r < 0) makes an isolated repulsive spring laterally soft; the
    surrounding beam/crossover network stabilises it in the SHAPE solve (verified: assembled
    system keeps 6 rigid modes).  For the free-free NMA (RMSF) pass, that indefinite term can
    introduce spurious soft modes, so ``axial_only=True`` keeps only the PD axial term
    Π''(r)·(n⊗n) — the dominant stiffening; the FORCE is unchanged either way.
    """
    r = float(np.linalg.norm(rvec))
    if r < 1e-9:
        return np.zeros(3), np.zeros((3, 3))
    n = rvec / r
    dpi = _dPi_dr(r, prm)
    d2pi = _d2Pi_dr2(r, prm)
    f_j = -dpi * n                       # −dΠ/dr > 0 along +n → repulsion pushes j outward
    nn = np.outer(n, n)
    K = d2pi * nn
    if not axial_only:
        K = K + (dpi / r) * (np.eye(3) - nn)
    return f_j, K


# ── Pair generation (inter-helix, within cutoff) ───────────────────────────────

def inter_helix_pairs(helix_ids: Sequence, positions: np.ndarray, r_cut: float
                      ) -> List[Tuple[int, int]]:
    """Indices (i, j) of node pairs on DIFFERENT helices within ``r_cut`` (nm).

    Uses a scipy cKDTree when available (O(N log N)); falls back to a plain O(N²) scan.
    Same-helix pairs are excluded (SI S6: interaction is *between* helices).
    """
    n = len(positions)
    if n < 2:
        return []
    hid = list(helix_ids)
    pairs: List[Tuple[int, int]] = []
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(positions)
        for i, j in tree.query_pairs(r_cut, output_type="ndarray"):
            if hid[i] != hid[j]:
                pairs.append((int(i), int(j)))
    except Exception:  # noqa: BLE001 — no scipy / degenerate: O(N²) fallback
        rc2 = r_cut * r_cut
        for i in range(n):
            pi = positions[i]
            for j in range(i + 1, n):
                if hid[i] == hid[j]:
                    continue
                d = positions[j] - pi
                if float(d @ d) <= rc2:
                    pairs.append((i, j))
    return pairs


def assemble_electrostatics(helix_ids: Sequence, positions: np.ndarray, prm: ESParams,
                            *, scale: float = 1.0, axial_only: bool = False):
    """Assemble the electrostatic repulsion into (triplet stiffness contributions, force).

    Returns ``(rows, cols, vals, f)`` where (rows, cols, vals) are COO entries to add to the
    6N global stiffness on the TRANSLATIONAL DOFs (rotational DOFs untouched — S6.2), and
    ``f`` is the 6N global repulsive force vector.  ``scale`` ∈ [0,1] ramps the interaction on
    during the nonlinear continuation (SI S9 generates electrostatic elements gradually).

    Both the stiffness and the force use the SAME pair set at the current ``positions`` — a
    consistent tangent, so Newton converges quadratically (finite-difference-checked in tests).
    """
    n = len(positions)
    f = np.zeros(6 * n, dtype=float)
    rows: List[int] = []
    cols: List[int] = []
    vals: List[float] = []
    if scale == 0.0:
        return rows, cols, vals, f
    for i, j in inter_helix_pairs(helix_ids, positions, prm.r_cut):
        f_j, K = pair_force_stiffness(positions[j] - positions[i], prm, axial_only=axial_only)
        f_j = f_j * scale
        K = K * scale
        di, dj = 6 * i, 6 * j          # translational DOF base (first 3 of each node)
        f[dj:dj + 3] += f_j
        f[di:di + 3] -= f_j
        for a in range(3):
            for b in range(3):
                v = K[a, b]
                if v == 0.0:
                    continue
                rows += [dj + a, di + a, dj + a, di + a]
                cols += [dj + b, di + b, di + b, dj + b]
                vals += [v, v, -v, -v]
    return rows, cols, vals, f
