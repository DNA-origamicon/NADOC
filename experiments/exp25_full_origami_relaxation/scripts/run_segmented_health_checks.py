#!/usr/bin/env python3
"""Run segmented NAMD stages and trigger health checks after each segment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASEPAIR = ROOT / "experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py"
WC = ROOT / "experiments/exp25_full_origami_relaxation/scripts/watson_crick_monitor.py"


def run(cmd: list[str], cwd: Path, log: Path | None = None) -> int:
    if log is None:
        return subprocess.run(cmd, cwd=cwd).returncode
    with log.open("w") as handle:
        proc = subprocess.run(cmd, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    return proc.returncode


def health_check(package_dir: Path, name: str, min_c1: float, min_wc: float) -> dict:
    dcd = package_dir / "output" / f"{name}.dcd"
    c1_jsonl = package_dir / "output" / f"{name}_basepair_monitor.jsonl"
    wc_json = package_dir / "output" / f"{name}_watson_crick_monitor.json"
    c1_cmd = [
        sys.executable,
        str(BASEPAIR),
        "--psf", "B_tube.psf",
        "--pdb", "B_tube.pdb",
        "--dcd", str(dcd.relative_to(package_dir)),
        "--out-jsonl", str(c1_jsonl.relative_to(package_dir)),
        "--safe-back", "0",
        "--paired-max-ang", "13.0",
        "--min-paired", str(min_c1),
        "--grace-frames", "1",
    ]
    c1_rc = run(c1_cmd, package_dir)
    wc_cmd = [
        sys.executable,
        str(WC),
        "--psf", "B_tube.psf",
        "--ref-pdb", "B_tube.pdb",
        "--dcd", str(dcd.relative_to(package_dir)),
        "--frame", "-1",
        "--out", str(wc_json.relative_to(package_dir)),
    ]
    wc_rc = run(wc_cmd, package_dir)
    wc_data = json.loads(wc_json.read_text()) if wc_json.exists() else {}
    c1_records = [
        json.loads(line) for line in c1_jsonl.read_text().splitlines()
        if line.strip().startswith("{")
    ] if c1_jsonl.exists() else []
    c1_final = c1_records[-1] if c1_records else {}
    wc_fraction = float(wc_data.get("ref_relative_paired_fraction", 0.0))
    ok = c1_rc == 0 and wc_rc == 0 and wc_fraction >= min_wc
    return {
        "name": name,
        "ok": ok,
        "c1_rc": c1_rc,
        "wc_rc": wc_rc,
        "c1_final": c1_final,
        "wc_final": wc_data,
        "min_c1": min_c1,
        "min_wc": min_wc,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    ap.add_argument("--manifest", default="F018_manifest.json")
    ap.add_argument("--namd", default="/home/jojo/Applications/NAMD_3.0.2/namd3")
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--pemap", default="0-15")
    ap.add_argument("--devices", default="0")
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--max-segments", type=int, default=0, help="0 means all segments.")
    ap.add_argument("--min-c1", type=float, default=0.90)
    ap.add_argument("--min-wc", type=float, default=0.85)
    args = ap.parse_args()
    namd_args = [args.namd, f"+p{args.threads}", "+setcpuaffinity"]
    if args.pemap:
        namd_args += ["+pemap", args.pemap]

    package_dir = args.package_dir.resolve()
    manifest = json.loads((package_dir / args.manifest).read_text())
    stages = manifest["stages"][args.start_index:]
    if args.max_segments:
        stages = stages[:args.max_segments]

    report_path = package_dir / "output" / args.manifest.replace("_manifest.json", "_health_report.jsonl")
    report_path.parent.mkdir(exist_ok=True)

    if args.start_index == 0 and (package_dir / f"{manifest['minimization']['name']}.conf").exists():
        min_name = manifest["minimization"]["name"]
        min_log = package_dir / f"{min_name}.log"
        if not (package_dir / "output" / f"{min_name}.coor").exists():
            rc = run(
                [*namd_args, "+devices", args.devices, f"{min_name}.conf"],
                package_dir,
                min_log,
            )
            if rc != 0:
                raise SystemExit(f"Minimization failed: {min_name} rc={rc}")

    for stage in stages:
        name = stage["name"]
        print(f"RUN {name} ({stage['percent']}% of {stage['stage']})", flush=True)
        rc = run(
            [*namd_args, "+devices", args.devices, f"{name}.conf"],
            package_dir,
            package_dir / f"{name}.log",
        )
        if rc != 0:
            rec = {"name": name, "ok": False, "namd_rc": rc, "error": "NAMD failed"}
            with report_path.open("a") as out:
                out.write(json.dumps(rec) + "\n")
            raise SystemExit(f"NAMD failed: {name} rc={rc}")
        rec = health_check(package_dir, name, args.min_c1, args.min_wc)
        with report_path.open("a") as out:
            out.write(json.dumps(rec) + "\n")
        c1_pct = rec.get("c1_final", {}).get("paired_percent")
        wc_pct = rec.get("wc_final", {}).get("ref_relative_paired_percent")
        print(f"HEALTH {name}: ok={rec['ok']} C1={c1_pct} WC={wc_pct}", flush=True)
        if not rec["ok"]:
            raise SystemExit(f"Health check failed after {name}")


if __name__ == "__main__":
    main()
