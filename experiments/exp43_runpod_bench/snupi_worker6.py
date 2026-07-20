#!/usr/bin/env python3
"""Full per-motif 6-DOF SNUPI-observable worker — numpy only, on-pod portable.

Reads a growing DCD INCREMENTALLY and, per frame, computes for TWO motif classes:
  * duplex (regular_bp): the 6 bp-step params {shift,slide,rise,tilt,roll,twist} over the clean
    intra-helix steps  (frame_step_params);
  * extra-base crossover: the SNUPI-convention cross-helix 6-DOF + interhelical θ (crossover_params).
For each it emits the per-frame spatial MEAN (6) and spatial COVARIANCE (upper-tri 6x6 = 21). The
watcher accumulates these over frames into the ensemble covariance (law of total covariance) and
gates on the convergence of its eigenvalues — SNUPI's stiffness is k = kB·T·Cov⁻¹, couplings included.

Deps: numpy + dcd_fast.py + snupi_step_params.py (its recipe builders import MDAnalysis lazily and are
NOT called here — only the pure-numpy frame_step_params/crossover_params are). Recipe .npz is built
locally and uploaded.
"""
import sys, os, json, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dcd_fast import read_layout, read_frame
import snupi_step_params as S

_UT = np.triu_indices(6)   # 21 upper-triangular indices of a 6x6


def _mean_cov(P):
    """P (n,6) finite rows -> (mean(6), upper-tri cov(21), n). Returns None if too few rows."""
    m = np.all(np.isfinite(P), axis=1)
    P = P[m]
    if len(P) < 8:
        return None
    C = np.cov(P.T)                       # (6,6)
    return P.mean(axis=0), C[_UT], len(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcd", required=True)
    ap.add_argument("--recipe", required=True)     # .npz with dup_* and xo_* arrays
    ap.add_argument("--state", required=True)
    ap.add_argument("--safe-back", type=int, default=2)
    a = ap.parse_args()
    z = np.load(a.recipe)
    c1_a, c1_b, window = z["c1_a"], z["c1_b"], z["window"]
    dup_steps, xo_steps, beam = z["dup_steps"], z["xo_steps"], z["beam"]
    has_xo = len(xo_steps) > 0
    try:
        lay = read_layout(a.dcd)
    except Exception as e:
        print(json.dumps({"error": f"layout: {e}"})); return
    n_safe = max(0, lay.n_frames - a.safe_back)
    state = {"last": -1, "series": []}
    if os.path.exists(a.state):
        try: state = json.load(open(a.state))
        except Exception: pass
    for f in range(state["last"] + 1, n_safe):
        try:
            xyz, _ = read_frame(a.dcd, lay, f)
        except IndexError:
            break
        xyz = np.asarray(xyz, dtype=np.float64)
        row = {"f": f}
        o, R = S.bp_frames_h(xyz, c1_a, c1_b, window)     # helix-axis frames, computed once
        dP = S.step_params(o, R, dup_steps)
        r = _mean_cov(dP)
        if r is not None:
            row["dm"], row["dc"], row["dn"] = r[0].tolist(), r[1].tolist(), r[2]
        if has_xo:
            Q = S.crossover_params(o, R, xo_steps, beam)  # (Sx,7): 6-DOF + theta
            r = _mean_cov(Q[:, :6])
            if r is not None:
                row["xm"], row["xc"], row["xn"] = r[0].tolist(), r[1].tolist(), r[2]
                th = Q[:, 6]; th = th[np.isfinite(th)]
                row["th_m"], row["th_v"] = float(th.mean()), float(th.var())
        if "dm" in row or "xm" in row:
            state["series"].append(row)
        state["last"] = f
    json.dump(state, open(a.state, "w"))
    print(json.dumps({"dt_ps": lay.delta_ps, "n_frames": lay.n_frames,
                      "n_processed": len(state["series"]), "series": state["series"]}))


if __name__ == "__main__":
    main()
