"""
Step 4 — Convergence diagnostics for parameterization trajectories.

All six inter-arm coordinates must converge before parameters are trusted.
This module provides:
  - Block averaging (Flyvbjerg-Petersen) for unbiased variance estimates
  - Running mean / running covariance vs. simulation time
  - Effective sample size via integrated autocorrelation time
  - A gating function: emit a warning if any coordinate has not converged

Usage
-----
    from backend.parameterization.convergence import check, plot_diagnostics
    report = check(params)           # in-place update of params.converged
    plot_diagnostics(q_series, out_dir)

Reference: Flyvbjerg & Petersen, J. Chem. Phys. 91, 461 (1989).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from backend.parameterization.param_extract import CrossoverParameters

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

_MIN_ESS = 100       # minimum effective sample size per coordinate
_MAX_RUNNING_DRIFT = 0.10   # max fractional drift of running mean in final 25% of traj

_DOF_NAMES = [
    "q0 (separation, Å)",
    "q1 (perp1, Å)",
    "q2 (perp2, Å)",
    "q3 (Euler α, rad)",
    "q4 (Euler β, rad)",
    "q5 (Euler γ, rad)",
]


# ── Block averaging ───────────────────────────────────────────────────────────

def _block_average_variance(x: np.ndarray, min_blocks: int = 4) -> np.ndarray:
    """
    Estimate variance of the mean via block averaging.

    Returns the block-averaged variance at each block size from 1 to len(x)//min_blocks.
    The plateau value is the unbiased variance of the mean.

    Parameters
    ----------
    x : (n,) array or (n, d) array
        Time series.  If 2D, each column is treated independently.
    min_blocks : int
        Minimum number of blocks required at the largest block size.

    Returns
    -------
    block_vars : (n_block_sizes,) or (n_block_sizes, d) array
        Variance of block means at each block size.
    """
    n = len(x)
    max_block_size = n // min_blocks
    if max_block_size < 2:
        return np.var(x, axis=0, ddof=1)[None, ...]

    block_sizes = np.unique(np.logspace(0, np.log2(max_block_size), num=20, base=2).astype(int))
    block_vars = []
    for bs in block_sizes:
        n_blocks = n // bs
        if n_blocks < min_blocks:
            break
        trimmed = x[:n_blocks * bs]
        blocks = trimmed.reshape(n_blocks, bs, -1) if x.ndim > 1 else trimmed.reshape(n_blocks, bs)
        block_means = blocks.mean(axis=1)
        block_vars.append(np.var(block_means, axis=0, ddof=1) / n_blocks)
    return np.array(block_vars)


# ── Integrated autocorrelation time ──────────────────────────────────────────

def _integrated_autocorr_time(x: np.ndarray, max_lag_fraction: float = 0.1) -> np.ndarray:
    """
    Estimate the integrated autocorrelation time τ for each column of x.

    τ is estimated using the Sokal windowed estimator: sum C(t)/C(0) until
    the window condition t < 5τ is satisfied.

    Returns τ in units of frames.  ESS = N / (2τ).
    """
    n = len(x)
    if x.ndim == 1:
        x = x[:, None]
    d = x.shape[1]
    taus = np.zeros(d)
    max_lag = max(2, int(n * max_lag_fraction))

    for col in range(d):
        c = x[:, col] - x[:, col].mean()
        c0 = np.dot(c, c) / n
        if c0 < 1e-20:
            taus[col] = 1.0
            continue

        tau = 0.5
        window = 1
        for t in range(1, max_lag):
            rho_t = np.dot(c[:-t], c[t:]) / (n * c0)
            tau += rho_t
            if t >= window * 5:
                break
            window = max(window, int(5 * tau + 0.5))
        taus[col] = max(0.5, tau)

    return taus if d > 1 else taus[0]


# ── Running mean / covariance ─────────────────────────────────────────────────

def _running_mean(Q: np.ndarray, n_points: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the running mean of Q at n_points evenly spaced intervals.

    Returns (frame_indices, running_means) where running_means[i] is the
    cumulative mean using frames 0..frame_indices[i].
    """
    n = len(Q)
    checkpoints = np.unique(np.linspace(1, n, n_points, dtype=int))
    means = np.array([Q[:cp].mean(axis=0) for cp in checkpoints])
    return checkpoints, means


def _running_cov_diag(Q: np.ndarray, n_points: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Return (frame_indices, running_variances) for diagonal of covariance."""
    n = len(Q)
    checkpoints = np.unique(np.linspace(max(2, n // n_points), n, n_points, dtype=int))
    variances = np.array([np.var(Q[:cp], axis=0, ddof=1) for cp in checkpoints])
    return checkpoints, variances


# ── Convergence check ─────────────────────────────────────────────────────────

def check(
    params: CrossoverParameters,
    q_series: np.ndarray | None = None,
    min_ess: int = _MIN_ESS,
    max_running_drift: float = _MAX_RUNNING_DRIFT,
) -> dict:
    """
    Run convergence diagnostics and update params.converged in-place.

    Parameters
    ----------
    params : CrossoverParameters
        Output from param_extract.extract_parameters().  q_series is optional
        if n_frames and q_std are already populated.
    q_series : (n_frames, 6) array, optional
        Raw inter-arm coordinate time series.  Required for ESS and running-mean
        analysis; if None, only basic checks on params are done.
    min_ess : int
        Minimum effective sample size per coordinate (default: 100).
    max_running_drift : float
        Maximum fractional drift of running mean in final 25% (default: 0.10).

    Returns
    -------
    report : dict with keys passed, warnings, ess_per_dof, running_mean_drift,
             recommendation.
    """
    warnings: list[str] = []
    ess_per_dof = None
    running_mean_drift = None

    if params.n_frames < 500:
        warnings.append(
            f"Only {params.n_frames} frames — likely insufficient for converged "
            "covariance (need ≥ 500 frames at 20 ps spacing = 10 ns minimum)."
        )

    if q_series is not None:
        Q = np.asarray(q_series)

        # ESS via integrated autocorrelation time
        taus = _integrated_autocorr_time(Q)
        ess = Q.shape[0] / (2 * taus)
        ess_per_dof = ess.tolist()

        for i, (e, name) in enumerate(zip(ess, _DOF_NAMES)):
            if e < min_ess:
                warnings.append(
                    f"DOF {i} ({name}): ESS = {e:.0f} < {min_ess}.  "
                    "Extend the production run."
                )

        # Running mean drift: fraction of final-value range seen in last 25%
        n = len(Q)
        final_quarter = Q[3 * n // 4:]
        overall_mean = Q.mean(axis=0)
        q_std = Q.std(axis=0)
        q_std_safe = np.where(q_std > 1e-10, q_std, 1.0)

        fq_mean = final_quarter.mean(axis=0)
        drift = np.abs(fq_mean - overall_mean) / q_std_safe
        running_mean_drift = drift.tolist()

        for i, (d, name) in enumerate(zip(drift, _DOF_NAMES)):
            if d > max_running_drift:
                warnings.append(
                    f"DOF {i} ({name}): running mean drifted by {d:.2f}σ in final 25% "
                    "of trajectory — not yet equilibrated."
                )

    passed = len(warnings) == 0
    params.converged = passed
    params.convergence_warnings = warnings

    if not passed:
        recommendation = (
            f"DO NOT USE THESE PARAMETERS — {len(warnings)} convergence warning(s). "
            "Extend the production run and re-run param_extract.extract_parameters()."
        )
        logger.warning("Convergence check FAILED for %s: %s", params.variant_label, "; ".join(warnings))
    else:
        recommendation = "Convergence check passed."
        logger.info("Convergence check PASSED for %s (n_frames=%d)", params.variant_label, params.n_frames)

    return {
        "passed": passed,
        "warnings": warnings,
        "ess_per_dof": ess_per_dof,
        "running_mean_drift": running_mean_drift,
        "recommendation": recommendation,
        "n_frames": params.n_frames,
        "variant": params.variant_label,
    }


# ── Optional diagnostic plots ─────────────────────────────────────────────────

def plot_diagnostics(
    q_series: np.ndarray,
    out_dir: str | Path,
    variant_label: str = "",
) -> None:
    """
    Write diagnostic plots to out_dir:
      running_mean.png  — running means of all 6 DOFs vs time
      running_var.png   — running variances vs time
      block_avg.png     — block-averaged variance vs block size (Flyvbjerg-Petersen)

    Requires matplotlib.  Silently skips if not available.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.info("matplotlib not available; skipping diagnostic plots.")
        return

    if q_series is None:
        logger.info("plot_diagnostics: q_series is None — skipping plots.")
        return

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Q = np.asarray(q_series)
    n = len(Q)
    frames = np.arange(n)

    # Running mean
    cp, rm = _running_mean(Q)
    fig, axes = plt.subplots(6, 1, figsize=(10, 12), sharex=True)
    for i, (ax, name) in enumerate(zip(axes, _DOF_NAMES)):
        ax.plot(cp, rm[:, i])
        ax.axhline(Q[:, i].mean(), color="red", linestyle="--", linewidth=0.8)
        ax.set_ylabel(name, fontsize=7)
    axes[-1].set_xlabel("Frame")
    axes[0].set_title(f"Running means — {variant_label}")
    fig.tight_layout()
    fig.savefig(out_dir / "running_mean.png", dpi=120)
    plt.close(fig)

    # Running variance
    cp2, rv = _running_cov_diag(Q)
    fig, axes = plt.subplots(6, 1, figsize=(10, 12), sharex=True)
    for i, (ax, name) in enumerate(zip(axes, _DOF_NAMES)):
        ax.plot(cp2, rv[:, i])
        ax.set_ylabel(name, fontsize=7)
    axes[-1].set_xlabel("Frame")
    axes[0].set_title(f"Running variances — {variant_label}")
    fig.tight_layout()
    fig.savefig(out_dir / "running_var.png", dpi=120)
    plt.close(fig)

    # Block averaging
    bv = _block_average_variance(Q)
    if len(bv) > 1:
        fig, axes = plt.subplots(6, 1, figsize=(10, 12), sharex=True)
        block_sizes = np.logspace(0, np.log2(n // 4), num=len(bv), base=2)
        for i, (ax, name) in enumerate(zip(axes, _DOF_NAMES)):
            ax.semilogx(block_sizes, bv[:, i] if bv.ndim > 1 else bv)
            ax.set_ylabel(name, fontsize=7)
        axes[-1].set_xlabel("Block size (frames)")
        axes[0].set_title(f"Block-averaged variance (Flyvbjerg-Petersen) — {variant_label}")
        fig.tight_layout()
        fig.savefig(out_dir / "block_avg.png", dpi=120)
        plt.close(fig)

    logger.info("Diagnostic plots written to %s", out_dir)
