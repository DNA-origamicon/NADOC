"""Back-fill the standard end-of-run health check for runs completed BEFORE it was added.

Reads each completed run's archived final production frame (archive-aware `job_dir`/`stage_dir`),
runs `run_oxdna_health_check`, and records healthy / bp_retained / FENE / stretch into every
results.json row for that job (incl. baseline mirrors).  Idempotent.  Run with the main driver
STOPPED (writes results.json).  Usage:  python backfill_health.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import run as R  # noqa: E402

from backend.core.oxdna_job import OxdnaJob  # noqa: E402
from backend.core.oxdna_runner import _load_snapshot_design  # noqa: E402

WS = str(HERE / "ws")


def main() -> None:
    path = HERE / "results" / "results.json"
    recs = json.loads(path.read_text())
    health_by_job: dict[str, dict] = {}
    for r in recs:
        if r.get("status") != "ok":
            continue
        jid = r["job_id"]
        if jid not in health_by_job:
            try:
                job = OxdnaJob.load(jid, pathlib.Path(WS))
                design = _load_snapshot_design(job.job_dir(pathlib.Path(WS)))
                health_by_job[jid] = R._health_check(design, job, WS)
            except Exception as e:  # noqa: BLE001
                health_by_job[jid] = {"healthy": None, "health_reason": f"backfill error: {e}"}
            h = health_by_job[jid]
            print(f"{jid}: healthy={h.get('healthy')} bp_retained={h.get('bp_retained')} "
                  f"fene_safe={h.get('fene_safe')} stretch={h.get('max_backbone_stretch_nm')}nm",
                  flush=True)
        r.update(health_by_job[jid])
    path.write_text(json.dumps(recs, indent=2))
    print(f"backfilled health into {sum(1 for r in recs if r.get('status')=='ok')} ok rows.")


if __name__ == "__main__":
    main()
