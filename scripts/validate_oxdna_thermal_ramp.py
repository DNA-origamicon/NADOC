"""Explicit opt-in native validation from an existing, completed managed job.

Does not author a structure. Uses the same production endpoint as the wizard.
"""
import argparse
import asyncio
import json
from pathlib import Path


def run(parent, workspace, config):
    from backend.api.headless_oxdna_build import _use_workspace, _scratch_job_design, start_relaxation
    from backend.api.routes_oxdna import RunRequest, append_oxdna_run
    from scripts.validate_oxdna_cpd import wait_job
    workspace = Path(workspace).resolve()
    with _use_workspace(workspace), _scratch_job_design(parent, workspace):
        child = asyncio.run(append_oxdna_run(parent, RunRequest(thermal_ramp=config)))
    start_relaxation(child["job_id"], workspace)
    job = wait_job(child["job_id"], workspace)
    result = {"job_id": job.job_id, "status": job.status.value, "error": job.error,
              "stages": [s.__dict__ for s in job.stages],
              "thermal_progress": job.run_config.get("thermal_progress")}
    (job.job_dir(workspace) / "thermal_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--config", required=True, help="JSON thermal-ramp configuration")
    args = parser.parse_args()
    run(args.parent, args.workspace, json.loads(args.config))
