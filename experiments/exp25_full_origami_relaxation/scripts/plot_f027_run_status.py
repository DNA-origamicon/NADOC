#!/usr/bin/env python3
"""Plot F027 B_tube production-candidate monitoring, health, and ETA.

The script is intentionally read-only: it parses the active F027 package's NAMD
logs, manifest, XST files, and health JSONL records, then writes a dashboard PNG
plus a compact JSON summary.

Usage:
    python experiments/exp25_full_origami_relaxation/scripts/plot_f027_run_status.py
    python experiments/exp25_full_origami_relaxation/scripts/plot_f027_run_status.py \
      --package-dir .../B_tube_namd_solvated --out output/F027_run_status.png
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F027_literature_aligned_enm_production/B_tube_namd_solvated"
)

ENERGY_PREFIX = "ENERGY:"
PERF_RE = re.compile(r"PERFORMANCE:\s+(\d+)\s+averaging\s+([0-9.eE+-]+)\s+ns/day")
TIMING_RE = re.compile(r"TIMING:\s+(\d+).*?Wall:\s+([0-9.eE+-]+),\s+([0-9.eE+-]+)/step")
WALL_RE = re.compile(r"WallClock:\s+([0-9.eE+-]+)")
FATAL_MARKERS = (
    "-99999999999.9999",
    "FATAL ERROR",
    "CUDA initialization error",
    "CUDA error cudaGetDeviceCount",
    "NVRM: API mismatch",
    "Driver/library version mismatch",
    "forward compatibility was attempted on non supported HW",
    "Atoms moving too fast",
    "Periodic cell has become too small",
)


@dataclass
class StageStatus:
    name: str
    planned_steps: int
    minimize_steps: int
    temp: float | None
    npt: bool
    done: bool
    started: bool
    current_step: int
    ns_per_day: float | None
    wallclock_s: float | None
    fatal_markers: list[str]
    energy_rows: list[dict[str, float]]
    perf_rows: list[tuple[int, float]]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_manifest(package_dir: Path) -> dict:
    return _read_json(package_dir / "F027_manifest.json")


def _parse_energy_log(log_path: Path) -> tuple[list[dict[str, float]], list[tuple[int, float]], float | None, list[str]]:
    if not log_path.exists():
        return [], [], None, []
    text = log_path.read_text(errors="replace")
    fatal = [marker for marker in FATAL_MARKERS if marker in text]
    col_idx: dict[str, int] = {}
    rows: list[dict[str, float]] = []
    for line in text.splitlines():
        if line.startswith("ETITLE:"):
            fields = line.split()
            col_idx = {name: i - 1 for i, name in enumerate(fields) if i >= 1}
        elif line.startswith(ENERGY_PREFIX) and col_idx:
            vals = line.split()[1:]
            try:
                nums = [float(v) for v in vals]
            except ValueError:
                continue
            rec = {}
            for name, idx in col_idx.items():
                if 0 <= idx < len(nums):
                    rec[name] = nums[idx]
            if rec:
                rows.append(rec)

    perfs = [(int(m.group(1)), float(m.group(2))) for m in PERF_RE.finditer(text)]
    wall = None
    if m := WALL_RE.search(text):
        wall = float(m.group(1))
    return rows, perfs, wall, fatal


def _stage_status(package_dir: Path, stage: dict) -> StageStatus:
    name = stage["name"]
    log_path = package_dir / f"{name}.log"
    out_dir = package_dir / "output"
    coor_path = out_dir / f"{name}.coor"
    rows, perfs, wall, fatal = _parse_energy_log(log_path)
    current_step = int(rows[-1].get("TS", 0)) if rows else 0
    ns_day = perfs[-1][1] if perfs else None
    return StageStatus(
        name=name,
        planned_steps=int(stage.get("steps") or 0),
        minimize_steps=int(stage.get("minimize_steps") or 0),
        temp=stage.get("temp"),
        npt=bool(stage.get("npt")),
        done=coor_path.exists(),
        started=log_path.exists(),
        current_step=current_step,
        ns_per_day=ns_day,
        wallclock_s=wall,
        fatal_markers=fatal,
        energy_rows=rows,
        perf_rows=perfs,
    )


def _load_health(output_dir: Path) -> list[dict]:
    path = output_dir / "F027_health.jsonl"
    records = []
    if not path.exists():
        return records
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _latest_health_by_stage(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in records:
        stage = rec.get("stage") or rec.get("segment")
        if stage:
            latest[stage] = rec
    return latest


def _parse_xst(path: Path) -> tuple[list[int], list[float]]:
    steps, volumes = [], []
    if not path.exists():
        return steps, volumes
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("$"):
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            steps.append(int(float(parts[0])))
            ax, ay, az = map(float, parts[1:4])
            bx, by, bz = map(float, parts[4:7])
            cx, cy, cz = map(float, parts[7:10])
            mat = np.asarray([[ax, ay, az], [bx, by, bz], [cx, cy, cz]], dtype=float)
            volumes.append(float(abs(np.linalg.det(mat))))
        except ValueError:
            continue
    return steps, volumes


def _format_duration(days: float | None) -> str:
    if days is None or not math.isfinite(days):
        return "n/a"
    seconds = max(0.0, days * 86400.0)
    if seconds < 3600:
        return f"{seconds/60:.0f} min"
    if seconds < 86400:
        return f"{seconds/3600:.1f} h"
    return f"{seconds/86400:.1f} d"


def _compute_progress(stages: list[StageStatus]) -> dict[str, Any]:
    total_steps = sum(s.planned_steps for s in stages)
    done_steps = 0
    current: StageStatus | None = None
    for s in stages:
        if s.planned_steps <= 0:
            continue
        if s.done:
            done_steps += s.planned_steps
        elif s.started and current is None:
            current = s
            done_steps += min(s.current_step, s.planned_steps)
        elif current is not None:
            continue
    if current is None:
        for s in stages:
            if s.started and not s.done:
                current = s
                break
    failed_stage = next((s for s in stages if s.fatal_markers), None)
    latest_rate = None
    for s in reversed(stages):
        if s.ns_per_day:
            latest_rate = s.ns_per_day
            break
    remaining_steps = max(0, total_steps - done_steps)
    # All F027 dynamics configs currently use timestep 1 fs.
    remaining_ns = remaining_steps * 1.0e-6
    eta_days = remaining_ns / latest_rate if latest_rate and latest_rate > 0 else None
    current_remaining_days = None
    if current and current.planned_steps and latest_rate:
        current_remaining_ns = max(0, current.planned_steps - current.current_step) * 1.0e-6
        current_remaining_days = current_remaining_ns / latest_rate
    return {
        "total_steps": total_steps,
        "done_steps": done_steps,
        "progress_fraction": done_steps / total_steps if total_steps else 0.0,
        "remaining_steps": remaining_steps,
        "remaining_ns": remaining_ns,
        "latest_ns_per_day": latest_rate,
        "eta_days": eta_days,
        "current_stage": current.name if current else None,
        "failed_stage": failed_stage.name if failed_stage else None,
        "current_stage_eta_days": current_remaining_days,
        "estimated_completion": (
            (datetime.now() + timedelta(days=eta_days)).isoformat(timespec="minutes")
            if eta_days is not None
            else None
        ),
    }


def _gpu_snapshot() -> dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        return {}
    if not out:
        return {}
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    keys = ["gpu_util_pct", "mem_util_pct", "mem_used_mb", "mem_total_mb", "power_w", "power_limit_w", "temp_c"]
    snap = {}
    for key, val in zip(keys, parts):
        try:
            snap[key] = float(val)
        except ValueError:
            snap[key] = val
    return snap


def _concat_stage_series(stages: list[StageStatus], column: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    offset = 0.0
    for s in stages:
        local = []
        for row in s.energy_rows:
            if column in row and "TS" in row:
                local.append((offset + row["TS"] * 1.0e-6, row[column]))
        if local:
            x, y = zip(*local)
            xs.extend(x)
            ys.extend(y)
        offset += s.planned_steps * 1.0e-6
    return xs, ys


def _plot_dashboard(package_dir: Path, out_path: Path, summary_path: Path) -> dict:
    manifest = _load_manifest(package_dir)
    out_dir = package_dir / "output"
    stages = [_stage_status(package_dir, s) for s in manifest["stages"]]
    health_records = _load_health(out_dir)
    latest_health = _latest_health_by_stage(health_records)
    progress = _compute_progress(stages)
    gpu = _gpu_snapshot()

    fig = plt.figure(figsize=(16, 11), constrained_layout=True)
    gs = gridspec.GridSpec(4, 3, figure=fig, height_ratios=[1.05, 1, 1, 0.8])
    ax_progress = fig.add_subplot(gs[0, :])
    ax_perf = fig.add_subplot(gs[1, 0])
    ax_temp = fig.add_subplot(gs[1, 1])
    ax_press = fig.add_subplot(gs[1, 2])
    ax_health = fig.add_subplot(gs[2, :2])
    ax_volume = fig.add_subplot(gs[2, 2])
    ax_text = fig.add_subplot(gs[3, :])

    fig.suptitle("F027 B_tube Production Candidate: Monitoring and Health", fontsize=17, fontweight="bold")

    # Progress strip.
    total_steps = max(1, progress["total_steps"])
    x0 = 0
    colors = {"done": "#2b8a3e", "active": "#1c7ed6", "pending": "#ced4da", "failed": "#c92a2a"}
    active = progress["current_stage"]
    for s in stages:
        width = s.planned_steps / total_steps if s.planned_steps else 0.012
        status = "done" if s.done else "active" if s.name == active else "pending"
        if s.fatal_markers:
            status = "failed"
        ax_progress.barh([0], [width], left=[x0], color=colors[status], edgecolor="white", height=0.42)
        label = s.name.replace("F027_", "").replace("_", "\n")
        if width > 0.025:
            ax_progress.text(x0 + width / 2, 0, label, ha="center", va="center", fontsize=7)
        x0 += width
    ax_progress.set_xlim(0, 1)
    ax_progress.set_yticks([])
    ax_progress.set_xlabel(f"Pipeline progress: {progress['progress_fraction']*100:.2f}% of planned dynamics")
    ax_progress.set_title("Stage Progress")
    ax_progress.grid(axis="x", alpha=0.2)

    # Performance by stage.
    names, rates = [], []
    for s in stages:
        if s.ns_per_day is not None:
            names.append(s.name.replace("F027_", "").replace("_", "\n"))
            rates.append(s.ns_per_day)
    if rates:
        ax_perf.bar(range(len(rates)), rates, color="#495057")
        ax_perf.set_xticks(range(len(rates)), names, rotation=35, ha="right", fontsize=7)
        ax_perf.set_ylabel("ns/day")
        ax_perf.set_title("NAMD Performance")
        ax_perf.axhline(progress["latest_ns_per_day"], color="#e67700", ls="--", lw=1)
    else:
        ax_perf.text(0.5, 0.5, "No performance lines yet", ha="center", va="center")
    ax_perf.grid(axis="y", alpha=0.25)

    # Temperature, pressure, volume.
    for ax, col, ylabel, title, color in [
        (ax_temp, "TEMP", "K", "Temperature", "#c92a2a"),
        (ax_press, "PRESSURE", "bar", "Pressure", "#1971c2"),
    ]:
        xs, ys = _concat_stage_series(stages, col)
        if xs:
            ax.plot(xs, ys, color=color, lw=1.4)
            if col == "TEMP":
                ax.axhline(310, color="#868e96", ls=":", lw=1)
            if col == "PRESSURE":
                ax.axhline(1.01325, color="#868e96", ls=":", lw=1)
        else:
            ax.text(0.5, 0.5, f"No {title.lower()} data", ha="center", va="center")
        ax.set_xlabel("Cumulative planned dynamics (ns)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25)

    vol_x, vol_y = _concat_stage_series(stages, "VOLUME")
    if vol_x:
        ax_volume.plot(vol_x, np.asarray(vol_y) / 1.0e6, color="#5f3dc4", lw=1.4, label="ENERGY")
    # XST has sparse restart/box records; overlay where available.
    offset = 0.0
    for s in stages:
        steps, vols = _parse_xst(out_dir / f"{s.name}.xst")
        if steps and vols:
            ax_volume.scatter(
                [offset + st * 1.0e-6 for st in steps],
                np.asarray(vols) / 1.0e6,
                s=16,
                color="#2f9e44",
                alpha=0.8,
            )
        offset += s.planned_steps * 1.0e-6
    ax_volume.set_xlabel("Cumulative planned dynamics (ns)")
    ax_volume.set_ylabel("10^6 A^3")
    ax_volume.set_title("Cell Volume")
    ax_volume.grid(alpha=0.25)

    # Health.
    hx, c1, wc, passed = [], [], [], []
    for idx, s in enumerate(stages):
        rec = latest_health.get(s.name)
        if not rec:
            continue
        h = rec.get("health", {})
        hx.append(idx)
        c1.append((h.get("c1_paired_fraction") or 0.0) * 100)
        wc.append((h.get("wc_ref_relative_fraction") or 0.0) * 100)
        passed.append(bool(rec.get("passed")))
    if hx:
        ax_health.plot(hx, c1, "o-", color="#1c7ed6", label="C1' paired")
        ax_health.plot(hx, wc, "s-", color="#f08c00", label="WC ref-relative")
        for x, ok in zip(hx, passed):
            ax_health.axvline(x, color="#2b8a3e" if ok else "#c92a2a", alpha=0.12, lw=8)
        ax_health.axhline(85, color="#868e96", ls=":", lw=1, label="85% guide")
        ax_health.set_xticks(hx, [stages[i].name.replace("F027_", "") for i in hx], rotation=25, ha="right", fontsize=8)
        ax_health.set_ylim(0, 105)
        ax_health.set_ylabel("%")
        ax_health.legend(loc="lower right", ncol=3, fontsize=8)
    else:
        ax_health.text(0.5, 0.5, "No health records yet", ha="center", va="center")
    ax_health.set_title("Health Gates and Warnings")
    ax_health.grid(axis="y", alpha=0.25)

    # Text summary.
    ax_text.axis("off")
    current_stage = progress["current_stage"] or "none"
    failed_stage = progress.get("failed_stage")
    eta = _format_duration(progress["eta_days"])
    stage_eta = _format_duration(progress["current_stage_eta_days"])
    latest_rate = progress["latest_ns_per_day"]
    latest_rate_s = f"{latest_rate:.3f} ns/day" if latest_rate else "n/a"
    gpu_s = "GPU n/a"
    if gpu:
        gpu_s = (
            f"GPU {gpu.get('gpu_util_pct', 0):.0f}% SM, "
            f"{gpu.get('power_w', 0):.0f}/{gpu.get('power_limit_w', 0):.0f} W, "
            f"{gpu.get('mem_used_mb', 0):.0f}/{gpu.get('mem_total_mb', 0):.0f} MB"
        )
    fatal = [f"{s.name}: {','.join(s.fatal_markers)}" for s in stages if s.fatal_markers]
    summary_lines = [
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Package: {package_dir}",
        f"Current stage: {current_stage}",
        f"Failed stage: {failed_stage or 'none'}",
        f"Latest rate: {latest_rate_s}",
        f"Current stage ETA: {stage_eta}",
        f"Full manifest ETA: {eta}"
        + (f" (completion ~ {progress['estimated_completion']})" if progress["estimated_completion"] else ""),
        f"Remaining planned dynamics: {progress['remaining_ns']:.3f} ns",
        gpu_s,
        "Fatal markers: " + ("; ".join(fatal) if fatal else "none"),
    ]
    ax_text.text(
        0.01,
        0.95,
        "\n".join(summary_lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=10,
        bbox=dict(facecolor="#f8f9fa", edgecolor="#dee2e6", boxstyle="round,pad=0.6"),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)

    summary = {
        "generated_at": time.time(),
        "package_dir": str(package_dir),
        "plot": str(out_path),
        "current_stage": progress["current_stage"],
        "failed_stage": progress["failed_stage"],
        "latest_ns_per_day": progress["latest_ns_per_day"],
        "progress_fraction": progress["progress_fraction"],
        "remaining_ns": progress["remaining_ns"],
        "eta_days": progress["eta_days"],
        "current_stage_eta_days": progress["current_stage_eta_days"],
        "estimated_completion": progress["estimated_completion"],
        "gpu": gpu,
        "stages": [
            {
                "name": s.name,
                "done": s.done,
                "started": s.started,
                "planned_steps": s.planned_steps,
                "current_step": s.current_step,
                "ns_per_day": s.ns_per_day,
                "fatal_markers": s.fatal_markers,
            }
            for s in stages
        ],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    args = ap.parse_args()

    package_dir = args.package_dir.resolve()
    out = args.out or (package_dir / "output" / "F027_run_status.png")
    summary = args.summary or (package_dir / "output" / "F027_run_status_summary.json")
    result = _plot_dashboard(package_dir, out, summary)
    print(f"wrote {result['plot']}")
    print(
        "current={current_stage} rate={rate:.3f} ns/day eta={eta}".format(
            current_stage=result.get("current_stage"),
            rate=result.get("latest_ns_per_day") or 0.0,
            eta=_format_duration(result.get("eta_days")),
        )
    )


if __name__ == "__main__":
    main()
