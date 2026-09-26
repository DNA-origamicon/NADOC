"""Launch a resource-bounded command with a watcher in a separate systemd cgroup."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_published_comparator.trigger_dna_review import save
from experiments.cpd_anti_additive.watch import process_identity


def supervise(root):
    plan = json.loads((root / "execution_plan.json").read_text())
    state = dict(
        state="starting",
        pid=os.getpid(),
        records=[],
        started_at=time.time(),
        simulation_ready=False,
    )
    save(root / "status.json", state)
    watcher = root / "watcher.py"
    subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={plan['unit']}-watch",
            f"--setenv=PYTHONPATH={REPO}",
            "--property=Restart=on-failure",
            "--property=RestartSec=30",
            "--property=StartLimitIntervalSec=300",
            "--property=StartLimitBurst=5",
            "/usr/bin/python3",
            str(watcher),
            "--root",
            str(root),
            "--thread",
            plan["thread"],
        ],
        check=True,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            wp = root / "completion_wake.json"
            if wp.exists():
                w = json.loads(wp.read_text())
                if w["state"] == "armed" and process_identity(w["watcher_pid"]):
                    break
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "External watcher failed to arm; command not started"
                )
            time.sleep(0.1)
        state["state"] = "running"
        save(root / "status.json", state)
        with (root / "run.log").open("w") as log:
            p = subprocess.run(
                plan["command"], cwd=plan["cwd"], stdout=log, stderr=subprocess.STDOUT
            )
        state.update(
            state="complete" if p.returncode == 0 else "failed", returncode=p.returncode
        )
    except BaseException as exc:
        state.update(state="failed", error=repr(exc))
        raise
    finally:
        state["finished_at"] = time.time()
        save(root / "status.json", state)


def launch(
    root,
    unit,
    command,
    expected_seconds,
    memory_gib=20,
    threads=16,
    hours=24,
    cwd=None,
    self_test=False,
):
    pause_path = REPO / ".development-artifacts/cpd-anti-validation-v1/campaign_pause.json"
    if pause_path.exists() and json.loads(pause_path.read_text()).get("paused"):
        raise RuntimeError("CPD campaign paused by user; explicit resume required")
    fitting_scripts = {
        "refine_joint.py", "refine_remote_reference.py", "refine_core_angles.py",
        "fit_charge_candidates.py", "multiconformer_charge_fit.py",
        "multiconformer_water_charge_fit.py", "coupled_round.py", "remote_coupled_round.py",
        "broad_torsion_diagnostic.py", "profile_diagnostic.py",
    }
    if any(Path(str(arg)).name in fitting_scripts for arg in command):
        from experiments.cpd_anti_additive.validation_gate import require_fit_ready
        require_fit_ready()
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex executable unavailable")
    thread = os.environ["CODEX_THREAD_ID"]
    for name in ("watch", "launch"):
        shutil.copy2(
            REPO / f"experiments/cpd_anti_additive/{name}.py",
            root / f"{name}er.py" if name == "watch" else root / "supervisor.py",
        )
    save(
        root / "watcher_config.json",
        dict(
            codex_executable=str(Path(codex).resolve()),
            expected_seconds=expected_seconds,
            self_test=self_test,
        ),
    )
    save(
        root / "execution_plan.json",
        dict(
            unit=unit,
            command=command,
            thread=thread,
            cwd=str(cwd or REPO),
            expected_seconds=expected_seconds,
            memory_gib=memory_gib,
            omp_threads=threads,
            runtime_hours=hours,
            completion_semantics="Command termination only. Inspect scientific reports before accepting results.",
        ),
    )
    # Copies retain repo imports through an explicit environment, not parent-directory inference.
    subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            f"--property=MemoryMax={memory_gib}G",
            "--property=MemorySwapMax=0",
            f"--property=RuntimeMaxSec={hours}h",
            f"--setenv=PYTHONPATH={REPO}",
            f"--setenv=NADOC_REPO_ROOT={REPO}",
            "--setenv=OPENBLAS_NUM_THREADS=1",
            "--setenv=MKL_NUM_THREADS=1",
            f"--setenv=OMP_NUM_THREADS={threads}",
            "/usr/bin/python3",
            str(root / "supervisor.py"),
            "--supervise",
            str(root),
        ],
        check=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--supervise", type=Path, required=True)
    supervise(p.parse_args().supervise)
