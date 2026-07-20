#!/usr/bin/env python3
"""On-pod crossover 6x6 worker — process ALL frames of the volume-local 2xT DCD, return only the tiny
6x6 (transfer to home is ~0.9 MB/s, so we compute on the pod). Uses the Curves+-calibrated Kabsch
extractor. numpy only: needs dcd_fast.py + snupi_step_params.py + kabsch_frame_test.py + the recipe npz
(built locally with the backend) in the same dir. Prints the D matrix + diagnostics as JSON."""
import sys, json, numpy as np
sys.path.insert(0, ".")
from dcd_fast import read_layout, read_frame
import snupi_step_params as S
import kabsch_frame_test as KF


def main():
    dcd, recipe = sys.argv[1:3]
    start = int(sys.argv[3]) if len(sys.argv) > 3 else 375     # post-eq start frame
    z = np.load(recipe)
    c1_a, c1_b, xsteps = z["c1_a"], z["c1_b"], z["xsteps"]
    ka = {k: z[k] for k in z.files if k.startswith(("a_", "b_"))}
    lay = read_layout(dcd)
    i, j = xsteps[:, 0], xsteps[:, 1]
    ref = np.asarray(read_frame(dcd, lay, lay.n_frames - 5)[0], float)
    o_ref, R_ref = KF.bp_frames_kabsch(ref, c1_a, c1_b, ka)
    ax = S._unit(o_ref[j] - o_ref[i])
    up = np.tile(np.array([0., 0., 1.]), (len(xsteps), 1))
    alt = np.tile(np.array([0., 1., 0.]), (len(xsteps), 1))
    up = np.where((np.abs(np.sum(ax * up, 1)) > 0.9)[:, None], alt, up)
    p1 = S._unit(up - np.sum(up * ax, 1)[:, None] * ax)
    beam = np.stack([ax, p1, np.cross(ax, p1)], axis=-1)
    Bt = np.transpose(beam, (0, 2, 1))
    Rrel_ref = R_ref[j] @ np.transpose(R_ref[i], (0, 2, 1))
    nX = len(xsteps); mean = np.zeros((nX, 6)); M2 = np.zeros((nX, 6, 6)); cnt = 0
    for fi in range(start, lay.n_frames - 1):
        xyz = np.asarray(read_frame(dcd, lay, fi)[0], float)
        o, R = KF.bp_frames_kabsch(xyz, c1_a, c1_b, ka)
        q_t = np.einsum("sab,sb->sa", Bt, o[j] - o[i])
        Rrel = R[j] @ np.transpose(R[i], (0, 2, 1))
        dR = np.transpose(Rrel_ref, (0, 2, 1)) @ Rrel
        q_r = np.degrees(np.einsum("sab,sb->sa", Bt, S._log_rotvec(dR)))
        Q = np.concatenate([q_t, q_r], axis=1)
        cnt += 1; d = Q - mean; mean += d / cnt; d2 = Q - mean; M2 += np.einsum("si,sj->sij", d, d2)
    cov = M2 / (cnt - 1)
    S6 = np.array([0.1, 0.1, 0.1, np.pi/180, np.pi/180, np.pi/180]); KT = 4.142
    Cm = np.nanmean(cov, axis=0) * np.outer(S6, S6)
    K = KT * np.linalg.pinv(Cm); std = np.sqrt(np.diag(Cm))
    L = abs(np.nanmean(mean[:, 0])) * 0.1; D = K * L
    print(json.dumps({"D": D.tolist(), "diag": np.diag(D).round(2).tolist(),
                      "std": [std[0]*10, std[1]*10, std[2]*10,
                              np.degrees(std[3]), np.degrees(std[4]), np.degrees(std[5])],
                      "L": float(L), "n_frames": cnt, "n_xover": int(nX), "start": start}))


if __name__ == "__main__":
    main()
