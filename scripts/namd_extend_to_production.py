#!/usr/bin/env python3
"""Append post-relaxation NAMD production-qualification segments to an MD job.

The equilibrium-aware ladder currently ends at weak DNA heavy-atom restraints
(k=0.05).  This script extends a completed/restartable job with:
  - k=0.02 NPT qualification, 50 ps
  - k=0.01 NPT qualification, 50 ps
  - k=0.00 unrestrained NPT qualification, 50 ps
  - k=0.00 unrestrained 1 ns production, split 10/50/100% health gates
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


def _scale_label(scale: float | None, production: bool = False) -> str:
    if scale is None:
        return "prod1ns_k0" if production else "k0"
    return f"k{scale:g}".replace(".", "p")


def _stage_label(scale: float | None, production: bool = False) -> str:
    suffix = "production 1 ns" if production else f"k={scale if scale is not None else 0.0}"
    return f"310K NPT {suffix}"


def _existing_segment_names(manifest: dict) -> set[str]:
    return {s.get("name") for s in manifest.get("segments", []) if isinstance(s, dict)}


def build_extension_segments(name_stem: str, previous: str, start_stage_idx: int) -> list[SegmentSpec]:
    segments: list[SegmentSpec] = []
    stage_idx = start_stage_idx

    stages: list[tuple[float | None, int, bool]] = [
        (0.02, 50_000, False),
        (0.01, 50_000, False),
        (None, 50_000, False),
        (None, 1_000_000, True),
    ]

    for scale, total_steps, production in stages:
        label = f"310K_NPT_{_scale_label(scale, production)}"
        for pct, frac in PCTS:
            steps = max(100, int(total_steps * frac))
            name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            segments.append(SegmentSpec(
                name=name,
                stage=_stage_label(scale, production),
                percent=pct,
                steps=steps,
                temp=310.0,
                damping=1.0,
                scale=scale,
                npt=True,
                previous=previous,
                reinit=False,
                dcd_freq=max(100, steps // 5),
            ))
            previous = name
        stage_idx += 1

    return segments


def extend_job(job_id: str, workspace: Path) -> None:
    job_path = workspace / "md_jobs" / job_id / "job.json"
    if not job_path.exists():
        raise FileNotFoundError(f"job.json not found for {job_id}: {job_path}")
    job = json.loads(job_path.read_text())

    package_dir = workspace / "md_jobs" / job_id / job["package_subdir"]
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())

    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    existing = _existing_segment_names(manifest)
    previous = manifest["segments"][-1]["name"]
    start_stage_idx = len({s["stage"] for s in manifest["segments"]}) + 1
    segments = [s for s in build_extension_segments(name_stem, previous, start_stage_idx) if s.name not in existing]

    if not segments:
        print("No new production-extension segments needed.")
        return

    for spec in segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds)
        )

    manifest["segments"].extend(asdict(s) for s in segments)
    manifest["production_extension"] = {
        "status": "queued",
        "reason": "Completed relaxation ended at k=0.05; appended k=0.02, k=0.01, k=0 qualification and 1 ns unrestrained production.",
        "first_new_segment": segments[0].name,
        "last_new_segment": segments[-1].name,
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
    } for s in segments)
    job["status"] = "queued"
    job["error"] = None
    job["current_segment_idx"] = min(int(job.get("current_segment_idx", 0)), len(manifest["segments"]) - len(segments))
    job_path.write_text(json.dumps(job, indent=2) + "\n")

    print(f"Appended {len(segments)} segments to {job_id}.")
    print(f"First new segment: {segments[0].name}")
    print(f"Last new segment : {segments[-1].name}")
    print(f"Job status      : queued")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()
    extend_job(args.job_id, args.workspace)


if __name__ == "__main__":
    main()
