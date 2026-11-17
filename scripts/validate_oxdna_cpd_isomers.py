"""Explicit scientific validation of each newly supported oxDNA CPD isomer.

Serial native jobs, normal health gates/retries, replayable published parts.
Failures are retained and reported; no gate relaxation or implicit re-fitting.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from scripts.validate_oxdna_cpd import main, continue_job

ISOMERS = ("cis-anti-I", "trans-syn-I", "trans-syn-II")


def validate(output, isomers=ISOMERS):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for isomer in isomers:
        folder = output / isomer
        try:
            main(folder, 1_000_000, isomer)
            run = json.loads((folder / "validation.json").read_text())
            job = folder / "oxdna_jobs" / run["job_id"]
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.check_oxdna_cpd_forces",
                    str(job / "4_production/input.txt"),
                    str(folder / "force-audit"),
                ],
                check=True,
            )
            continuation = continue_job(run["job_id"], folder, 1_000_000)
            results.append(
                {
                    "isomer": isomer,
                    "status": "passed",
                    "run": run,
                    "continuation": continuation,
                    "force_audit": json.loads(
                        (folder / "force-audit/force_audit.json").read_text()
                    ),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "isomer": isomer,
                    "status": "failed",
                    "error": str(exc),
                    "evidence": str(folder),
                }
            )
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(
            json.dumps({"isomer": isomer, "status": results[-1]["status"]}), flush=True
        )
    if any(result["status"] != "passed" for result in results):
        raise RuntimeError("One or more isomers failed; see retained results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--isomer", choices=ISOMERS, action="append")
    args = parser.parse_args()
    validate(args.output, args.isomer or ISOMERS)
