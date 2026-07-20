"""Validate and export completed exp43 trajectories without mixing phases."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def process_all(workspace: Path) -> dict:
    from backend.core.md_job import MdJob
    from backend.ml.propagator.windows import export_windows

    registry = json.loads((HERE / "runs" / "registry.json").read_text())
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    summary = {"conditions": {}, "phase_policy": {
        "restrained": "non-equilibrium relaxation; useful only with this label",
        "unrestrained": "equilibrium-candidate; diagnostics must establish burn-in",
    }}
    for condition, entry in registry["jobs"].items():
        job = MdJob.load(entry["job_id"], workspace)
        status = job.status.value if hasattr(job.status, "value") else str(job.status)
        if status != "completed":
            summary["conditions"][condition] = {"status": status, "exported": False}
            continue
        pkg = job.package_dir(workspace)
        manifest = json.loads((pkg / "manifest.json").read_text())
        by_name = {s["name"]: s for s in manifest["segments"]}
        phase_segments = {
            "restrained": [s for s in job.segments if by_name[s.name].get("scale") is not None],
            "unrestrained": [s for s in job.segments if by_name[s.name].get("scale") is None],
        }
        condition_out = results / condition
        phase_out = {}
        system_meta = json.loads((HERE / "designs" / condition / "system.json").read_text())
        for phase, segments in phase_segments.items():
            # export_windows discovers captures through job.segments, so a shallow
            # phase view preserves the source job while enforcing phase separation.
            phase_job = dataclasses.replace(job, segments=segments)
            try:
                m = export_windows(phase_job, workspace, condition_out / phase / "frames.npz",
                                   system_meta={**system_meta, "trajectory_phase": phase},
                                   dna_only=False)
                phase_out[phase] = {"exported": True, "manifest": m}
            except RuntimeError as exc:
                phase_out[phase] = {"exported": False, "reason": str(exc)}
        summary["conditions"][condition] = {"status": status, "phases": phase_out}
    (results / "processing_summary.json").write_text(json.dumps(summary, indent=2))
    return summary
