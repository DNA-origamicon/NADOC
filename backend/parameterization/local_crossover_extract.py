"""
Local crossover parameter extraction from bundle trajectories.

Measures per-crossover junction geometry directly:
  - d_cc: C1'–C1' distance at the crossover bp position [Å]
  - theta_hj: Holliday junction dihedral angle [rad]

These are the quantities mrdna's HarmonicBond(k, r0) and HarmonicDihedral(k, t0)
represent — the inter-bead distance at the crossover node, NOT the mid-arm
centroid-to-centroid distance measured by param_extract.py.

WHY THIS APPROACH INSTEAD OF THE 2hb ISOLATED SYSTEM
-----------------------------------------------------
The 2hb inter-arm extraction (param_extract.py) has autocorrelation times of
~11 ns because the unconstrained arm can fluctuate slowly. Getting ESS=100
requires ~2–4 µs — impractical.

In a bundle:
  - Multiple crossovers provide independent samples at the same time
  - The bundle constrains local fluctuations → shorter τ (~1–2 ns, same as
    the inter-helix DOFs measured in 10hb)
  - With N crossovers × N_frames / (2τ) the pooled ESS is much higher

The local d_cc measurement is also physically more appropriate: mrdna's crossover
spring connects two beads at the crossover position; r0 should be the distance
between those beads (~18–22 Å), not the mid-arm distance (~24 Å).

LIMITATIONS
-----------
- k_bond from this extraction reflects the crossover in the bundle context.
  For T=0 this is fine. For variants with extra bases, the isolated geometry
  is slightly different — use the 2hb T1/T2 trajectories for those.
- HJ dihedral estimation uses a 4-C1' dihedral at the junction. Direction
  assignment is based on bp_index ordering within each helix (may differ
  for scaffold vs staple crossovers).
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

log = logging.getLogger(__name__)

_kT_kJ_MOL = 2.5788   # kJ/mol at 310 K


# ── Residue index map ─────────────────────────────────────────────────────────

def _build_c1p_map(
    u,
    design: Design,
    pdb_path: Path,
) -> dict[tuple[str, int, str], int]:
    """
    Map (helix_id, bp_idx, direction) → MDAnalysis residue index.

    The `direction` key ("FORWARD" or "REVERSE") distinguishes the two strands
    (scaffold vs staple) at the same bp position. This is required for crossover
    extraction: we must select the CROSSING strand's C1', not any strand.
    """
    model = build_atomistic_model(design)
    cmap  = build_chain_map(model)
    p_order = build_p_gro_order(pdb_path.read_text(), cmap)

    sel_str = "name P and resname " + " ".join(sorted(_GRO_DNA_RESNAMES))
    p_atoms = u.select_atoms(sel_str)

    if len(p_atoms) != len(p_order):
        raise ValueError(
            f"P atom count mismatch: GROMACS has {len(p_atoms)}, "
            f"p_order has {len(p_order)}."
        )

    c1p_map: dict[tuple[str, int, str], int] = {}
    for pa, (helix_id, bp_index, direction) in zip(p_atoms, p_order):
        rix = pa.residue.ix
        if pa.residue.atoms.select_atoms("name C1'").n_atoms > 0:
            c1p_map[(helix_id, bp_index, direction)] = rix
    return c1p_map


def _bp_center(u, c1p_map, helix_id: str, bp_idx: int) -> "np.ndarray | None":
    """
    Estimate the base-pair center on a given helix at a given bp position.

    Averages the C1' positions of both strands (FORWARD + REVERSE) at the bp.
    This approximates the local helix axis position, which is what mrdna's bead
    represents. If only one strand is available, returns that strand's C1'.
    Returns None if neither strand has a mapped residue.
    """
    pos_fwd = None
    pos_rev = None
    for direction in ("FORWARD", "REVERSE"):
        rix = c1p_map.get((helix_id, bp_idx, direction))
        if rix is None:
            continue
        ag = u.residues[rix].atoms.select_atoms("name C1'")
        if len(ag) > 0:
            if direction == "FORWARD":
                pos_fwd = ag.positions[0]
            else:
                pos_rev = ag.positions[0]

    if pos_fwd is not None and pos_rev is not None:
        return 0.5 * (pos_fwd + pos_rev)
    elif pos_fwd is not None:
        return pos_fwd
    elif pos_rev is not None:
        return pos_rev
    return None


# ── 4-atom dihedral ───────────────────────────────────────────────────────────

def _dihedral(p1, p2, p3, p4) -> float:
    """IUPAC dihedral angle (radians) from 4 Cartesian positions."""
    b1 = p2 - p1
    b2 = p3 - p2
    b3 = p4 - p3

    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    norm_n1 = np.linalg.norm(n1)
    norm_n2 = np.linalg.norm(n2)
    if norm_n1 < 1e-8 or norm_n2 < 1e-8:
        return 0.0

    n1 /= norm_n1
    n2 /= norm_n2
    m1 = np.cross(n1, b2 / (np.linalg.norm(b2) + 1e-10))
    cos_a = np.clip(np.dot(n1, n2), -1.0, 1.0)
    sin_a = np.dot(m1, n2)
    return float(np.arctan2(sin_a, cos_a))


# ── ESS (first-lag estimate) ──────────────────────────────────────────────────

def _ess_1d(x: np.ndarray) -> float:
    n = len(x)
    c = x - x.mean()
    var = float(np.dot(c, c)) / n
    if var < 1e-20:
        return float(n)
    rho1 = float(np.dot(c[:-1], c[1:])) / (n * var)
    tau = 1.0 + 2.0 * max(0.0, rho1)
    return float(n) / tau


# ── Main extraction function ──────────────────────────────────────────────────

def extract_local_crossover_params(
    run_dir: Path,
    design: Design,
    pdb_path: Path,
    extra_bases_filter: str | None = None,
    skip: int = 5,
) -> dict:
    """
    Extract per-crossover local geometry from a bundle production trajectory.

    Parameters
    ----------
    run_dir : Path
        GROMACS run directory containing npt.gro and prod.xtc (or prod_best.part*.xtc).
    design : Design
        NADOC design object (used for crossover list and topology mapping).
    pdb_path : Path
        input_nadoc.pdb used to set up the GROMACS run (for P-atom topology order).
    extra_bases_filter : str | None
        If given, only process crossovers where xo.extra_bases == extra_bases_filter.
        Use None to process all crossovers.
    skip : int
        Load every Nth frame (default 5 = 500 ps at 100 ps output).

    Returns
    -------
    dict with keys:
        mrdna_params : dict with r0_ang, k_bond_kJ_mol_ang2, hj_equilibrium_angle_deg,
                       k_dihedral_kJ_mol_rad2, n_crossovers, pooled_ESS_d, pooled_ESS_theta
        per_crossover : list of per-crossover dicts (for diagnostics)
        crossover_type : str (e.g. "T0", "T1")
        n_frames : int
        converged : bool
        convergence_warnings : list[str]
    """
    import MDAnalysis as mda

    # ── Locate trajectory ────────────────────────────────────────────────────
    gro = run_dir / "npt.gro"
    if not gro.exists():
        raise FileNotFoundError(f"npt.gro not found in {run_dir}")

    # Prefer production parts over view_whole.xtc
    parts = sorted((run_dir).glob("prod_best.part*.xtc"))
    xtc = parts[-1] if parts else run_dir / "prod.xtc"
    if not xtc.exists():
        raise FileNotFoundError(f"No production XTC found in {run_dir}")

    log.info("Loading trajectory: %s + %s", gro, xtc)
    u = mda.Universe(str(gro), str(xtc))
    log.info("  %d frames at dt=%.1f ps", u.trajectory.n_frames, u.trajectory.dt)

    # ── Build residue map ────────────────────────────────────────────────────
    c1p_map = _build_c1p_map(u, design, pdb_path)
    log.info("C1' map: %d positions", len(c1p_map))

    # ── Collect crossovers to measure ────────────────────────────────────────
    # For each crossover, pre-build atom groups for BOTH strands at the crossover
    # bp on each helix. The bp center (average of both C1' positions) approximates
    # the local helix axis, which is what mrdna's bead represents.
    def _c1p_ag(helix_id: str, bp_idx: int, direction: str):
        rix = c1p_map.get((helix_id, bp_idx, direction))
        if rix is None:
            return None
        ag = u.residues[rix].atoms.select_atoms("name C1'")
        return ag if len(ag) > 0 else None

    crossovers_to_measure = []
    for xo in design.crossovers:
        eb = xo.extra_bases or ""
        if extra_bases_filter is not None and eb != extra_bases_filter:
            continue
        bp_a = xo.half_a.index
        bp_b = xo.half_b.index
        h_a  = xo.half_a.helix_id
        h_b  = xo.half_b.helix_id

        # Both strands at each bp position — needed for bp-center computation
        ag_a_fwd = _c1p_ag(h_a, bp_a, "FORWARD")
        ag_a_rev = _c1p_ag(h_a, bp_a, "REVERSE")
        ag_b_fwd = _c1p_ag(h_b, bp_b, "FORWARD")
        ag_b_rev = _c1p_ag(h_b, bp_b, "REVERSE")

        if (ag_a_fwd is None and ag_a_rev is None) or (ag_b_fwd is None and ag_b_rev is None):
            log.debug("Crossover %s@%d – %s@%d: no C1' atoms on one side, skipping",
                      h_a, bp_a, h_b, bp_b)
            continue

        # Dihedral: use crossing-strand neighbors (prev on half_a, next on half_b)
        dir_a = xo.half_a.strand.value
        dir_b = xo.half_b.strand.value
        flank_a = _c1p_ag(h_a, bp_a - 1, dir_a) or _c1p_ag(h_a, bp_a + 1, dir_a)
        flank_b = _c1p_ag(h_b, bp_b + 1, dir_b) or _c1p_ag(h_b, bp_b - 1, dir_b)

        crossovers_to_measure.append({
            "label": f"{h_a}@{bp_a}–{h_b}@{bp_b}",
            "extra_bases": eb,
            "ag_a_fwd": ag_a_fwd, "ag_a_rev": ag_a_rev,
            "ag_b_fwd": ag_b_fwd, "ag_b_rev": ag_b_rev,
            "flank_a": flank_a,   "flank_b": flank_b,
        })

    log.info("Crossovers to measure: %d", len(crossovers_to_measure))
    if not crossovers_to_measure:
        raise ValueError("No crossovers matched the filter criteria.")

    # ── Trajectory loop ───────────────────────────────────────────────────────
    def _center(ag_fwd, ag_rev) -> np.ndarray:
        """bp center = average of available strand C1' positions."""
        pts = []
        if ag_fwd is not None: pts.append(ag_fwd.positions[0])
        if ag_rev is not None: pts.append(ag_rev.positions[0])
        return np.mean(pts, axis=0)

    n_xo = len(crossovers_to_measure)
    d_lists: list[list[float]] = [[] for _ in range(n_xo)]
    theta_lists: list[list[float]] = [[] for _ in range(n_xo)]
    has_dihedral = [
        (xoi["flank_a"] is not None and xoi["flank_b"] is not None)
        for xoi in crossovers_to_measure
    ]

    for ts in u.trajectory[::skip]:
        for i, xoi in enumerate(crossovers_to_measure):
            center_a = _center(xoi["ag_a_fwd"], xoi["ag_a_rev"])
            center_b = _center(xoi["ag_b_fwd"], xoi["ag_b_rev"])
            d_lists[i].append(float(np.linalg.norm(center_a - center_b)))

            if has_dihedral[i]:
                pf_a = xoi["flank_a"].positions[0]
                # Use the crossing-strand C1' (not center) for dihedral flanks
                dir_a = xo.half_a.strand.value if False else None  # placeholder
                # Use center_a as the junction point for dihedral
                pf_b = xoi["flank_b"].positions[0]
                theta_lists[i].append(_dihedral(pf_a, center_a, center_b, pf_b))

    n_frames = len(d_lists[0])
    log.info("Extracted %d frames for %d crossovers", n_frames, n_xo)

    # ── Per-crossover statistics ──────────────────────────────────────────────
    per_xo = []
    all_d = []
    all_theta = []
    for i, xoi in enumerate(crossovers_to_measure):
        d = np.array(d_lists[i])
        all_d.append(d)
        ess_d = _ess_1d(d)
        k_d = _kT_kJ_MOL / np.var(d, ddof=1) if np.var(d) > 1e-10 else float("inf")

        entry: dict = {
            "label": xoi["label"],
            "extra_bases": xoi["extra_bases"],
            "d_mean_A": float(d.mean()),
            "d_std_A": float(d.std(ddof=1)),
            "k_bond_kJ_mol_ang2": float(k_d),
            "ESS_d": float(ess_d),
        }

        if has_dihedral[i] and len(theta_lists[i]) > 0:
            theta = np.array(theta_lists[i])
            all_theta.append(theta)
            ess_theta = _ess_1d(theta)
            k_theta = _kT_kJ_MOL / np.var(theta, ddof=1) if np.var(theta) > 1e-10 else float("inf")
            entry.update({
                "theta_mean_deg": float(np.degrees(theta.mean())),
                "theta_std_deg": float(np.degrees(theta.std(ddof=1))),
                "k_dihedral_kJ_mol_rad2": float(k_theta),
                "ESS_theta": float(ess_theta),
            })

        per_xo.append(entry)

    # ── Pooled statistics ─────────────────────────────────────────────────────
    D = np.concatenate(all_d)         # all crossover d values pooled
    r0_pooled = float(D.mean())
    k_bond_pooled = float(_kT_kJ_MOL / np.var(D, ddof=1))
    # Pooled ESS: sum of per-crossover ESS (independent crossovers)
    pooled_ess_d = float(sum(e["ESS_d"] for e in per_xo))

    theta_mean_deg = None
    k_dihedral_pooled = None
    pooled_ess_theta = None
    if all_theta:
        THETA = np.concatenate(all_theta)
        theta_mean_deg = float(np.degrees(THETA.mean()))
        k_dihedral_pooled = float(_kT_kJ_MOL / np.var(THETA, ddof=1))
        pooled_ess_theta = float(sum(e.get("ESS_theta", 0.0) for e in per_xo if "ESS_theta" in e))

    # ── Convergence check ─────────────────────────────────────────────────────
    warnings: list[str] = []
    if pooled_ess_d < 200:
        warnings.append(f"Pooled ESS_d = {pooled_ess_d:.0f} < 200 — extend run or add crossovers.")
    if pooled_ess_theta is not None and pooled_ess_theta < 200:
        warnings.append(f"Pooled ESS_theta = {pooled_ess_theta:.0f} < 200.")
    if n_frames < 100:
        warnings.append(f"Only {n_frames} frames — need ≥ 100.")
    converged = len(warnings) == 0

    # ── Filter out helix-terminal / scaffold-routing crossovers ──────────────
    # Crossovers near helix ends (bp ≤ 0 or bp ≥ max_bp) have large d_std due
    # to helix-end flexibility and scaffold-routing geometry. Exclude them from
    # the pooled statistics used for mrdna injection. "Interior" = both bp
    # indices strictly between 0 and the max bp in their helix.
    interior_indices = []
    for i, xoi in enumerate(crossovers_to_measure):
        bps = [int(xoi["label"].split("@")[1].split("–")[0]),
               int(xoi["label"].split("@")[2])]
        # Skip if any bp is at or beyond the helix boundary (0 or max)
        # We use bp > 0 and bp < 41 as a conservative filter for 10hb (42 bp helices)
        if all(1 <= bp <= 40 for bp in bps):
            interior_indices.append(i)

    interior_per_xo = [per_xo[i] for i in interior_indices]
    n_interior = len(interior_per_xo)

    if n_interior > 0:
        D_int = np.concatenate([all_d[i] for i in interior_indices])
        r0_interior = float(D_int.mean())
        k_bond_interior = float(_kT_kJ_MOL / np.var(D_int, ddof=1))
        pooled_ess_interior = float(sum(per_xo[i]["ESS_d"] for i in interior_indices))
    else:
        r0_interior, k_bond_interior, pooled_ess_interior = r0_pooled, k_bond_pooled, pooled_ess_d

    # ── Determine crossover type label ────────────────────────────────────────
    eb_set = {xo["extra_bases"] for xo in crossovers_to_measure}
    if eb_set == {""}:
        xover_type = "T0"
    elif len(eb_set) == 1:
        t_count = len(next(iter(eb_set)))
        xover_type = f"T{t_count}"
    else:
        xover_type = "mixed"

    mrdna_params: dict = {
        "r0_ang": r0_interior,
        "r0_all_crossovers_ang": r0_pooled,
        "k_bond_kJ_mol_ang2": k_bond_interior,
        "n_crossovers": n_xo,
        "n_interior_crossovers": n_interior,
        "pooled_ESS_d": pooled_ess_interior,
        "note": (
            "r0 and k_bond from interior DX crossovers (bp 1-40) only. "
            "Helix-terminal and scaffold-routing crossovers excluded. "
            "k_bond is context-dependent; see per_crossover for breakdown."
        ),
    }
    if theta_mean_deg is not None:
        mrdna_params["hj_equilibrium_angle_deg"] = theta_mean_deg
        mrdna_params["hj_equilibrium_angle_rad"] = float(np.radians(theta_mean_deg))
        mrdna_params["k_dihedral_kJ_mol_rad2"] = k_dihedral_pooled
        mrdna_params["pooled_ESS_theta"] = pooled_ess_theta

    return {
        "crossover_type": xover_type,
        "mrdna_params": mrdna_params,
        "per_crossover": per_xo,
        "n_frames": n_frames,
        "converged": converged,
        "convergence_warnings": warnings,
    }
