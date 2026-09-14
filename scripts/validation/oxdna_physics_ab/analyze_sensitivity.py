"""Derived ANM strain and positional fluctuations from saved frames only."""

import json
import numpy as np
from ab_common import ROOT, frames

rows = json.loads((ROOT / "sensitivity.json").read_text())
for r in rows:
    if "error" in r:
        continue
    d = ROOT / "sensitivity_inputs" / r["prior"]
    p = np.array(
        [
            [float(v) for k, v in enumerate(line.split()) if k in [0, 1, 2]]
            for line in (d / "anm.par").read_text().splitlines()[1:]
        ]
    )
    i, j = p[:, 0].astype(int), p[:, 1].astype(int)
    rest = p[:, 2]
    _, a = frames(ROOT / "runs" / r["label"] / "trajectory.dat", r["particles"])
    a = a[len(a) // 2 :]
    strain = np.array(
        [
            np.sqrt(np.mean((np.linalg.norm(x[i, :3] - x[j, :3], axis=1) - rest) ** 2))
            * 0.8518
            for x in a
        ]
    )
    r["ANM_rms_extension_nm"] = float(strain.mean())
    tip = a[:, -1, :3] * 0.8518
    r["tip_position_mean_nm"] = tip.mean(axis=0).tolist()
    r["tip_position_covariance_nm2"] = np.cov(tip.T).tolist()
    tether = np.array(r["series"]["tether_length_nm"])
    r["tether_sd_second_half_nm"] = float(tether[len(tether) // 2 :].std(ddof=1))
    print(r["prior"], r["seed"], r["ANM_rms_extension_nm"], flush=True)
(ROOT / "sensitivity_diagnostics.json").write_text(
    json.dumps(
        [
            {k: v for k, v in r.items() if k not in ["series", "sample_steps"]}
            for r in rows
        ],
        indent=2,
    )
)
