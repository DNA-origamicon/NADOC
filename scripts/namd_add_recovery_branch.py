#!/usr/bin/env python3
"""Append a conservative recovery branch after a marginal low-restraint failure."""

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


def _label(scale: float | None, production: bool = False) -> str:
    if production:
        return "prod1ns_k0_recovery"
    if scale is None:
        return "k0_recovery"
    return f"k{scale:g}_recovery".replace(".", "p")


def _stage(scale: float | None, production: bool = False) -> str:
    if production:
        return "310K NPT production 1 ns recovery"
    return f"310K NPT recovery k={scale if scale is not None else 0.0}"


def _segments(name_stem: str, previous: str, start_stage_idx: int) -> list[SegmentSpec]:
    stages: list[tuple[float | None, int, bool]] = [
        (0.015, 100_000, False),
        (0.01, 100_000, False),
        (0.005, 100_000, False),
        (None, 100_000, False),
        (None, 1_000_000, True),
    ]
    out: list[SegmentSpec] = []
    stage_idx = start_stage_idx
    for scale, total_steps, production in stages:
        label = f"310K_NPT_{_label(scale, production)}"
        for pct, frac in PCTS:
            steps = max(100, int(total_steps * frac))
            name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            out.append(SegmentSpec(
                name=name,
                stage=_stage(scale, production),
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
    return out


def append_recovery(job_id: str, workspace: Path, previous: str) -> None:
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
        print("No new recovery segments needed.")
        return

    start_idx = len(manifest["segments"])
    for spec in new_segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds)
        )

    manifest["segments"].extend(asdict(s) for s in new_segments)
    manifest["recovery_branch"] = {
        "status": "queued",
        "previous": previous,
        "reason": "k=0.01 p100 missed WC gate narrowly; recovery starts from last passing k=0.01 p50 checkpoint.",
        "first_new_segment": new_segments[0].name,
        "last_new_segment": new_segments[-1].name,
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    for seg in job["segments"]:
        if seg["status"] in {"failed", "pending"} and (
            "k0p01_p100" in seg["name"]
            or "_k0_" in seg["name"]
            or "prod1ns_k0" in seg["name"]
        ):
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

    print(f"Appended {len(new_segments)} recovery segments to {job_id}.")
    print(f"Recovery starts at job segment index {start_idx}: {new_segments[0].name}")
    print(f"Recovery ends at: {new_segments[-1].name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--previous", default="10hb_15_310K_NPT_k0p01_p50")
    args = parser.parse_args()
    append_recovery(args.job_id, args.workspace, args.previous)


if __name__ == "__main__":
    main()
