"""A triggered 90 Å-box pilot using the deposited 1T4I starting state."""

import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path
import MDAnalysis as mda
from scipy.spatial.distance import pdist
from experiments.cpd_published_comparator import dna_replicas as pilot
from experiments.cpd_published_comparator.analyze_dna_replicas import (
    analyze_case,
    main as assess,
)
from experiments.cpd_published_comparator.trigger_dna_review import save


def main(root, candidate, thread, build_only=False):
    pilot.CANDIDATE = candidate.resolve()
    if build_only:
        pilot.build(
            root, padding_nm=2.0, box_mode="rotation", box_size_nm=(9.0, 9.0, 9.0)
        )
        protocol = json.loads((root / "protocol.json").read_text())
        protocol.update(
            stage="1T4I large-box replicated pilot",
            starting_structure="Deposited 1T4I A/B; same v6 PSFs and parameters",
            box_goal="90 Å cubic; rotation-safe initial separation with deformation margin",
        )
        protocol["limits"] = [
            "1T4I coordinates and box both change relative to prior batch: effects cannot be separately attributed",
            "Undamaged control still derives from a damaged crystal; independent normal-DNA starting ensemble remains pending",
            "Short pilot does not establish convergence or production readiness",
        ]
        save(root / "protocol.json", protocol)
        return
    assert thread, "Originating thread required"
    state = dict(
        state="running",
        pid=os.getpid(),
        records=[],
        expected_keys=[[s, r, 0] for s in ["cpd", "control"] for r in range(1, 4)],
        simulation_ready=False,
    )
    save(root / "status.json", state)
    with (root / "wake_supervisor.log").open("w") as log:
        wake = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "experiments.cpd_published_comparator.trigger_dna_review",
                "--root",
                str(root),
                "--codex",
                shutil.which("codex"),
                "--thread",
                thread,
                "--expected-seconds",
                "3600",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(50):
        if (root / "completion_wake.json").exists():
            break
        if wake.poll() is not None:
            raise RuntimeError("Wake registration failed")
        time.sleep(0.1)
    else:
        raise RuntimeError("Wake registration timeout")

    def completed(case):
        folder = Path(case["folder"])
        report = analyze_case(folder)
        # A conservative bound valid for any orientation: shortest cell length minus
        # maximum solute heavy-atom separation. Fail if that guarantee is lost.
        u = mda.Universe(str(folder / "system.psf"), str(folder / "trajectory.dcd"))
        heavy = u.atoms[:634][u.atoms[:634].masses > 2]
        bounds = []
        for ts in u.trajectory[::5]:
            bounds.append(float(min(ts.dimensions[:3]) - max(pdist(heavy.positions))))
        report["rotation_independent_image_gap_lower_bound_A"] = min(bounds)
        report["checks"]["image_gap_lower_bound_above_16A"] = min(bounds) > 16
        report["passed"] = all(report["checks"].values())
        save(folder / "analysis.json", report)
        record = {
            k: v
            for k, v in report.items()
            if k not in ["metrics", "sources", "center_volume_ranges"]
        }
        record["block"] = 0
        state["records"].append(record)
        save(root / "status.json", state)
        assess(root)
        print(json.dumps(record), flush=True)
        if not report["passed"]:
            raise RuntimeError(f"Pilot assessment failed: {folder}")

    try:
        pilot.run(root, on_case=completed)
        state["state"] = "complete"
    except BaseException as exc:
        state.update(state="failed", error=repr(exc))
        raise
    finally:
        state["finished_at"] = time.time()
        save(root / "status.json", state)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument(
        "--candidate",
        type=Path,
        default=Path(".development-artifacts/cpd-start-1t4i-v2"),
    )
    p.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--build", action="store_true")
    a = p.parse_args()
    main(a.root.resolve(), a.candidate, a.thread, a.build)
