#!/usr/bin/env python3
"""
Bundle inter-helix stiffness parameter extraction.

Computes 6-DOF inter-helix stiffness parameters from a GROMACS production
trajectory, grouped by the neighbor-count context of the two helices:
  - "2-2": both helices have 2 nearest neighbors (edge helices)
  - "2-3": one helix has 2 neighbors, the other has 3 (junction)
  - "3-3": both helices have 3 nearest neighbors (internal pair)

For each neighboring helix pair the 6-DOF inter-helix coordinate is:
  q[0] : axial separation (along helix A axis) [Å]
  q[1] : lateral separation, direction 1 [Å]
  q[2] : lateral separation, direction 2 [Å]
  q[3] : Euler α (in-plane rotation) [rad] — unreliable when tilt < 15° (gimbal lock)
  q[4] : Euler β (tilt) [rad]
  q[5] : Euler γ (out-of-plane twist) [rad] — unreliable when tilt < 15° (gimbal lock)

Stiffness: K = kT × Cov⁻¹  (kT = 2.579 kJ/mol at 310 K)

Usage
-----
    python bundle_extract.py --run-dir ./nominal --design /path/to/design.nadoc \\
                             [--skip 5] [--out-dir ./nominal]

See docs/bundle_param_extraction.md for known limitations and convergence guidance.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO))

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_to_nadoc import (
    _GRO_DNA_RESNAMES,
    build_chain_map,
    build_p_gro_order,
)
from backend.parameterization.param_extract import (
    _helix_axis_from_c1prime,
    _rotation_matrix_between,
    _rotation_to_euler_zyz,
)

_kT_kJ_MOL = 2.5788   # kJ/mol at 310 K

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("extract_bundle")

# ── Helix neighbor graph ───────────────────────────────────────────────────────
# Derived from crossover connectivity in 10hb.nadoc.
# Each pair listed once; the graph is symmetric.
_HELIX_NEIGHBOR_PAIRS: list[tuple[str, str]] = [
    ("h_XY_0_0",  "h_XY_0_-1"),
    ("h_XY_0_0",  "h_XY_0_1"),
    ("h_XY_0_-1", "h_XY_1_-1"),
    ("h_XY_1_-1", "h_XY_1_0"),
    ("h_XY_1_0",  "h_XY_1_1"),
    ("h_XY_1_1",  "h_XY_0_1"),
    ("h_XY_1_1",  "h_XY_1_2"),
    ("h_XY_0_1",  "h_XY_0_2"),
    ("h_XY_1_2",  "h_XY_1_3"),
    ("h_XY_1_3",  "h_XY_0_3"),
    ("h_XY_0_3",  "h_XY_0_2"),
]

# 3-neighbor (internal) helices
_THREE_NEIGHBOR = {"h_XY_1_1", "h_XY_0_1"}


def _neighbor_count(h_id: str) -> int:
    return 3 if h_id in _THREE_NEIGHBOR else 2


def _context_label(h_a: str, h_b: str) -> str:
    n_a = _neighbor_count(h_a)
    n_b = _neighbor_count(h_b)
    lo, hi = sorted([n_a, n_b])
    return f"{lo}-{hi}"


# ── Residue-to-helix assignment from NADOC geometry ───────────────────────────

def _assign_residues_to_helices(
    u,  # MDAnalysis Universe
    design: Design,
    pdb_path: Path,
) -> dict[str, list]:
    """
    Assign each DNA residue in the trajectory to a NADOC helix using
    topology-based mapping via build_p_gro_order.

    GROMACS preserves the atom ordering from pdb2gmx (which reads input_nadoc.pdb),
    so the i-th P atom in the MDAnalysis selection matches the i-th entry in
    p_order — giving an exact residue → (helix_id, bp_index, direction) mapping
    without any geometry-dependent nearest-axis search.

    Returns dict: h_id → list of (resindex, bp_idx) sorted by bp_idx.
    """
    pdb_text = pdb_path.read_text()
    model    = build_atomistic_model(design)
    cmap     = build_chain_map(model)
    p_order  = build_p_gro_order(pdb_text, cmap)

    # Select DNA P atoms in GROMACS atom order
    sel_str = "name P and resname " + " ".join(sorted(_GRO_DNA_RESNAMES))
    p_atoms = u.select_atoms(sel_str)

    if len(p_atoms) != len(p_order):
        raise ValueError(
            f"P atom count mismatch: GROMACS has {len(p_atoms)}, "
            f"p_order has {len(p_order)}. "
            f"Check that {pdb_path.name} matches the trajectory topology."
        )

    log.info("Topology-based assignment: %d P atoms mapped to %d NADOC helices",
             len(p_atoms), len({e[0] for e in p_order}))

    result: dict[str, list] = {h.id: [] for h in design.helices}
    for pa, (helix_id, bp_index, _direction) in zip(p_atoms, p_order):
        result[helix_id].append((pa.residue.ix, bp_index))

    for h_id in result:
        result[h_id].sort(key=lambda x: x[1])
        log.info("  %-20s: %d residues", h_id, len(result[h_id]))

    return result


# ── Per-frame 6-DOF inter-helix coordinate ────────────────────────────────────

def _interhelix_q(
    c1p_A: np.ndarray,  # (n_A, 3) C1' positions for helix A [Å]
    c1p_B: np.ndarray,  # (n_B, 3) C1' positions for helix B [Å]
    ref_ax_A=None,
    ref_ax_B=None,
) -> np.ndarray:
    """Return 6-DOF coordinate vector for one frame."""
    o_A, ax_A = _helix_axis_from_c1prime(c1p_A, reference_axis=ref_ax_A)
    o_B, ax_B = _helix_axis_from_c1prime(c1p_B, reference_axis=ref_ax_B)

    sep_vec = o_B - o_A
    along   = float(np.dot(sep_vec, ax_A))

    ref = np.array([0, 0, 1]) if abs(ax_A[2]) < 0.9 else np.array([1, 0, 0])
    perp1 = np.cross(ax_A, ref);  perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(ax_A, perp1)

    q_sep = along
    q_p1  = float(np.dot(sep_vec, perp1))
    q_p2  = float(np.dot(sep_vec, perp2))

    R_rel = _rotation_matrix_between(ax_A, ax_B)
    alpha, beta, gamma = _rotation_to_euler_zyz(R_rel)

    return np.array([q_sep, q_p1, q_p2, alpha, beta, gamma])


# ── Block-averaging for uncertainty ───────────────────────────────────────────

def _block_sem(q_series: np.ndarray, n_blocks: int = 10) -> np.ndarray:
    """Standard error of the mean via block averaging."""
    n = len(q_series)
    if n < n_blocks:
        return np.full(q_series.shape[1], np.nan)
    block_size = n // n_blocks
    blocks = np.array([
        q_series[i*block_size:(i+1)*block_size].mean(axis=0)
        for i in range(n_blocks)
    ])
    return blocks.std(axis=0, ddof=1) / np.sqrt(n_blocks)


# ── ESS estimate ──────────────────────────────────────────────────────────────

def _ess(q_series: np.ndarray) -> np.ndarray:
    """Effective sample size via integrated autocorrelation (first-lag estimate)."""
    n = len(q_series)
    q_c = q_series - q_series.mean(axis=0)
    var = (q_c**2).mean(axis=0)
    rho1 = (q_c[:-1] * q_c[1:]).mean(axis=0) / (var + 1e-30)
    tau  = 1.0 + 2.0 * np.clip(rho1, 0, 0.99)
    return n / tau


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_bundle_params(
    run_dir: Path,
    out_dir: Path,
    design_path: Path,
    skip_frames: int = 1,
) -> dict[str, dict]:
    """
    Extract per-pair and per-context 6-DOF stiffness parameters.

    Parameters
    ----------
    run_dir     : GROMACS run directory (must contain input_nadoc.pdb and trajectory).
    out_dir     : Directory to write JSON output files.
    design_path : Path to the .nadoc design file.
    skip_frames : Load every Nth frame (1 = all).

    Returns dict: context_label → parameter dict.
    """
    try:
        import MDAnalysis as mda
    except ImportError:
        raise ImportError("MDAnalysis required: pip install MDAnalysis")

    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Topology: em.tpr > prod_best.tpr > prod.tpr > npt.gro (em.tpr is always present)
    top_candidates = ["em.tpr", "prod_best.tpr", "prod.tpr", "npt.gro"]
    top = next((str(run_dir / f) for f in top_candidates if (run_dir / f).exists()), None)
    if top is None:
        raise FileNotFoundError(f"No topology file found in {run_dir}")

    # Trajectory priority:
    #   1. prod_best.part*.xtc if any part is newer than view_whole.xtc — raw parts
    #      have more data once the sim continues past what view_whole covered
    #   2. view_whole.xtc  — PBC-preprocessed (stale once production continues)
    #   3. prod.xtc  — legacy / short benchmark run
    view_whole = run_dir / "view_whole.xtc"
    prod_parts = sorted(run_dir.glob("prod_best.part*.xtc"))
    prod_orig  = run_dir / "prod.xtc"

    # Use production parts if any are newer than view_whole (sim has continued past it)
    parts_newer = prod_parts and (
        not view_whole.exists()
        or max(p.stat().st_mtime for p in prod_parts) > view_whole.stat().st_mtime
    )

    if parts_newer:
        xtc_files = [str(p) for p in prod_parts]
        log.info("Using %d prod_best.part*.xtc (newer than view_whole.xtc): %s … %s",
                 len(xtc_files), prod_parts[0].name, prod_parts[-1].name)
    elif view_whole.exists():
        xtc_files = [str(view_whole)]
        log.info("Using PBC-preprocessed trajectory: view_whole.xtc")
    elif prod_orig.exists():
        xtc_files = [str(prod_orig)]
        log.warning("Falling back to prod.xtc (short run — only %s)", prod_orig)
    else:
        raise FileNotFoundError(f"No production XTC found in {run_dir}")

    log.info("Topology: %s", top)
    u = mda.Universe(top, *xtc_files)
    log.info("Trajectory: %d atoms, %d frames", u.atoms.n_atoms, u.trajectory.n_frames)

    raw = json.loads(Path(design_path).read_text())
    design = Design.model_validate(raw)

    pdb_path = run_dir / "input_nadoc.pdb"
    if not pdb_path.exists():
        raise FileNotFoundError(f"input_nadoc.pdb not found in {run_dir}")

    # Topology-based residue-to-helix assignment (uses GROMACS atom ordering)
    helix_residues = _assign_residues_to_helices(u, design, pdb_path)

    # For each pair, accumulate q-series
    pair_q: dict[tuple[str,str], list[np.ndarray]] = {
        pair: [] for pair in _HELIX_NEIGHBOR_PAIRS
    }

    # Anchor axes using frame 0 to prevent PCA sign flips across frames.
    # All design helices run along +Z, so snap the initial reference to +Z as
    # well. Without this, PCA returns an arbitrary ±Z sign per helix, causing
    # ~180° apparent tilts between pairs that happen to get opposite signs.
    u.trajectory[0]
    ref_axes: dict[str, np.ndarray] = {}
    for h_id, entries in helix_residues.items():
        if not entries:
            continue
        rixs = [e[0] for e in entries]
        c1p = u.residues[rixs].atoms.select_atoms("name C1'").positions.copy()
        if len(c1p) >= 3:
            _, ax = _helix_axis_from_c1prime(c1p)
            if ax[2] < 0:   # snap to +Z to match design axis convention
                ax = -ax
            ref_axes[h_id] = ax

    log.info("Accumulating %d frames (skip=%d) …", u.trajectory.n_frames, skip_frames)
    for ts in u.trajectory[::skip_frames]:
        for h_a, h_b in _HELIX_NEIGHBOR_PAIRS:
            entries_a = helix_residues.get(h_a, [])
            entries_b = helix_residues.get(h_b, [])
            if len(entries_a) < 3 or len(entries_b) < 3:
                continue
            rixs_a = [e[0] for e in entries_a]
            rixs_b = [e[0] for e in entries_b]
            c1p_a = u.residues[rixs_a].atoms.select_atoms("name C1'").positions.copy()
            c1p_b = u.residues[rixs_b].atoms.select_atoms("name C1'").positions.copy()
            if len(c1p_a) < 3 or len(c1p_b) < 3:
                continue
            q = _interhelix_q(
                c1p_a, c1p_b,
                ref_ax_A=ref_axes.get(h_a),
                ref_ax_B=ref_axes.get(h_b),
            )
            pair_q[(h_a, h_b)].append(q)

    # ── Compute per-pair and per-context parameters ───────────────────────────
    dof_names = [
        "q0_axial_sep_A",
        "q1_lateral1_A",
        "q2_lateral2_A",
        "q3_euler_alpha_rad",
        "q4_euler_beta_tilt_rad",
        "q5_euler_gamma_twist_rad",
    ]

    all_pair_results: dict[str, dict] = {}
    context_q: dict[str, list[np.ndarray]] = {}

    for (h_a, h_b), frames in pair_q.items():
        if len(frames) < 50:
            log.warning("Pair %s↔%s: only %d frames — skipping", h_a, h_b, len(frames))
            continue

        Q = np.array(frames)   # (n_frames, 6)
        q_mean = Q.mean(axis=0)
        q_std  = Q.std(axis=0, ddof=1)
        cov    = np.cov(Q.T)
        try:
            cov_inv = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            cov_inv = np.linalg.pinv(cov)
        stiffness = _kT_kJ_MOL * cov_inv

        block_sem = _block_sem(Q)
        ess_vals  = _ess(Q)

        ctx = _context_label(h_a, h_b)
        if ctx not in context_q:
            context_q[ctx] = []
        context_q[ctx].append(Q)

        pair_key = f"{h_a}_vs_{h_b}"
        all_pair_results[pair_key] = {
            "helix_a": h_a,
            "helix_b": h_b,
            "n_nbrs_a": _neighbor_count(h_a),
            "n_nbrs_b": _neighbor_count(h_b),
            "context": ctx,
            "n_frames": len(frames),
            "q_mean": q_mean.tolist(),
            "q_std":  q_std.tolist(),
            "q_mean_physical": {
                "center_to_center_dist_A": float(np.linalg.norm(q_mean[:3])),
                "axial_sep_A":  float(q_mean[0]),
                "lateral_sep_A": float(np.linalg.norm(q_mean[1:3])),
                "tilt_angle_deg": float(np.degrees(q_mean[4])),
            },
            "stiffness_diagonal": stiffness.diagonal().tolist(),
            "stiffness_matrix": stiffness.tolist(),
            "cov_matrix": cov.tolist(),
            "block_sem": block_sem.tolist(),
            "ess_per_dof": ess_vals.tolist(),
            "dof_names": dof_names,
            "converged_dofs": [
                dof_names[i] for i in range(6)
                if ess_vals[i] > 50 and block_sem[i] < 0.1 * abs(q_std[i])
            ],
        }
        log.info(
            "Pair %s↔%s [%s]: n=%d  d=%.1f Å  tilt=%.1f°  K_perp=%.3f kJ/mol/Å²",
            h_a, h_b, ctx, len(frames),
            all_pair_results[pair_key]["q_mean_physical"]["center_to_center_dist_A"],
            all_pair_results[pair_key]["q_mean_physical"]["tilt_angle_deg"],
            stiffness.diagonal()[1],
        )

    # ── Aggregate by context ──────────────────────────────────────────────────
    context_results: dict[str, dict] = {}
    for ctx, q_list in context_q.items():
        Q_all = np.concatenate(q_list, axis=0)
        q_mean = Q_all.mean(axis=0)
        q_std  = Q_all.std(axis=0, ddof=1)
        cov    = np.cov(Q_all.T)
        try:
            stiffness = _kT_kJ_MOL * np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            stiffness = _kT_kJ_MOL * np.linalg.pinv(cov)
        ess_vals = _ess(Q_all)
        context_results[ctx] = {
            "context": ctx,
            "n_pairs": sum(1 for p in all_pair_results.values() if p["context"] == ctx),
            "n_frames_total": len(Q_all),
            "q_mean": q_mean.tolist(),
            "q_std":  q_std.tolist(),
            "stiffness_diagonal": stiffness.diagonal().tolist(),
            "stiffness_matrix": stiffness.tolist(),
            "cov_matrix": cov.tolist(),
            "ess_per_dof": ess_vals.tolist(),
            "dof_names": dof_names,
            "q_mean_physical": {
                "center_to_center_dist_A": float(np.linalg.norm(q_mean[:3])),
                "lateral_sep_A": float(np.linalg.norm(q_mean[1:3])),
                "tilt_angle_deg": float(np.degrees(q_mean[4])),
            },
            "note": (
                f"Context {ctx!r}: stiffness pooled from all {ctx}-type "
                f"neighbor pairs using Boltzmann inversion of the 6-DOF covariance."
            ),
        }

    # ── Save outputs ──────────────────────────────────────────────────────────
    (out_dir / "all_pairs.json").write_text(
        json.dumps(all_pair_results, indent=2)
    )
    (out_dir / "context_params.json").write_text(
        json.dumps(context_results, indent=2)
    )
    log.info("Saved all_pairs.json and context_params.json to %s", out_dir)

    _print_summary(context_results, all_pair_results)
    return context_results


def _print_summary(ctx_results: dict, pair_results: dict) -> None:
    sep = "=" * 70
    print(sep)
    print("  10hb BUNDLE INTER-HELIX STIFFNESS PARAMETERS")
    print(sep)
    for ctx in sorted(ctx_results):
        r = ctx_results[ctx]
        K = r["stiffness_diagonal"]
        print(f"\n  Context {ctx} ({r['n_pairs']} pairs, {r['n_frames_total']} frames):")
        print(f"    d(center-center) = {r['q_mean_physical']['center_to_center_dist_A']:.2f} Å")
        print(f"    lateral sep      = {r['q_mean_physical']['lateral_sep_A']:.2f} Å")
        print(f"    tilt angle       = {r['q_mean_physical']['tilt_angle_deg']:.2f}°")
        print(f"    K [kJ/mol/Å²]:   q0={K[0]:.4f}  q1={K[1]:.4f}  q2={K[2]:.4f}")
        print(f"    K [kJ/mol/rad²]: q3={K[3]:.4f}  q4={K[4]:.4f}  q5={K[5]:.4f}")
        print(f"    ESS:             {[f'{e:.0f}' for e in r['ess_per_dof']]}")
    print(sep)


def main():
    import argparse
    _default_design = Path(__file__).parent.parent.parent / "workspace" / "10hb.nadoc"
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-dir", required=True,
                        help="GROMACS run directory (must contain input_nadoc.pdb)")
    parser.add_argument("--design", default=str(_default_design),
                        help=f"Path to .nadoc design file (default: {_default_design})")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory for JSON files (default: same as --run-dir)")
    parser.add_argument("--skip", type=int, default=5,
                        help="Load every Nth frame (default 5 = 0.5 ns at 100 ps/frame)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir

    extract_bundle_params(
        run_dir=run_dir,
        out_dir=out_dir,
        design_path=Path(args.design),
        skip_frames=args.skip,
    )


if __name__ == "__main__":
    main()
