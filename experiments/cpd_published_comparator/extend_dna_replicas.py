"""Checkpointed local DNA extensions; fail closed on numerical/structural errors."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import sys
import numpy as np
from experiments.cpd_published_comparator.analyze_dna_replicas import analyze_case
from experiments.cpd_published_comparator.reconstruct import source


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def run(root, parent, wake_thread, expected_seconds=14400):
    if not wake_thread or not shutil.which("codex"):
        raise RuntimeError(
            "Long runs require an originating --wake-thread and callable codex queue"
        )
    root.mkdir(parents=True, exist_ok=False)
    parent = parent.resolve()
    save(
        root / "protocol.json",
        dict(
            stage="5 ns per replica extension",
            simulation_ready=False,
            parent=str(parent),
            replicas=6,
            blocks_per_replica=5,
            block_ps=1000,
            timestep_fs=2,
            frames_per_block=500,
            restraints=False,
            scheduling="Sequential, alternating matched CPD/control replicas per 1 ns block",
            limits=[
                "5 ns does not guarantee convergence",
                "Initial structure bias remains",
                "Independent glycosidic energetics and general strand integration pending",
            ],
            source=source(Path(__file__)),
        ),
    )
    shutil.copy2(__file__, root / "executed_source.py")
    shutil.copy2(
        Path(__file__).with_name("analyze_dna_replicas.py"), root / "analyzer_source.py"
    )
    records = []
    status = dict(
        state="running", pid=os.getpid(), records=records, simulation_ready=False
    )
    save(root / "status.json", status)
    # Register completion/deadline supervision before starting native work.
    with (root / "wake_supervisor.log").open("w") as log:
        watcher = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "experiments.cpd_published_comparator.trigger_dna_review",
                "--root",
                str(root),
                "--codex",
                shutil.which("codex"),
                "--thread",
                wake_thread,
                "--expected-seconds",
                str(expected_seconds),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # Bounded registration handshake only; the long run itself is event-driven.
    for _ in range(50):
        if (root / "completion_wake.json").exists():
            break
        if watcher.poll() is not None:
            raise RuntimeError(
                "Completion watcher failed to arm; inspect wake_supervisor.log"
            )
        time.sleep(0.1)
    else:
        raise RuntimeError("Completion watcher did not acknowledge registration")
    try:
        for block in range(1, 6):
            for replica in range(1, 4):
                for system in ["cpd", "control"]:
                    original = parent / system / f"replica-{replica}"
                    previous = (
                        original
                        if block == 1
                        else root / system / f"replica-{replica}" / f"block-{block - 1}"
                    )
                    folder = root / system / f"replica-{replica}" / f"block-{block}"
                    folder.mkdir(parents=True)
                    for name in ["system.psf", "system.pdb"]:
                        shutil.copy2(original / name, folder / name)
                    build = json.loads((original / "build.json").read_text())
                    build.update(
                        production_start_step=110000 + (block - 1) * 500000,
                        production_steps=500000,
                        expected_frames=500,
                        stage="extended DNA stability sampling",
                    )
                    save(folder / "build.json", build)
                    config = (
                        (original / "run.conf").read_text().split("constraints on")[0]
                    )
                    lines = []
                    for line in config.splitlines():
                        key = line.split()[0] if line.split() else ""
                        if key in [
                            "temperature",
                            "cellBasisVector1",
                            "cellBasisVector2",
                            "cellBasisVector3",
                            "cellOrigin",
                        ]:
                            continue
                        if key == "seed":
                            line = f"seed {int(line.split()[1]) + block * 100003}"
                        if key in ["outputName", "DCDfile"]:
                            line = f"{key} {folder / ('trajectory.dcd' if key == 'DCDfile' else 'trajectory')}"
                        if key == "dcdfreq":
                            line = "dcdfreq 1000"
                        lines.append(line)
                    start = build["production_start_step"]
                    lines += [
                        f"bincoordinates {previous / 'trajectory.coor'}",
                        f"binvelocities {previous / 'trajectory.vel'}",
                        f"extendedSystem {previous / 'trajectory.xsc'}",
                        f"firsttimestep {start}",
                        "run 500000",
                    ]
                    (folder / "run.conf").write_text("\n".join(lines) + "\n")
                    save(
                        folder / "restart_sources.json",
                        [
                            source(previous / f"trajectory.{ext}")
                            for ext in ["coor", "vel", "xsc"]
                        ],
                    )
                    status.update(
                        current=dict(
                            system=system,
                            replica=replica,
                            block=block,
                            folder=str(folder),
                        ),
                        updated=time.time(),
                    )
                    save(root / "status.json", status)
                    before = time.time()
                    with (folder / "run.log").open("w") as log:
                        process = subprocess.Popen(
                            ["namd3", "+p2", "+devices", "0", str(folder / "run.conf")],
                            stdout=log,
                            stderr=subprocess.STDOUT,
                        )
                        status["namd_pid"] = process.pid
                        save(root / "status.json", status)
                        code = process.wait()
                    rows = []
                    keys = []
                    text = (folder / "run.log").read_text()
                    for line in text.splitlines():
                        if line.startswith("ETITLE:"):
                            keys = line.split()[1:]
                        if line.startswith("ENERGY:"):
                            rows.append(dict(zip(keys, map(float, line.split()[1:]))))
                    valid = (
                        bool(rows)
                        and all(np.isfinite(v) for row in rows for v in row.values())
                        and all(row["TEMP"] > 0.1 for row in rows)
                    )
                    passed = (
                        code == 0
                        and "FATAL ERROR" not in text
                        and valid
                        and rows[-1]["TS"] == start + 500000
                    )
                    completion = dict(
                        exit_code=code,
                        elapsed_s=time.time() - before,
                        passed_execution=bool(passed),
                        last_step=rows[-1]["TS"] if rows else None,
                    )
                    save(folder / "completion.json", completion)
                    if not passed:
                        raise RuntimeError(f"Native execution failed: {folder}")
                    report = analyze_case(folder)
                    save(folder / "analysis.json", report)
                    record = {
                        k: v
                        for k, v in report.items()
                        if k not in ["metrics", "sources", "center_volume_ranges"]
                    }
                    record.update(
                        block=block,
                        folder=str(folder),
                        elapsed_s=completion["elapsed_s"],
                    )
                    records.append(record)
                    save(root / "status.json", status)
                    print(json.dumps(record), flush=True)
                    if not report["passed"]:
                        raise RuntimeError(f"Structural assessment failed: {folder}")
        status["state"] = "complete"
    except BaseException as exc:
        status.update(state="failed", error=repr(exc))
        raise
    finally:
        status.update(updated=time.time(), namd_pid=None)
        save(root / "status.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--parent",
        type=Path,
        default=Path(".development-artifacts/cpd-dna-replicas-v2"),
    )
    parser.add_argument("--wake-thread", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--expected-seconds", type=float, default=14400)
    args = parser.parse_args()
    run(args.root.resolve(), args.parent, args.wake_thread, args.expected_seconds)
