"""Collect one recorded Slurm pilot; never fit or promote parameters."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, write


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    root = args.root.resolve()
    submission = json.loads((root / "submission.json").read_text())
    job = submission["slurm_job_id"]
    remote = submission["remote_root"]
    if (
        not job.isdigit()
        or remote
        != "/scratch/alpine/jojo6687/nadoc_qm_campaigns/cpd-drude-water-correlated-pilot-v1"
    ):
        raise ValueError("Unexpected job or remote scope")
    host = "jojo6687@login.rc.colorado.edu"
    socket = "/tmp/nadoc-alpine-1000/control.sock"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-S", socket, host]
    while True:
        try:
            state = subprocess.check_output(
                ssh + [f"squeue --noheader -j {job} -o %T"], text=True, timeout=20
            ).strip()
            if not state:
                state = subprocess.check_output(
                    ssh + [f"sacct -X -j {job} --noheader --parsable2 --format=State"],
                    text=True,
                    timeout=20,
                ).strip()
                terminal = state.split()[0].rstrip("+") if state else ""
                if terminal in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELLED",
                    "TIMEOUT",
                    "OUT_OF_MEMORY",
                    "NODE_FAIL",
                    "BOOT_FAIL",
                    "DEADLINE",
                }:
                    dest = root / "collected"
                    dest.mkdir(exist_ok=True)
                    subprocess.run(
                        [
                            "rsync",
                            "-a",
                            "-e",
                            f"ssh -o BatchMode=yes -o ConnectTimeout=10 -S {socket}",
                            f"{host}:{remote}/",
                            str(dest) + "/",
                        ],
                        check=True,
                        timeout=60,
                    )
                    result = dest / "results" / job / "result.json"
                    record = {
                        "status": "raw_pilot_collected_requires_qm_audit",
                        "slurm_state": state,
                        "simulation_ready": False,
                        "gate_effect": "none",
                        "submission": source(root / "submission.json"),
                        "collector": source(__file__),
                        "files": [
                            source(f) for f in sorted(dest.rglob("*")) if f.is_file()
                        ],
                    }
                    if result.exists():
                        data = json.loads(result.read_text())
                        if (
                            data["input_sha256"]
                            != submission["sources"]["pilot.py"]["sha256"]
                            or data["policy_sha256"]
                            != submission["sources"]["policy.json"]["sha256"]
                        ):
                            raise ValueError(
                                "Pilot result input provenance differs from submission"
                            )
                        record["result"] = source(result)
                    else:
                        record["status"] = (
                            "terminal_pilot_missing_result_requires_diagnosis"
                        )
                    write(root / "collection_assessment.json", record)
                    print(
                        json.dumps(
                            {"state": state, "collection_status": record["status"]}
                        ),
                        flush=True,
                    )
                    return
            print(
                json.dumps({"slurm_job_id": job, "state": state or "not_yet_resolved"}),
                flush=True,
            )
        except (subprocess.SubprocessError, OSError) as error:
            print(f"Transient observation failure; no restart: {error}", flush=True)
        if not args.watch:
            return
        time.sleep(45)


if __name__ == "__main__":
    main()
