#!/usr/bin/env python3
"""Append the Relax protocol's unrestrained qualification tail to an MD job.

This is the manual repair path for jobs created before Relax included the
final k=0 pre-run.  It appends:
  - k=0.02 NPT, 50 ps at 1 fs/step
  - k=0.01 NPT, 50 ps at 1 fs/step
  - k=0 unrestrained qualification, 100 ps at 1 fs/step
"""

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


def _stage_label(scale: float | None) -> str:
    if scale is None:
        return "310K NPT unrestrained qualification"
    return f"310K NPT k={scale}"


def _scale_label(scale: float | None) -> str:
    if scale is None:
        return "k0_qualification"
    return f"k{scale:g}".replace(".", "p")


def _segments(name_stem: str, previous: str, start_stage_idx: int) -> list[SegmentSpec]:
    stages: list[tuple[float | None, int]] = [
        (0.02, 50_000),
        (0.01, 50_000),
        (None, 100_000),
    ]
    out: list[SegmentSpec] = []
    stage_idx = start_stage_idx
    for scale, total_steps in stages:
        label = f"310K_NPT_{_scale_label(scale)}"
        for pct, frac in PCTS:
            steps = max(100, int(total_steps * frac))
            name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            out.append(SegmentSpec(
                name=name,
                stage=_stage_label(scale),
                percent=pct,
                steps=steps,
                temp=310.0,
                damping=1.0,
                scale=scale,
                npt=True,
                previous=previous,
                reinit=False,
                dcd_freq=max(100, min(10_000, steps // 50)),
                min_c1_paired=0.90,
                min_wc_ref_relative=0.80 if scale is None else 0.85,
            ))
            previous = name
        stage_idx += 1
    return out


def append_qualification(job_id: str, workspace: Path) -> None:
    job_path = workspace / "md_jobs" / job_id / "job.json"
    if not job_path.exists():
        raise FileNotFoundError(f"job.json not found for {job_id}: {job_path}")
    job = json.loads(job_path.read_text())
    package_dir = workspace / "md_jobs" / job_id / job["package_subdir"]
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    existing = {s["name"] for s in manifest.get("segments", [])}
    previous = manifest["segments"][-1]["name"]
    start_idx = len(manifest["segments"])
    start_stage_idx = len({s["stage"] for s in manifest["segments"]}) + 1
    new_segments = [
        s for s in _segments(name_stem, previous, start_stage_idx)
        if s.name not in existing
    ]
    if not new_segments:
        print("No new unrestrained qualification segments needed.")
        return

    for spec in new_segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds)
        )

    manifest["segments"].extend(asdict(s) for s in new_segments)
    manifest["unrestrained_qualification"] = {
        "status": "queued",
        "previous": previous,
        "first_new_segment": new_segments[0].name,
        "last_new_segment": new_segments[-1].name,
        "health_gate": {
            "min_c1_paired": 0.90,
            "min_wc_ref_relative": 0.80,
        },
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

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

    print(f"Appended {len(new_segments)} unrestrained qualification segments to {job_id}.")
    print(f"First new segment: {new_segments[0].name}")
    print(f"Last new segment : {new_segments[-1].name}")
    print(f"Resume index     : {start_idx}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()
    append_qualification(args.job_id, args.workspace)


if __name__ == "__main__":
    main()
