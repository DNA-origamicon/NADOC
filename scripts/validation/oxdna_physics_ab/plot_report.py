"""Standalone scientific figure; replicate intervals are not trajectory-frame errors."""

from pathlib import Path
import json
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
data = json.loads(
    (REPO / "docs/validation/oxdna_physics_ab_2026-09-13.json").read_text()
)
if data.get("long_followup", {}).get("completed") != 18:
    raise SystemExit("Long follow-up not complete; final figure not generated")
plt.rcParams.update(
    {
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.fonttype": "none",
    }
)
fig, axes = plt.subplots(1, 2, figsize=(11, 4.1), layout="constrained")
colors = {"CPU": "#315c9e", "CUDA": "#bf5a26"}
arms = ["A_baseline", "B_current_K", "E_brownian_eps1"]
labels = ["Baseline Bussi", "Current-K Bussi", "Brownian / amplitude 1"]
for b, shift in [("CPU", -0.12), ("CUDA", 0.12)]:
    for i, arm in enumerate(arms):
        g = next(
            x
            for x in data["long_followup"]["groups"]
            if x["backend"] == b and x["arm"] == arm
        )
        v = g["means"]["DNA_trans_T"]
        lo, hi = v["ci"]
        axes[0].errorbar(
            i + shift,
            v["mean"],
            yerr=[[v["mean"] - lo], [hi - v["mean"]]],
            fmt="o",
            capsize=4,
            color=colors[b],
            label=b if i == 0 else None,
        )
        samples = [
            x["means"]["DNA_trans_T"]
            for x in data["long_followup"]["replicas"]
            if x["backend"] == b and x["arm"] == arm
        ]
        axes[0].scatter(
            np.full(3, i + shift) + [-0.03, 0, 0.03],
            samples,
            s=15,
            alpha=0.4,
            color=colors[b],
        )
axes[0].axhline(296, color="#444444", ls="--", lw=1, label="296 K target")
axes[0].set_xticks(range(3), labels, rotation=12)
axes[0].set_ylabel("DNA translational temperature (K)")
axes[0].set_title("Biotin-linked model: 1 million steps")
axes[0].legend(fontsize=8)
controls = data["additional_controls"]
xpos = np.arange(2)
for i, (metric, label, color) in enumerate(
    [
        ("CPU_GPU_force_error", "Force", "#315c9e"),
        ("CPU_GPU_torque_error", "Torque", "#bf5a26"),
    ]
):
    values = [
        max(
            x[metric]
            for x in controls
            if x["test"] == "average_parameter_file"
            and x["backend"] == "CUDA"
            and x["explicit"] == explicit
        )
        for explicit in [False, True]
    ]
    axes[1].bar(xpos + (i - 0.5) * 0.3, values, width=0.28, color=color, label=label)
axes[1].axhline(0.001, color="#444444", ls="--", lw=1, label="Predeclared tolerance")
axes[1].set_yscale("log")
axes[1].set_ylim(3e-5, 0.015)
axes[1].set_xticks(
    xpos, ["Default average parameters", "Explicit upstream average file"], rotation=12
)
axes[1].set_ylabel("Largest normalized CPU/GPU error")
axes[1].set_title("Ordinary DNA2: input-only consistency remedy")
axes[1].legend(fontsize=8)
fig.suptitle(
    "Numerical agreement and thermal sampling are separate checks", fontsize=13
)
fig.savefig(REPO / "docs/validation/oxdna_physics_ab_2026-09-13.svg")
print("Wrote standalone SVG; error bars: 95% intervals across three seed means")
