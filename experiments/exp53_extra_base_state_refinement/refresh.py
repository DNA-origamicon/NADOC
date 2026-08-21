#!/usr/bin/env python3
"""Refresh exp53 inventory, metric dumps, validation and state reports."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
CONFIG = HERE / "inventory.json"


def load_sources(part=None):
    cfg = json.loads(CONFIG.read_text())
    excluded = set(cfg.get("exclude_parts", []))
    sources = [s for s in cfg["sources"] if s.get("enabled", True)
               and s["part"] not in excluded and (not part or s["part"] == part)]
    return cfg, sources


def package_info(source):
    job = Path(source["job"])
    meta = json.loads((job / "job.json").read_text())
    stem = meta["name_stem"]
    pkg = job / meta["package_subdir"]
    def piece_order(path):
        match = re.search(r"\.cont(\d+)\.dcd$", path.name)
        return 0 if match is None else int(match.group(1)) + 1

    dcds = sorted((pkg / "output").glob("*production*.dcd"), key=piece_order)
    if not dcds:
        raise FileNotFoundError(f"no production DCD under {pkg}")
    return job, stem, pkg, dcds


def inventory(part=None):
    cfg, sources = load_sources(part)
    rows = []
    for source in sources:
        try:
            job, stem, pkg, dcds = package_info(source)
            rows.append({**source, "available": True, "stem": stem,
                         "dcds": [str(p) for p in dcds],
                         "dcd_bytes": sum(p.stat().st_size for p in dcds),
                         "dcd_mtime_ns": max(p.stat().st_mtime_ns for p in dcds),
                         "package": str(pkg)})
        except (FileNotFoundError, KeyError) as exc:
            rows.append({**source, "available": False, "reason": str(exc)})
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "inventory.json"
    path.write_text(json.dumps({"schema": "nadoc.exp53.scan.v1", "sources": rows}, indent=2)+"\n")
    print(path)
    return cfg, rows


def slug(source):
    return f"{source['part']}__{source['role']}"


def validate(rows):
    for source in rows:
        if not source.get("available"):
            continue
        out = RESULTS / f"{slug(source)}__topology.txt"
        psf = Path(source["package"]) / f"{source['stem']}_hmr.psf"
        pdb = Path(source["package"]) / f"{source['stem']}.pdb"
        cmd = [sys.executable, str(ROOT / "scripts/check_ring_piercing_frame.py"),
               str(psf), str(pdb), "--quiet"]
        run = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        out.write_text("$ " + " ".join(cmd) + "\n" + run.stdout + run.stderr)
        print(out, "PASS" if run.returncode == 0 else "FAIL")


def extract(cfg, rows, force=False):
    for source in rows:
        if not source.get("available"):
            continue
        target = int(source.get("target_samples", cfg["extraction"]["target_samples"]))
        out = RESULTS / f"{slug(source)}__metrics.json"
        sig = RESULTS / f"{slug(source)}__metrics.signature.json"
        current = {"dcds": source["dcds"], "bytes": source["dcd_bytes"],
                   "mtime_ns": source["dcd_mtime_ns"], "target_samples": target,
                   "local_minimum_image": bool(source.get("local_minimum_image"))}
        if not force and out.exists() and sig.exists() and json.loads(sig.read_text()) == current:
            print(out, "cached")
            continue
        # MDAnalysis exposes the exact frame count only after opening the DCD. Use its
        # lightweight reader once to choose a bounded stride before the expensive pass.
        import MDAnalysis as mda
        u = mda.Universe(str(Path(source["package"]) / f"{source['stem']}_hmr.psf"),
                         *source["dcds"])
        stride = max(1, len(u.trajectory) // target)
        cmd = [sys.executable, str(ROOT / "experiments/exp46_xb_placement/xb_observables.py"),
               "--job", source["job"], "--dcd", *source["dcds"], "--stride", str(stride),
               "--out", str(out)]
        if source.get("local_minimum_image"):
            cmd.append("--local-minimum-image")
        subprocess.run(cmd, cwd=ROOT, check=True)
        sig.write_text(json.dumps(current, indent=2) + "\n")
        print(out)


def analyse(rows):
    for source in rows:
        dump = RESULTS / f"{slug(source)}__metrics.json"
        if not dump.exists():
            continue
        out = RESULTS / f"{slug(source)}__states.json"
        cmd = [sys.executable, str(HERE / "analyse.py"), str(dump), "--out", str(out)]
        subprocess.run(cmd, cwd=ROOT, check=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("inventory", "validate", "extract", "analyse", "all"))
    ap.add_argument("--part")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    cfg, rows = inventory(args.part)
    if args.command in ("validate", "all"):
        validate(rows)
    if args.command in ("extract", "all"):
        extract(cfg, rows, args.force)
    if args.command in ("analyse", "all"):
        analyse(rows)


if __name__ == "__main__":
    main()
