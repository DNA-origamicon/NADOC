#!/usr/bin/env python3
"""SNUPI/CanDo BP–BP cross-correlation matrix (DCCM) vs MD — the G7 validation observable.

SNUPI's SECOND validation channel (SI S11): beyond the per-bp RMSF *magnitude*, compare the
*shape of motion* — the bp-to-bp displacement-correlation matrix — between the FE model and MD.

FE side: ``fem_solver.compute_correlation_matrix`` (the free-free NMA modes → Pearson DCCM),
for material="snupi" and material="cando".
MD side: per-frame Kabsch-aligned bp-center (mean of both strands' C1') positions from the free
k=0 DCD → the sample displacement-correlation matrix.
Agreement = Pearson of the off-diagonal upper-triangle entries (matched by (helix,bp)), a single
number in [−1,1]; higher snupi→MD than cando→MD = SNUPI captures the motion topology better.

Reuses the exp42 design battery (only the two designs with an on-disk free-k0 DCD). DCDs are
local-only (gitignored) — this is a documented analysis, not a CI pin. Writes
experiments/exp42_snupi_cross_compare/dccm.json.

Usage:  uv run python scripts/snupi_dccm_compare.py [--only 6hbx100_noT,3x4SQ] [--max-frames 150]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.core.models import Design                              # noqa: E402
from backend.physics.fem_solver import (                           # noqa: E402
    assemble_global_stiffness, assemble_mass_matrix, build_fem_mesh,
    compute_correlation_matrix,
)
from scripts.snupi_cross_compare import BATTERY, WS, OUT_DIR       # noqa: E402


def _fe_dccm(design: Design, material: str):
    """(node_keys, DCCM) for the material's free-free NMA. node_keys = [(helix_id, global_bp)]."""
    mesh = build_fem_mesh(design)
    K, _ = assemble_global_stiffness(mesh, material=material, bp_registered_frame=True)
    M = assemble_mass_matrix(mesh, design) if material == "snupi" else None
    C = compute_correlation_matrix(K, len(mesh.nodes), M=M)
    keys = [(n.helix_id, int(n.global_bp)) for n in mesh.nodes]
    return keys, C


def _md_dccm(entry: dict, max_frames: int):
    """(keys, DCCM) of MD bp-center fluctuations from the free k=0 DCD, or (None, None)."""
    from backend.core.md_trajectory import (
        _build_md_nadoc_ctx, _extract_md_nadoc_frame, _stride_pick)

    md = entry["md"]
    jd = WS / "md_jobs" / md["job"]
    pkg = next((jd / "package").glob("*/"), None)
    if pkg is None:
        return None, None
    psf = pkg / f"{md['stem']}.psf"
    ref_pdb = pkg / f"{md['stem']}.pdb"
    dcd = pkg / "output" / md["dcd"]
    if not (psf.exists() and ref_pdb.exists() and dcd.exists()):
        print(f"    [md] missing topology/dcd for {entry['name']}")
        return None, None
    design = (Design.model_validate_json((jd / "design.json").read_text())
              if md["design_json"] else Design.model_validate_json((WS / entry["nadoc"]).read_text()))
    ctx = _build_md_nadoc_ctx(str(psf), [str(dcd)], str(ref_pdb), design, with_termini=False)
    p_order = ctx["p_order"]
    n = ctx["n_frames"]
    if n <= 0 or not p_order:
        return None, None
    idxs = list(range(n)) if n <= max_frames else _stride_pick(list(range(n)), max_frames)

    # bp-center = mean of FORWARD+REVERSE C1' at each (helix,bp); keep bps present on BOTH strands.
    per_bp: dict[tuple, dict[str, int]] = {}
    for i, (hid, bp, direction) in enumerate(p_order):
        per_bp.setdefault((hid, int(bp)), {})[direction] = i
    bp_keys = [k for k, dd in per_bp.items() if len(dd) >= 2]
    if len(bp_keys) < 3:
        return None, None
    pairs = [(per_bp[k][list(per_bp[k])[0]], per_bp[k][list(per_bp[k])[1]]) for k in bp_keys]
    fi = np.array([a for a, _ in pairs]); ri = np.array([b for _, b in pairs])

    m = len(bp_keys)
    sum_p = np.zeros((m, 3)); sum_outer = np.zeros((m, m)); used = 0
    for gidx in idxs:
        out = _extract_md_nadoc_frame(ctx, gidx, with_c1p=True, with_termini=False)
        c1p = out[2] if out is not None else None
        if c1p is None or len(c1p) != len(p_order):
            continue
        cen = 0.5 * (c1p[fi] + c1p[ri])       # (m,3) bp-centers this frame
        flat = cen.reshape(-1)
        sum_p += cen
        sum_outer += (cen @ cen.T)            # <r_i·r_j> accumulation (dot over xyz)
        used += 1
    if used < 3:
        return None, None
    mean_p = sum_p / used
    cov = sum_outer / used - (mean_p @ mean_p.T)     # <Δr_i·Δr_j>
    d = np.sqrt(np.clip(np.diag(cov), 1e-30, None))
    C = np.clip(cov / np.outer(d, d), -1.0, 1.0)
    return bp_keys, C


def _agree(keys_a, A, keys_b, B) -> dict:
    """Pearson of the off-diagonal upper-triangle DCCM entries on the common (helix,bp) set."""
    idx_b = {k: i for i, k in enumerate(keys_b)}
    common = [k for k in keys_a if k in idx_b]
    if len(common) < 4:
        return {"n": len(common), "pearson": None}
    ia = np.array([keys_a.index(k) for k in common])
    ib = np.array([idx_b[k] for k in common])
    Aa = A[np.ix_(ia, ia)]; Bb = B[np.ix_(ib, ib)]
    iu = np.triu_indices(len(common), k=1)
    a, b = Aa[iu], Bb[iu]
    if a.std() < 1e-9 or b.std() < 1e-9:
        return {"n": len(common), "pearson": None}
    return {"n": len(common), "pearson": round(float(np.corrcoef(a, b)[0, 1]), 4)}


def _dynamics_channel(design: Design, md_keys, C_md, dyn_steps: int) -> dict:
    """The Langevin-dynamics channel (project_snupi_dynamics Phase 3): (1) the dynamics-trajectory
    equal-time DCCM vs MD — should match the snupi-NMA→MD agreement, since the equilibrium DCCM is
    friction-independent (it re-derives the same k_BT·K⁻¹ from an actual trajectory); (2) the breathing
    mode (PCA of the trajectory) and its relaxation TIME under diagonal-Stokes vs full-RPY friction —
    the KINETIC quantity static NMA cannot provide at all, and the concrete thing hydrodynamics buys.
    """
    from backend.physics import snupi_dynamics as sd

    mesh = build_fem_mesh(design)
    keys = [(n.helix_id, int(n.global_bp)) for n in mesh.nodes]
    kw = dict(material="snupi", n_steps=dyn_steps, n_equil=dyn_steps // 6,
              sample_every=20, seed=7)
    stk = sd.simulate_equilibrium(design, hydrodynamics=False, **kw)
    C_dyn = sd.dynamics_dccm(stk["frames"], stk["positions0"])
    out = {"dyn_dccm_vs_md": _agree(keys, C_dyn, md_keys, C_md)}

    # breathing mode (from the Stokes run) + its relaxation time under both frictions
    N = stk["frames"].shape[1]
    node_mass = stk["mass_diag"].reshape(N, 6)[:, 0]
    pca0 = sd.breathing_mode_pca(stk["frames"], stk["positions0"], node_mass, n_modes=1)["modes"][0]
    mode = pca0["shape"]
    tau_s = sd.mode_autocorr_time_ns(
        sd.mode_coordinate(stk["frames"], stk["positions0"], mode), stk["dt_ns"] * kw["sample_every"])
    rpy = sd.simulate_equilibrium(design, hydrodynamics=True, **kw)
    tau_r = sd.mode_autocorr_time_ns(
        sd.mode_coordinate(rpy["frames"], rpy["positions0"], mode), rpy["dt_ns"] * kw["sample_every"])
    out["breathing"] = {
        "amplitude_nm": round(pca0["amplitude_nm"], 4),
        "freq_GHz": round(pca0["freq_GHz"], 4),
        "k_eff_pN_per_nm": round(pca0["k_eff_pN_per_nm"], 4),
        "tau_stokes_ns": round(tau_s, 5),
        "tau_rpy_ns": round(tau_r, 5),
        "tau_ratio_stokes_over_rpy": round(tau_s / tau_r, 3) if tau_r > 0 else None,
    }
    return out


def run(entry: dict, max_frames: int, dynamics: bool = False, dyn_steps: int = 80000) -> dict:
    name = entry["name"]
    print(f"[{name}] FE DCCM (snupi/cando) + MD DCCM …")
    design = Design.model_validate_json((WS / entry["nadoc"]).read_text())
    ks_s, C_s = _fe_dccm(design, "snupi")
    ks_c, C_c = _fe_dccm(design, "cando")
    md_keys, C_md = _md_dccm(entry, max_frames)
    out = {"design": name, "lattice": entry["lattice"], "n_fe_nodes": len(ks_s)}
    if C_md is None:
        out["error"] = "no MD DCCM"
        print("    SKIP: no MD DCCM")
        return out
    out["dccm_vs_md"] = {
        "snupi": _agree(ks_s, C_s, md_keys, C_md),
        "cando": _agree(ks_c, C_c, md_keys, C_md),
    }
    print(f"    snupi→MD {out['dccm_vs_md']['snupi']}  cando→MD {out['dccm_vs_md']['cando']}")
    if dynamics:
        print(f"    dynamics channel (Langevin {dyn_steps} steps, Stokes + RPY) …")
        dc = _dynamics_channel(design, md_keys, C_md, dyn_steps)
        out["dynamics"] = dc
        br = dc["breathing"]
        print(f"    dyn-DCCM→MD {dc['dyn_dccm_vs_md']}  breathing f={br['freq_GHz']} GHz  "
              f"τ_stokes={br['tau_stokes_ns']} ns  τ_rpy={br['tau_rpy_ns']} ns  "
              f"(RPY speedup ×{br['tau_ratio_stokes_over_rpy']})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="6hbx100_noT,3x4SQ")
    ap.add_argument("--max-frames", type=int, default=150)
    ap.add_argument("--dynamics", action="store_true",
                    help="add the Langevin-dynamics channel: dynamics-DCCM vs MD + breathing-mode "
                         "relaxation time under Stokes vs RPY friction (the hydrodynamics payoff)")
    ap.add_argument("--dyn-steps", type=int, default=80000)
    args = ap.parse_args()
    want = {s.strip() for s in args.only.split(",")}
    battery = [e for e in BATTERY if e["name"] in want and e.get("md")]

    results = [run(e, args.max_frames, dynamics=args.dynamics, dyn_steps=args.dyn_steps)
               for e in battery]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "dccm.json").write_text(json.dumps({"results": results}, indent=2))

    print("\n" + "=" * 70)
    print(f"{'design':<15}{'DCCM pearson vs MD  cando / snupi':<40}")
    print("-" * 70)
    for r in results:
        if r.get("error"):
            print(f"{r['design']:<15}SKIP ({r['error']})"); continue
        ag = r["dccm_vs_md"]
        print(f"{r['design']:<15}{ag['cando'].get('pearson')} / {ag['snupi'].get('pearson')}")
    print("=" * 70)
    print(f"full JSON → {OUT_DIR / 'dccm.json'}")


if __name__ == "__main__":
    main()
