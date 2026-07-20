#!/usr/bin/env python3
"""Self-contained SNUPI-observable worker — runs LOCALLY or ON A BARE POD.

Reads a (still-growing) DCD INCREMENTALLY, computes the per-frame pooled |twist| & rise
over a precomputed step recipe, and persists the growing series in a small JSON state file
so each invocation only reads the NEW frames. Prints the full series as JSON on stdout.

Dependencies: numpy + dcd_fast.py (same directory). NO MDAnalysis, NO scipy, NO NADOC repo
— so it can be scp'd to a RunPod pod (which has numpy) and run over the pod-local DCD,
avoiding both the 100+ GB fetch and the network-volume read-after-write lag of an SFTP read.
"""
import sys, os, json, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dcd_fast import read_layout, read_frame


def step_twist_rise(coords_ang, steps):
    """Per-step helical twist(deg, signed) & rise(Ang); NaN for non-physical (nick/gap) steps."""
    a_i = coords_ang[steps[:, 0]]; b_i = coords_ang[steps[:, 1]]
    a_j = coords_ang[steps[:, 2]]; b_j = coords_ang[steps[:, 3]]
    m_i = 0.5 * (a_i + b_i); m_j = 0.5 * (a_j + b_j)
    y_i = a_i - b_i; y_j = a_j - b_j
    step_vec = m_j - m_i
    rise = np.linalg.norm(step_vec, axis=1)
    h = step_vec / np.where(rise[:, None] > 1e-9, rise[:, None], 1.0)
    yi_p = y_i - (np.sum(y_i * h, axis=1))[:, None] * h
    yj_p = y_j - (np.sum(y_j * h, axis=1))[:, None] * h
    ni = np.linalg.norm(yi_p, axis=1); nj = np.linalg.norm(yj_p, axis=1)
    ok = (ni > 1e-6) & (nj > 1e-6)
    yi_u = yi_p / np.where(ni[:, None] > 1e-9, ni[:, None], 1.0)
    yj_u = yj_p / np.where(nj[:, None] > 1e-9, nj[:, None], 1.0)
    cosang = np.clip(np.sum(yi_u * yj_u, axis=1), -1.0, 1.0)
    sign = np.sign(np.sum(np.cross(yi_u, yj_u) * h, axis=1))
    twist = np.degrees(np.arccos(cosang)) * np.where(sign == 0, 1.0, sign)
    valid = ok & (rise >= 2.0) & (rise <= 5.5)
    return np.where(valid, twist, np.nan), np.where(valid, rise, np.nan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcd", required=True)
    ap.add_argument("--recipe", required=True)     # .npy (M,4) int C1' atom indices
    ap.add_argument("--state", required=True)       # persisted series JSON
    ap.add_argument("--safe-back", type=int, default=2)
    a = ap.parse_args()
    steps = np.load(a.recipe)
    try:
        lay = read_layout(a.dcd)
    except Exception as e:
        print(json.dumps({"error": f"layout: {e}"})); return
    n_safe = max(0, lay.n_frames - a.safe_back)
    state = {"last": -1, "series": []}   # series row = [frame, twist_mean, twist_var, rise_mean, rise_var, n_steps]
    if os.path.exists(a.state):
        try: state = json.load(open(a.state))
        except Exception: pass
    for f in range(state["last"] + 1, n_safe):
        try:
            xyz, _cell = read_frame(a.dcd, lay, f)
        except IndexError:
            break
        tw, ri = step_twist_rise(np.asarray(xyz, dtype=np.float64), steps)
        m = np.isfinite(tw); twa = np.abs(tw[m]); ria = ri[m]
        if twa.size:
            state["series"].append([f, float(twa.mean()), float(twa.var()),
                                    float(ria.mean()), float(ria.var()), int(twa.size)])
        state["last"] = f
    json.dump(state, open(a.state, "w"))
    print(json.dumps({"dt_ps": lay.delta_ps, "n_frames": lay.n_frames,
                      "n_processed": len(state["series"]), "series": state["series"]}))


if __name__ == "__main__":
    main()
