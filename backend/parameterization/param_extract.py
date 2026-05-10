"""
Step 3 — Parameter extraction from production trajectories.

Loads a GROMACS production trajectory (XTC + TPR/GRO), defines local reference
frames on each arm of the inter-crossover region, computes the 6-DOF inter-arm
time series, and returns the effective harmonic potential via Boltzmann inversion
of the covariance matrix.

Coordinate system
-----------------
The inter-crossover arm spans ~20 bp between the two crossover pairs.  We split
this arm into two halves relative to its midpoint, defining one reference frame
per half using the helical axis of the central 5 bp of that half.

For each frame, the axis is the first principal component of the C1' atom
positions (a robust, solvation-insensitive reporter of local helix geometry).

The 6 inter-arm coordinates are:
  q[0]  : separation along the inter-arm axis (Å)
  q[1]  : displacement perpendicular to axis, direction 1 (Å)
  q[2]  : displacement perpendicular to axis, direction 2 (Å)
  q[3]  : Euler angle α — rotation about inter-arm axis (rad)
  q[4]  : Euler angle β — tilt of one arm relative to other (rad)
  q[5]  : Euler angle γ — twist of one arm relative to other (rad)

Stiffness matrix
----------------
Under the harmonic approximation:
  K = kT × Cov⁻¹
where Cov is the 6×6 covariance matrix of q and kT = 2.479 kJ/mol at 310 K.

The diagonal of K gives the stiffness in each DOF.  The off-diagonal elements
encode coupling (e.g. stretch-twist coupling in DNA).

Mapping to mrdna parameters
----------------------------
  K[0,0] (stretch stiffness)    → bond k in HarmonicBond
  mean(q[0])                    → r0 in HarmonicBond
  K[3,3] (dihedral stiffness)   → dihedral k in HarmonicDihedral (junction angle)
  mean(q[3]) converted to deg   → hj_equilibrium_angle in SegmentModel
  K[4,4], K[5,5] (bend)         → orientation potential k (local_twist mode)

The full 6×6 matrix is saved for future use — current mrdna only consumes the
diagonal and equilibrium values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ── Physical constants ────────────────────────────────────────────────────────

_kT_kJ_MOL_310K = 2.5788   # kJ/mol at 310 K (kB × 310 K × NA)
_kT_KCAL_MOL_310K = 0.6162  # kcal/mol at 310 K

# LOCAL 0-based residue indices for the inter-crossover measurement arm.
# The 2hb helices start at global bp 7; crossovers at global bp 13-14 and 34-35.
# Measurement region = global bp 15-33 → local 0-based = global_bp - 7.
#   bp 15 → local 8,  bp 33 → local 26
_MEASUREMENT_BP_LO = 8
_MEASUREMENT_BP_HI = 26

# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class CrossoverParameters:
    """
    Extracted harmonic parameters for one crossover type.

    All stiffness values are in kJ/mol/rad² (angular) or kJ/mol/Å² (linear)
    depending on the DOF.  Equilibrium values are in Å (distances) or rad.

    Attributes
    ----------
    variant_label : str
        E.g. "T0".
    restraint_k_kcal : float
        Restraint spring constant used in the source run.
    q_mean : np.ndarray (6,)
        Equilibrium values of the 6 inter-arm coordinates.
    q_std : np.ndarray (6,)
        Standard deviations (sqrt of covariance diagonal).
    cov : np.ndarray (6, 6)
        Covariance matrix of the 6 coordinates.
    stiffness : np.ndarray (6, 6)
        Effective harmonic stiffness matrix K = kT × Cov⁻¹.
    mrdna_params : dict
        Scalar parameters extracted for mrdna injection (subset of the full
        6×6 matrix that current mrdna can consume).
    n_frames : int
        Number of trajectory frames used.
    converged : bool
        Whether convergence checks passed (set by convergence.py).
    convergence_warnings : list[str]
        Any convergence issues found.
    """
    variant_label: str
    restraint_k_kcal: float
    q_mean: np.ndarray
    q_std: np.ndarray
    cov: np.ndarray
    stiffness: np.ndarray
    mrdna_params: dict
    n_frames: int
    converged: bool = False
    convergence_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "variant_label": self.variant_label,
            "restraint_k_kcal": self.restraint_k_kcal,
            "q_mean": self.q_mean.tolist(),
            "q_std": self.q_std.tolist(),
            "cov": self.cov.tolist(),
            "stiffness": self.stiffness.tolist(),
            "mrdna_params": self.mrdna_params,
            "n_frames": self.n_frames,
            "converged": self.converged,
            "convergence_warnings": self.convergence_warnings,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "CrossoverParameters":
        d = json.loads(Path(path).read_text())
        return cls(
            variant_label=d["variant_label"],
            restraint_k_kcal=d["restraint_k_kcal"],
            q_mean=np.array(d["q_mean"]),
            q_std=np.array(d["q_std"]),
            cov=np.array(d["cov"]),
            stiffness=np.array(d["stiffness"]),
            mrdna_params=d["mrdna_params"],
            n_frames=d["n_frames"],
            converged=d["converged"],
            convergence_warnings=d["convergence_warnings"],
        )


# ── Reference frame helpers ───────────────────────────────────────────────────

def _helix_axis_from_c1prime(
    positions: np.ndarray,
    reference_axis: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the helix axis and origin from a set of C1' atom positions.

    Uses PCA: the first principal component is the helical axis direction.
    The sign is arbitrary; pass reference_axis to anchor it consistently
    across frames (axis is flipped if anti-aligned with the reference).

    Returns
    -------
    (origin, axis)  — origin is the centroid; axis is a unit vector.
    """
    origin = positions.mean(axis=0)
    centred = positions - origin
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    axis = vt[0]   # first right singular vector = direction of max variance
    axis = axis / np.linalg.norm(axis)
    if reference_axis is not None and np.dot(axis, reference_axis) < 0:
        axis = -axis
    return origin, axis


def _rotation_matrix_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix R such that R @ a ≈ b (both unit vectors)."""
    v = np.cross(a, b)
    s = np.linalg.norm(v)
    c = np.dot(a, b)
    if s < 1e-10:
        return np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 - c) / (s * s)


def _rotation_to_euler_zyz(R: np.ndarray) -> tuple[float, float, float]:
    """
    Decompose rotation matrix into ZYZ Euler angles (α, β, γ).

    Returns angles in radians.  β is the tilt (inter-arm angle).
    """
    beta = np.arccos(np.clip(R[2, 2], -1, 1))
    if np.abs(np.sin(beta)) < 1e-8:
        alpha = 0.0
        gamma = np.arctan2(-R[0, 1], R[0, 0]) if R[2, 2] > 0 else np.arctan2(R[0, 1], -R[0, 0])
    else:
        alpha = np.arctan2(R[1, 2], R[0, 2])
        gamma = np.arctan2(R[2, 1], -R[2, 0])
    return float(alpha), float(beta), float(gamma)


# ── Per-frame coordinate computation ─────────────────────────────────────────

def _compute_interarm_q(
    c1prime_arm1: np.ndarray,    # (n_bp_arm1, 3) C1' positions for arm 1
    c1prime_arm2: np.ndarray,    # (n_bp_arm2, 3) C1' positions for arm 2
    ref_ax1: np.ndarray | None = None,
    ref_ax2: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute the 6 inter-arm coordinates q for one trajectory frame.

    Returns
    -------
    q : np.ndarray shape (6,)
        [separation_A, perp1_A, perp2_A, euler_alpha_rad, euler_beta_rad, euler_gamma_rad]
    """
    o1, ax1 = _helix_axis_from_c1prime(c1prime_arm1, reference_axis=ref_ax1)
    o2, ax2 = _helix_axis_from_c1prime(c1prime_arm2, reference_axis=ref_ax2)

    # Separation vector from arm1 origin to arm2 origin
    sep_vec = o2 - o1

    # Project onto arm1 frame: (along ax1, perp1, perp2)
    along = np.dot(sep_vec, ax1)

    # Build a consistent perpendicular frame for arm1
    # perp_base: any vector not parallel to ax1
    ref = np.array([0, 0, 1]) if abs(ax1[2]) < 0.9 else np.array([1, 0, 0])
    perp1 = np.cross(ax1, ref)
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(ax1, perp1)

    q_sep = along
    q_p1 = np.dot(sep_vec, perp1)
    q_p2 = np.dot(sep_vec, perp2)

    # Relative rotation between the two arm frames
    # Build rotation that takes ax1 to ax2
    R_rel = _rotation_matrix_between(ax1, ax2)
    alpha, beta, gamma = _rotation_to_euler_zyz(R_rel)

    return np.array([q_sep, q_p1, q_p2, alpha, beta, gamma])


# ── Trajectory loading ────────────────────────────────────────────────────────

def _select_c1prime_atoms(universe, bp_lo: int, bp_hi: int, helix_idx: int):
    """
    Select C1' atoms for the specified bp range on a given chain (helix_idx).

    The 2hb design has two DNA helices.  We identify them as the two largest
    DNA chains in the universe (by residue count), then select C1' atoms in
    the measurement bp range.

    bp_lo, bp_hi are inclusive residue indices (0-based within the chain).
    """

    dna_chains = [
        s for s in universe.segments
        if any(r.resname in ("DA", "DT", "DG", "DC")
               for r in s.residues[:1])
    ]

    # Select the two scaffold helices — the two longest chains that share the
    # same residue count.  Central crossover staples can be LONGER than the
    # scaffold (e.g. 42 vs 35 residues in the 2hb design) so we cannot simply
    # take the two largest chains.
    from collections import Counter as _Counter
    length_counts = _Counter(len(s.residues) for s in dna_chains)
    # Target: the longest chain length that appears at least twice (a pair).
    paired_lengths = {l for l, n in length_counts.items() if n >= 2}
    if not paired_lengths:
        raise ValueError(
            "Could not find two DNA chains with matching residue counts. "
            "Expected two equal-length scaffold chains."
        )
    target_len = max(paired_lengths)
    scaffold_chains = [s for s in dna_chains if len(s.residues) == target_len]
    if len(scaffold_chains) < 2:
        raise ValueError(
            f"Expected at least 2 scaffold chains of length {target_len}; "
            f"found {len(scaffold_chains)}."
        )
    dna_chains_sorted = scaffold_chains

    chain = dna_chains_sorted[helix_idx]
    residues = chain.residues[bp_lo:bp_hi + 1]
    c1p = residues.atoms.select_atoms("name C1'")
    if len(c1p) == 0:
        raise ValueError(
            f"No C1' atoms found in chain {helix_idx} residues {bp_lo}–{bp_hi}."
        )
    return c1p


def extract_parameters(
    tpr_or_gro: str | Path,
    xtc_path: str | Path,
    variant_label: str,
    restraint_k_kcal: float,
    bp_lo: int = _MEASUREMENT_BP_LO,
    bp_hi: int = _MEASUREMENT_BP_HI,
    skip_frames: int = 1,
) -> CrossoverParameters:
    """
    Extract inter-arm harmonic parameters from a production trajectory.

    Parameters
    ----------
    tpr_or_gro : path
        GROMACS TPR or GRO file for the production run (topology + positions).
    xtc_path : path
        Production XTC trajectory.
    variant_label : str
        E.g. "T0".
    restraint_k_kcal : float
        Restraint spring constant used in the source run (for provenance).
    bp_lo, bp_hi : int
        Inclusive residue-index range of the measurement region within each
        helix (default: 15–33, i.e., the 20 bp inter-crossover arm).
    skip_frames : int
        Load every Nth frame (default: 1 = all frames).

    Returns
    -------
    CrossoverParameters with cov, stiffness, mrdna_params populated.
    converged is set to False; call convergence.check() to update it.

    Raises
    ------
    ImportError
        If MDAnalysis is not installed.
    ValueError
        If the trajectory has fewer than 50 usable frames.
    """
    try:
        import MDAnalysis as mda
    except ImportError as exc:
        raise ImportError(
            "MDAnalysis is required for parameter extraction.  "
            "Install with: pip install MDAnalysis"
        ) from exc

    u = mda.Universe(str(tpr_or_gro), str(xtc_path))
    logger.info(
        "Loaded trajectory: %d atoms, %d frames",
        u.atoms.n_atoms, u.trajectory.n_frames,
    )

    # Select C1' atoms in the measurement arm on each helix
    # helix_idx=0: larger scaffold chain; helix_idx=1: other scaffold chain
    arm1_c1p = _select_c1prime_atoms(u, bp_lo, bp_hi, helix_idx=0)
    arm2_c1p = _select_c1prime_atoms(u, bp_lo, bp_hi, helix_idx=1)
    logger.info(
        "C1' selection: arm1=%d atoms, arm2=%d atoms",
        len(arm1_c1p), len(arm2_c1p),
    )

    # Anchor helix axis signs using first frame — prevents PCA sign flips
    # from causing the q-vector components to average to near-zero.
    u.trajectory[0]
    _, ref_ax1 = _helix_axis_from_c1prime(arm1_c1p.positions.copy())
    _, ref_ax2 = _helix_axis_from_c1prime(arm2_c1p.positions.copy())

    # Accumulate per-frame q vectors
    q_frames: list[np.ndarray] = []
    for ts in u.trajectory[::skip_frames]:
        q = _compute_interarm_q(
            arm1_c1p.positions.copy(),
            arm2_c1p.positions.copy(),
            ref_ax1=ref_ax1,
            ref_ax2=ref_ax2,
        )
        q_frames.append(q)

    n_frames = len(q_frames)
    if n_frames < 50:
        raise ValueError(
            f"Only {n_frames} frames available; need at least 50 for reliable "
            "covariance estimation.  Extend the production run."
        )

    Q = np.array(q_frames)   # (n_frames, 6)
    q_mean = Q.mean(axis=0)
    q_std = Q.std(axis=0, ddof=1)
    cov = np.cov(Q.T)         # (6, 6)

    # Boltzmann inversion: K = kT × Cov⁻¹
    try:
        cov_inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        logger.warning("Covariance matrix is singular — using pseudoinverse.")
        cov_inv = np.linalg.pinv(cov)
    stiffness = _kT_kJ_MOL_310K * cov_inv

    # Extract scalar parameters for mrdna
    mrdna_params = _map_to_mrdna(q_mean, stiffness)

    logger.info(
        "Extracted parameters: r0=%.2f Å, k_bond=%.3f kJ/mol/Å², "
        "hj_angle=%.1f°, k_dihedral=%.4f kJ/mol/rad²",
        mrdna_params["r0_ang"],
        mrdna_params["k_bond_kJ_mol_ang2"],
        np.degrees(mrdna_params["hj_equilibrium_angle_rad"]),
        mrdna_params["k_dihedral_kJ_mol_rad2"],
    )

    result = CrossoverParameters(
        variant_label=variant_label,
        restraint_k_kcal=restraint_k_kcal,
        q_mean=q_mean,
        q_std=q_std,
        cov=cov,
        stiffness=stiffness,
        mrdna_params=mrdna_params,
        n_frames=n_frames,
        converged=False,
        convergence_warnings=["Convergence not yet checked — call convergence.check()"],
    )
    result._q_series = Q  # attach for convergence.check() / plot_diagnostics()
    return result


def _map_to_mrdna(q_mean: np.ndarray, stiffness: np.ndarray) -> dict:
    """
    Map 6-DOF mean + stiffness to the scalar parameters that mrdna can consume.

    Current mrdna (SegmentModel) uses:
      - HarmonicBond(k, r0)  for the inter-bead distance
      - HarmonicDihedral(k, t0) for the junction angle (hj_equilibrium_angle)
      - Orientation potential k (from local_twist mode)

    Units output:
      r0_ang           : Å  (mrdna uses Å internally)
      k_bond_kJ_mol_ang2 : kJ/mol/Å²
      hj_equilibrium_angle_rad : rad  (pass to SegmentModel as degrees)
      k_dihedral_kJ_mol_rad2   : kJ/mol/rad²
      k_bend_kJ_mol_rad2       : kJ/mol/rad² (average of tilt + twist bending)

    Note: mrdna's crossover bond r0 is 18.5 Å for a standard crossover.
    The extracted r0 will differ for extra-T variants.
    """
    # For a DX junction the two helices are side-by-side: the equilibrium
    # separation is mostly perpendicular to the helix axis (q[1] or q[2]),
    # not axial (q[0]≈0).  Use the Euclidean distance of the mean separation
    # vector as r0, and the stiffness in the dominant lateral direction as k_bond.
    r0_ang = float(np.linalg.norm(q_mean[:3]))           # Euclidean |sep_vec| in Å
    lateral_idx = int(np.argmax(np.abs(q_mean[1:3]))) + 1  # 1 or 2, dominant perp
    k_stretch = float(stiffness[lateral_idx, lateral_idx])  # kJ/mol/Å²

    hj_angle_rad = float(q_mean[3])                     # q[3] = α (dihedral-like)
    k_dihedral = float(stiffness[3, 3])                 # kJ/mol/rad²

    k_bend = float(0.5 * (stiffness[4, 4] + stiffness[5, 5]))  # average tilt+twist

    # Warn if any coupling term is large relative to diagonal
    max_off_diag = 0.0
    for i in range(6):
        for j in range(6):
            if i != j:
                frac = abs(stiffness[i, j]) / (np.sqrt(stiffness[i, i] * stiffness[j, j]) + 1e-10)
                max_off_diag = max(max_off_diag, frac)
    if max_off_diag > 0.3:
        logger.warning(
            "Large off-diagonal coupling in stiffness matrix (max fraction=%.2f). "
            "Diagonal-only mrdna injection will miss this coupling.",
            max_off_diag,
        )

    return {
        "r0_ang": r0_ang,
        "k_bond_kJ_mol_ang2": k_stretch,
        "hj_equilibrium_angle_rad": hj_angle_rad,
        "hj_equilibrium_angle_deg": float(np.degrees(hj_angle_rad)),
        "k_dihedral_kJ_mol_rad2": k_dihedral,
        "k_bend_kJ_mol_rad2": k_bend,
        "max_off_diagonal_coupling_fraction": float(max_off_diag),
        "full_6dof_stiffness_available": True,
        "note": (
            "Only diagonal terms are injected into mrdna (current version). "
            "Off-diagonal coupling is saved in stiffness for future use."
        ),
    }


# ── Restraint sensitivity check ───────────────────────────────────────────────

def check_restraint_sensitivity(
    params_by_k: dict[float, CrossoverParameters],
    threshold: float = 0.20,
) -> dict:
    """
    Compare stiffness matrix diagonals across restraint-k sweep runs.

    Parameters
    ----------
    params_by_k : dict mapping restraint_k → CrossoverParameters
        Must contain at least 2 entries.
    threshold : float
        Maximum acceptable fractional variation in any stiffness diagonal
        element across the k sweep (default: 0.20 = 20%).

    Returns
    -------
    dict with keys:
        passed : bool — True if all elements within threshold
        max_variation : float — maximum fractional variation observed
        flagged_dofs : list[int] — DOF indices that exceeded threshold
        recommendation : str — what to do if failed
    """
    if len(params_by_k) < 2:
        return {
            "passed": None,
            "max_variation": None,
            "flagged_dofs": [],
            "recommendation": "Need at least 2 k values for sensitivity check.",
        }

    k_vals = sorted(params_by_k.keys())
    diags = np.array([params_by_k[k].stiffness.diagonal() for k in k_vals])
    # Fractional variation: (max - min) / mean across k sweep, per DOF
    diag_mean = diags.mean(axis=0)
    diag_range = diags.max(axis=0) - diags.min(axis=0)
    frac_var = diag_range / (np.abs(diag_mean) + 1e-10)

    max_variation = float(frac_var.max())
    flagged = [int(i) for i in np.where(frac_var > threshold)[0]]
    passed = len(flagged) == 0

    dof_names = [
        "q0 (separation)",
        "q1 (perp1)",
        "q2 (perp2)",
        "q3 (Euler α / dihedral)",
        "q4 (Euler β / tilt)",
        "q5 (Euler γ / twist)",
    ]

    recommendation = ""
    if not passed:
        recommendation = (
            f"RESTRAINT BIAS DETECTED: DOFs {[dof_names[i] for i in flagged]} vary "
            f"by >{threshold*100:.0f}% across the k sweep.  The outer arm stubs are "
            f"too short for soft position restraints to give unbiased results.  "
            f"Consider: (a) position restraints with much softer k < 0.1 kcal/mol/Å², "
            f"(b) switching to orientational restraints at the helix termini, or "
            f"(c) extending the outer arm length in the reference design."
        )
        logger.error(recommendation)
    else:
        recommendation = (
            f"Restraint sensitivity check passed: max variation = {max_variation*100:.1f}% "
            f"< {threshold*100:.0f}% threshold.  Outer-arm restraints are not biasing results."
        )
        logger.info(recommendation)

    return {
        "passed": passed,
        "max_variation": max_variation,
        "fractional_variation_per_dof": frac_var.tolist(),
        "flagged_dofs": flagged,
        "dof_names": dof_names,
        "k_values_tested": k_vals,
        "recommendation": recommendation,
    }
