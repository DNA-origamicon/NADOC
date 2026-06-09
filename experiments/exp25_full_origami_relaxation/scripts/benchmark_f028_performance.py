#!/usr/bin/env python3
"""Create and optionally run F028 NAMD performance benchmark variants.

The script benchmarks from the latest F028 restart so settings can be compared
against the real B-tube system without modifying the production outputs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F028_aksimentiev_exact_btube/B_tube_namd_solvated"
)
DEFAULT_NAMD = Path("/home/jojo/Applications/NAMD_3.0.2/namd3")


@dataclass(frozen=True)
class Variant:
    name: str
    threads: int
    pemap: str | None
    notes: str


VARIANTS = [
    Variant("p8_ccd0", 8, "0-7", "One L3/CCD, physical cores only."),
    Variant("p8_ccd1", 8, "8-15", "Other L3/CCD, physical cores only."),
    Variant("p12_phys_0_11", 12, "0-11", "Twelve physical cores, crosses CCDs lightly."),
    Variant("p12_phys_0_15", 12, "0-15", "Twelve PEs placed over all physical cores."),
    Variant("p16_phys", 16, "0-15", "All physical cores, no SMT."),
    Variant("p24_phys_smt", 24, "0-31", "Allows SMT; checks whether more PEs beat locality."),
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def latest_stage_prefix(run_dir: Path, preferred_stage: str) -> str:
    preferred = run_dir / "output" / f"{preferred_stage}.restart.coor"
    if preferred.exists():
        return f"output/{preferred_stage}.restart"
    candidates = sorted((run_dir / "output").glob("*.restart.coor"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"No restart coordinate files found under {run_dir / 'output'}")
    return f"output/{candidates[-1].name.removesuffix('.coor')}"


def live_f028_process() -> str | None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-fa", r"namd3 \+p.*equil_k0\.5\.namd"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return out or None


def make_benchmark_config(base: str, stage: str, input_prefix: str, out_prefix: str, steps: int) -> str:
    text = base
    text = re.sub(r"^outputName\s+.*$", f"outputName         {out_prefix}", text, flags=re.M)
    text = re.sub(r"^dcdFile\s+.*$", f"dcdFile            {out_prefix}.dcd", text, flags=re.M)
    text = re.sub(r"^xstFile\s+.*$", f"xstFile            {out_prefix}.xst", text, flags=re.M)
    text = re.sub(r"^set input\s+.*$", f"set input          {input_prefix}", text, flags=re.M)
    text = re.sub(r"^run\s+\d+.*$", f"run                {steps}", text, flags=re.M)
    text = re.sub(r"^outputEnergies\s+.*$", "outputEnergies     5000", text, flags=re.M)
    text = re.sub(r"^outputPressure\s+.*$", "outputPressure     5000", text, flags=re.M)
    text = re.sub(r"^xstFreq\s+.*$", "xstFreq            5000", text, flags=re.M)
    text = re.sub(r"^dcdFreq\s+.*$", "dcdFreq            5000", text, flags=re.M)
    text = re.sub(r"^restartfreq\s+.*$", "restartfreq        5000", text, flags=re.M)
    return text


def parse_log(log_path: Path) -> dict[str, float | int | None]:
    ns_day = None
    sec_step = None
    step = None
    if not log_path.exists():
        return {"step": None, "ns_per_day": None, "sec_per_step": None}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"PERFORMANCE:\s+(\d+)\s+averaging\s+([\d.]+)\s+ns/day,\s+([\d.]+)\s+sec/step", line)
        if m:
            step = int(m.group(1))
            ns_day = float(m.group(2))
            sec_step = float(m.group(3))
        m = re.search(r"Benchmark time:\s+\d+\s+CPUs\s+([\d.]+)\s+s/step\s+([\d.]+)\s+days/ns", line)
        if m:
            sec_step = float(m.group(1))
            days_ns = float(m.group(2))
            ns_day = 1.0 / days_ns if days_ns else None
    return {"step": step, "ns_per_day": ns_day, "sec_per_step": sec_step}


def run_variant(namd: Path, run_dir: Path, conf: Path, variant: Variant, benchmark_time: int, output_timing: int, log: Path) -> int:
    cmd = [str(namd), f"+p{variant.threads}", "+setcpuaffinity"]
    if variant.pemap:
        cmd += ["+pemap", variant.pemap]
    cmd += ["--outputTiming", str(output_timing), "--benchmarkTime", str(benchmark_time), str(conf)]
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            cmd,
            cwd=run_dir,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return proc.wait(timeout=benchmark_time + 60)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                return proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                return 124


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--namd", type=Path, default=DEFAULT_NAMD)
    parser.add_argument("--stage", default="equil_k0.5")
    parser.add_argument("--steps", type=int, default=9600)
    parser.add_argument(
        "--benchmark-time",
        type=int,
        default=300,
        help="NAMD benchmark wall-clock time in seconds.",
    )
    parser.add_argument("--execute", action="store_true", help="Run benchmarks after writing configs.")
    parser.add_argument("--allow-concurrent", action="store_true", help="Allow running while F028 production is active.")
    args = parser.parse_args()
    if args.steps % 12 != 0:
        raise SystemExit("--steps must be divisible by F028 stepspercycle=12")

    if args.execute and not args.allow_concurrent:
        live = live_f028_process()
        if live:
            raise SystemExit(
                "F028 NAMD appears active; refusing concurrent benchmark. "
                "Stop/checkpoint it first or pass --allow-concurrent.\n" + live
            )

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bench_root = args.run_dir / "performance_benchmarks" / stamp
    bench_root.mkdir(parents=True, exist_ok=True)

    base_conf = read_text(args.run_dir / f"{args.stage}.namd")
    input_prefix = latest_stage_prefix(args.run_dir, args.stage)
    manifest = {
        "run_dir": str(args.run_dir),
        "stage": args.stage,
        "input_prefix": input_prefix,
        "benchmark_time_s": args.benchmark_time,
        "steps": args.steps,
        "variants": [],
    }

    for variant in VARIANTS:
        out_dir = bench_root / variant.name
        out_dir.mkdir()
        conf = args.run_dir / f"benchmark_{stamp}_{variant.name}.namd"
        out_prefix = f"{out_dir.relative_to(args.run_dir)}/output/{variant.name}"
        (out_dir / "output").mkdir()
        conf.write_text(
            make_benchmark_config(base_conf, args.stage, input_prefix, out_prefix, args.steps),
            encoding="utf-8",
        )
        record = asdict(variant) | {"conf": str(conf), "log": str(out_dir / f"{variant.name}.log")}
        if args.execute:
            rc = run_variant(
                args.namd,
                args.run_dir,
                conf,
                variant,
                args.benchmark_time,
                args.steps,
                out_dir / f"{variant.name}.log",
            )
            record["returncode"] = rc
            record.update(parse_log(out_dir / f"{variant.name}.log"))
        manifest["variants"].append(record)

    manifest_path = bench_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
