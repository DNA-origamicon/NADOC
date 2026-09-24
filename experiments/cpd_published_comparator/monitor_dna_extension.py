"""Refresh extension diagnostics and the saved UI snapshot at block boundaries."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np


def assess(root):
    state = json.loads((root / "status.json").read_text())
    groups = {}
    for record in state["records"]:
        report = json.loads((Path(record["folder"]) / "analysis.json").read_text())
        key = f"{record['system']}-{record['replica']}"
        group = groups.setdefault(key, [])
        fields = ["aligned_heavy_rmsd_initial_A", "central_contact_fraction"]
        metrics = report["metrics"]
        group.append(
            dict(
                block=record["block"],
                passed=record["passed"],
                temperature_K=record["temperature_mean_K"],
                density_g_ml=record["density_mean_g_ml"],
                diagnostics={
                    field: dict(
                        mean=float(np.mean([m[field] for m in metrics])),
                        first_half_mean=float(
                            np.mean([m[field] for m in metrics[: len(metrics) // 2]])
                        ),
                        second_half_mean=float(
                            np.mean([m[field] for m in metrics[len(metrics) // 2 :]])
                        ),
                    )
                    for field in fields
                },
                lesion_bond_mean_A=record["lesion_bond_mean_A"],
            )
        )
    result = dict(
        state=state["state"],
        simulation_ready=False,
        convergence_established=False,
        assessed_ns=len(state["records"]),
        planned_ns=30,
        replicas=groups,
        interpretation="Block means and within-block drift are diagnostics. Formal convergence and experimental accuracy are not established.",
    )
    target = root / "sampling_diagnostics.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(target)
    subprocess.run(
        [sys.executable, "experiments/cpd_published_comparator/export_progress.py"],
        check=True,
    )
    return state


def main(root):
    from experiments.cpd_published_comparator.completion_events import CompletionEvents

    events = CompletionEvents(root)
    previous = None
    try:
        while True:
            state = json.loads((root / "status.json").read_text())
            revision = (state["state"], len(state["records"]))
            if revision != previous:
                assess(root)
                previous = revision
            if state["state"] != "running":
                return
            events.wait()
    finally:
        events.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    main(args.root.resolve())
