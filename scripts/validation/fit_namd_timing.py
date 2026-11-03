"""Replay the qualified geometry timing index; no engines or paid services run.

Run from the repository root with .venv/bin/python. Requires scipy for the
nonnegative fit. The output retains configuration hashes and correlated geometry
identities; leave-one-geometry-out spreads are not confidence intervals.
"""

import json, re, math, hashlib, statistics
from pathlib import Path
from scipy.optimize import nnls
import numpy as np
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--artifacts", type=Path, default=Path(".development-artifacts"))
parser.add_argument(
    "--output",
    type=Path,
    default=Path(".development-artifacts/namd-runtime-estimator-20261102/fit.json"),
)
args = parser.parse_args()
root = args.artifacts
rows = []
for r in json.loads(
    (root / "namd-script-scheduling-20261102/features.json").read_text()
)["rows"]:
    p = root / r["id"]
    conf = Path(r["configuration"])
    if not p.exists():
        continue
    logs = list(p.glob("run.log"))
    if not logs:
        continue
    text = logs[0].read_text()
    c = conf.read_text()
    opts = {
        s[0].lower(): s[1]
        for line in c.splitlines()
        if len(s := line.split()) >= 2 and not line.startswith("#")
    }
    ts = [
        float(x)
        for x in re.findall(r"TIMING:.*?Wall:\s*[\d.e+-]+,\s*([\d.e+-]+)/step", text)
    ]
    if len(ts) < 3:
        continue
    n = r["features"]["neighbor"]["atoms"]
    grid = r["features"]["pme"]["grid"]
    pair = float(opts.get("pairlistdist", 13.5))
    group = r["group"]
    mode = "minimization" if "minimize" in opts else r["mode"]
    threads = r["qualification"]["threads"]
    data = json.loads((p / "result.json").read_text())
    if (
        not data.get("completed")
        or data.get("errors")
        or not r["qualification"]["eligible"]
    ):
        continue
    steps = int(opts.get("minimize", opts.get("run", "0")))
    ms = statistics.median(ts[2:]) * 1000
    rows.append(
        dict(
            id=r["id"],
            group=group,
            mode=mode,
            threads=threads,
            atoms=n,
            grid=grid,
            pairlistdist=pair,
            margin=float(opts.get("margin", 0)),
            ms=ms,
            startup_s=max(0, data["elapsed_s"] - steps * ms / 1000),
            elapsed_s=data["elapsed_s"],
            steps=steps,
            config_sha256=hashlib.sha256(conf.read_bytes()).hexdigest(),
        )
    )
print("ROWS", len(rows))
models = []
for mode, threads in sorted(set((r["mode"], r["threads"]) for r in rows)):
    subset = [r for r in rows if (r["mode"], r["threads"]) == (mode, threads)]

    def x(r):
        g = math.prod(r["grid"])
        return [
            1,
            r["atoms"] / 1e6,
            r["atoms"] / 1e6 * (r["pairlistdist"] / 13.5) ** 3,
            g * math.log2(g) / 2e7,
        ]

    X = np.array([x(r) for r in subset])
    y = np.array([r["ms"] for r in subset])
    coef = nnls(X, y)[0]
    ratios = []
    for g in sorted(set(r["group"] for r in subset)):
        train = np.array([r["group"] != g for r in subset])
        if sum(train) < 3:
            continue
        co = nnls(X[train], y[train])[0]
        pred = X[~train] @ co
        ratios.extend((y[~train] / np.maximum(pred, 0.001)).tolist())
    print(
        mode,
        threads,
        len(subset),
        "coef",
        coef,
        "ratios",
        np.quantile(ratios, [0, 0.1, 0.5, 0.9, 1]) if ratios else None,
        "startup",
        np.quantile([r["startup_s"] for r in subset], [0.5, 0.9, 1]),
    )
    models.append(
        dict(
            mode=mode,
            threads=threads,
            coefficients=coef.tolist(),
            max_pme_points_per_atom=max(
                math.prod(r["grid"]) / r["atoms"] for r in subset
            ),
            max_grid_aspect=max(max(r["grid"]) / min(r["grid"]) for r in subset),
            count=len(subset),
            groups=len(set(r["group"] for r in subset)),
            atoms=[min(r["atoms"] for r in subset), max(r["atoms"] for r in subset)],
            ratio_range=[min(ratios), max(ratios)] if ratios else None,
            startup_s=statistics.median(r["startup_s"] for r in subset),
        )
    )
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(dict(rows=rows, models=models), indent=2))
