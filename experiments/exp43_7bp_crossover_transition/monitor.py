"""Experiment-level failure and completeness checks for exp43."""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "runs" / "registry.json"
STALE_SECONDS = 30 * 60


def inspect_job(job, workspace: Path, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    pkg = job.package_dir(workspace)
    output = pkg / "output"
    issues: list[dict] = []
    if status == "failed":
        issues.append({"severity": "fatal", "kind": job.failure_kind or "namd_failure",
                       "message": job.error or "job failed"})
    if status == "running":
        heartbeat_candidates = [job.job_dir(workspace) / "job.json"]
        heartbeat_candidates += list(output.glob("*.log")) if output.exists() else []
        newest = max((p.stat().st_mtime for p in heartbeat_candidates if p.exists()), default=0)
        if newest and now - newest > STALE_SECONDS:
            issues.append({"severity": "fatal", "kind": "stalled",
                           "message": f"no job/log update for {int(now-newest)} seconds"})

    manifest_path = pkg / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    captured = {s["name"] for s in manifest.get("segments", [])
                if s.get("scale") is None and manifest.get("capture_vel_force", True)}
    for name in captured:
        files = [output / f"{name}{suffix}" for suffix in (".dcd", ".veldcd", ".forcedcd")]
        present = [p.exists() and p.stat().st_size > 0 for p in files]
        if any(present) and not all(present):
            issues.append({"severity": "fatal", "kind": "capture_triplet_incomplete",
                           "segment": name, "message": "position/velocity/force files differ"})

    health_path = output / "health.jsonl"
    if health_path.exists():
        for line in health_path.read_text().splitlines():
            try:
                h = json.loads(line)
            except json.JSONDecodeError:
                issues.append({"severity": "fatal", "kind": "torn_health_record",
                               "message": "health.jsonl contains invalid JSON"})
                continue
            if not h.get("passed", False):
                issues.append({"severity": "fatal" if h.get("blocking") else "warning",
                               "kind": "health_gate", "segment": h.get("segment"),
                               "message": h.get("reason") or h.get("error") or "health failed"})
    return {"job_id": job.job_id, "status": status, "issues": issues,
            "ok": not any(i["severity"] == "fatal" for i in issues)}


def monitor_all(workspace: Path, *, write: bool = False) -> int:
    from backend.core.md_job import MdJob
    if not REGISTRY.exists():
        raise SystemExit("experiment has not been prepared; registry.json is absent")
    registry = json.loads(REGISTRY.read_text())
    report = {"checked_at": time.time(), "conditions": {}}
    for condition, entry in registry["jobs"].items():
        job = MdJob.load(entry["job_id"], workspace)
        report["conditions"][condition] = inspect_job(job, workspace)
    report["ok"] = all(v["ok"] for v in report["conditions"].values())
    if write:
        out = HERE / "results"
        out.mkdir(exist_ok=True)
        (out / "monitor.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2
