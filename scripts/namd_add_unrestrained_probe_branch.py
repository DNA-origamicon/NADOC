#!/usr/bin/env python3
"""Append an unrestrained production-probe branch from a stable checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.md_protocols import SegmentSpec, _segment_conf


PCTS = [(10.0, 0.10), (50.0, 0.40), (100.0, 0.50)]


def _segments(name_stem: str, previous: str, start_stage_idx: int) -> list[SegmentSpec]:
    stages = [
        ("310K_NPT_k0_probe_wc80", "310K NPT unrestrained probe", 100_000),
        ("310K_NPT_prod1ns_k0_wc80", "310K NPT production 1 ns unrestrained", 1_000_000),
    ]
    out: list[SegmentSpec] = []
    stage_idx = start_stage_idx
    for label, stage, total_steps in stages:
        for pct, frac in PCTS:
            steps = max(100, int(total_steps * frac))
            name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            out.append(SegmentSpec(
                name=name,
                stage=stage,
                percent=pct,
                steps=steps,
                temp=310.0,
                damping=1.0,
                scale=None,
                npt=True,
                previous=previous,
                reinit=False,
                dcd_freq=max(100, steps // 5),
                min_c1_paired=0.95,
                min_wc_ref_relative=0.80,
            ))
            previous = name
        stage_idx += 1
    return out


def append_branch(job_id: str, workspace: Path, previous: str) -> None:
    job_path = workspace / "md_jobs" / job_id / "job.json"
    job = json.loads(job_path.read_text())
    package_dir = workspace / "md_jobs" / job_id / job["package_subdir"]
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    existing = {s["name"] for s in manifest["segments"]}
    start_stage_idx = len({s["stage"] for s in manifest["segments"]}) + 1
    new_segments = [s for s in _segments(name_stem, previous, start_stage_idx) if s.name not in existing]
    if not new_segments:
        print("No new unrestrained probe segments needed.")
        return

    start_idx = len(manifest["segments"])
    for spec in new_segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds)
        )

    manifest["segments"].extend(asdict(s) for s in new_segments)
    manifest["unrestrained_probe_branch"] = {
        "status": "queued",
        "previous": previous,
        "health_gate": {
            "min_c1_paired": 0.95,
            "min_wc_ref_relative": 0.80,
            "note": "C1 pairing is the hard structural gate; WC proxy is allowed more local breathing for unrestrained production probing.",
        },
        "first_new_segment": new_segments[0].name,
        "last_new_segment": new_segments[-1].name,
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    for seg in job["segments"]:
        if seg["status"] in {"failed", "pending"}:
            seg["status"] = "superseded"
    job["segments"].extend({
        "name": s.name,
        "stage": s.stage,
        "percent": s.percent,
        "steps": s.steps,
        "status": "pending",
    } for s in new_segments)
    job["status"] = "queued"
    job["error"] = None
    job["current_segment_idx"] = start_idx
    job_path.write_text(json.dumps(job, indent=2) + "\n")

    print(f"Appended {len(new_segments)} unrestrained probe segments to {job_id}.")
    print(f"Starts at job segment index {start_idx}: {new_segments[0].name}")
    print(f"Ends at: {new_segments[-1].name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--previous", default="10hb_18_310K_NPT_k0p015_recovery_p100")
    args = parser.parse_args()
    append_branch(args.job_id, args.workspace, args.previous)


if __name__ == "__main__":
    main()
