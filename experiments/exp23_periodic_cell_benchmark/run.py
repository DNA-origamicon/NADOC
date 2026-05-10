"""
Exp23 — B_tube Periodic Unit Cell MD Benchmark
===============================================
Builds a 1-period (21 bp) periodic unit cell package for B_tube, runs a
5,000-step NAMD CUDASOAintegrate benchmark, and reports ns/day alongside
the reference results from exp22 (vacuum PME and GBIS implicit solvent).

Design
------
B_tube: 24 helices × 305 bp, HONEYCOMB lattice
  Full solvated (namd_solvate): ~2.46M atoms → OOM on 16 GB machine
  Periodic cell (1 period):     ~170k atoms  → 14–20× speedup expected

Method
------
One 21 bp crossover-repeat period is simulated with:
  - Axial PBC: Z cell = 21 × 0.334 = 7.014 nm (exact repeat period)
  - XY solvated with TIP3P water + 150 mM NaCl (semiisotropic NPT)
  - 48 wrap bonds (O3'→P at each helix boundary, both strands)
  - CUDASOAintegrate (GPU-resident, same as solvated benchmark)

Benchmark
---------
  D1  NAMD3 periodic cell (1 period, ~170k atoms)

Reference (from exp22)
---------
  A1  GROMACS vacuum PME         8.40 ns/day  (462k atoms)
  B2  NAMD3 GBIS implicit solv.  2.36 ns/day  (289k atoms)

Usage
-----
    python experiments/exp23_periodic_cell_benchmark/run.py [--skip-build] [--n-steps N]

Outputs (written to results/)
------------------------------
    benchmark_results.json    — timing data
    benchmark_summary.txt     — human-readable table
    periodic_cell_run/        — extracted NAMD package
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.core.periodic_cell import build_periodic_cell_package, get_periodic_cell_stats

RESULTS_DIR = Path(__file__).parent / "results"
NADOC_FILE  = ROOT / "workspace" / "B_tube.nadoc"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _load_design() -> Design:
    if not NADOC_FILE.exists():
        raise FileNotFoundError(f"Design file not found: {NADOC_FILE}")
    return Design.model_validate_json(NADOC_FILE.read_text())


def _find_namd3() -> str:
    for candidate in ("namd3",
                       str(Path.home() / "Applications/NAMD_3.0.2/namd3"),
                       str(Path.home() / "Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3")):
        if Path(candidate).exists() or os.path.isfile(candidate):
            return candidate
    # Try shutil
    import shutil
    p = shutil.which("namd3")
    if p:
        return p
    raise RuntimeError("namd3 not found in PATH or ~/Applications/NAMD_3.0.2/")


def _patch_conf_for_bench(conf_path: Path, n_steps: int) -> None:
    """Replace minimize+run block with a fixed-step benchmark run."""
    text = conf_path.read_text()
    # Remove existing minimize / reinitvels / run lines
    lines = []
    for ln in text.splitlines():
        stripped = ln.strip().lower()
        if (stripped.startswith("minimize")
                or stripped.startswith("reinitvels")
                or stripped.startswith("run ")):
            continue
        lines.append(ln)
    lines.append("minimize           500        ;# pre-benchmark EM (not timed)")
    lines.append("reinitvels         310")
    lines.append(f"run                {n_steps}       ;# benchmark steps")
    conf_path.write_text("\n".join(lines) + "\n")


def _ns_per_day_from_log(log_path: Path, n_steps: int, timestep_fs: float = 2.0) -> float:
    """Parse NAMD log for timing; return ns/day."""
    text = log_path.read_text()

    # NAMD3 CUDASOAintegrate prints "Benchmark time: X days/ns Y ns/day"
    m = re.search(r"(\d+[\d.]*)\s+ns/day", text)
    if m:
        return float(m.group(1))

    # Fall back: find WallClock (seconds) from two TIMING lines
    timing = re.findall(r"^TIMING:\s+(\d+)\s+.*?(\d+\.\d+)\s*$", text, re.MULTILINE)
    if len(timing) >= 2:
        step0, wall0 = int(timing[0][0]),  float(timing[0][1])
        step1, wall1 = int(timing[-1][0]), float(timing[-1][1])
        if step1 > step0:
            wall_s = wall1 - wall0
            sim_ns = (step1 - step0) * timestep_fs * 1e-6
            return sim_ns / (wall_s / 86400.0)

    # Last resort: grep WallClock from the final "End of program" block
    m2 = re.search(r"WallClock:\s+([\d.]+)", text)
    if m2:
        wall_s = float(m2.group(1))
        sim_ns = n_steps * timestep_fs * 1e-6
        return sim_ns / (wall_s / 86400.0)

    return float("nan")


# ══════════════════════════════════════════════════════════════════════════════
# Build
# ══════════════════════════════════════════════════════════════════════════════


def build_package(design: Design, run_dir: Path) -> dict:
    """Build periodic cell package and extract into run_dir."""
    print("\n[BUILD] get_periodic_cell_stats …")
    t0 = time.time()
    stats = get_periodic_cell_stats(design)
    print(f"  bp range    : [{stats['bp_start']}, {stats['bp_end']})")
    print(f"  periodic Z  : {stats['periodic_z_nm']:.4f} nm")
    print(f"  wrap bonds  : {stats['n_wrap_bonds']}")
    print(f"  crossovers  : {stats['n_crossovers']}")
    print(f"  DNA atoms   : {stats['dna_atoms']:,}")
    print(f"  water atoms : {stats['water_atoms']:,}")
    print(f"  Na / Cl     : {stats['n_na']} / {stats['n_cl']}")
    print(f"  total atoms : {stats['total_atoms']:,}")
    print(f"  box (nm)    : {stats['box_nm'][0]:.3f} × {stats['box_nm'][1]:.3f} × {stats['box_nm'][2]:.3f}")
    print(f"  stats time  : {time.time() - t0:.1f} s")

    print("\n[BUILD] build_periodic_cell_package …")
    t0 = time.time()
    zip_bytes = build_periodic_cell_package(design)
    print(f"  build time  : {time.time() - t0:.1f} s")

    run_dir.mkdir(parents=True, exist_ok=True)
    zip_path = RESULTS_DIR / "periodic_cell.zip"
    zip_path.write_bytes(zip_bytes)

    # Extract ZIP
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parts = Path(member.filename).parts
            if len(parts) > 1:
                rel = Path(*parts[1:])  # strip top-level ZIP folder
            else:
                continue
            dest = run_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member.filename))
            mode = (member.external_attr >> 16) & 0o777
            if mode:
                if dest.suffix in (".sh", ".py") and not (mode & 0o111):
                    mode = 0o755
                dest.chmod(mode)
            elif dest.suffix in (".sh", ".py"):
                dest.chmod(0o755)
    print(f"  extracted to: {run_dir}")

    return stats


def _restore_file_from_zip(run_dir: Path, rel_path: str) -> None:
    """Restore one package file from the saved ZIP if present."""
    zip_path = RESULTS_DIR / "periodic_cell.zip"
    if not zip_path.exists():
        return
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parts = Path(member.filename).parts
            if len(parts) > 1 and Path(*parts[1:]) == Path(rel_path):
                (run_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)
                (run_dir / rel_path).write_bytes(zf.read(member.filename))
                return


def _restore_run_configs_from_zip(run_dir: Path) -> None:
    """Restore generated configs from ZIP so benchmark patches start clean."""
    for rel in (
        "namd.conf",
        "equilibrate_npt.conf",
        "relax_locked_nvt.template.conf",
        "production_locked_nvt.template.conf",
        "benchmark_standard_cuda.conf",
        "benchmark_gpu_resident.conf",
    ):
        _restore_file_from_zip(run_dir, rel)
    zip_path = RESULTS_DIR / "periodic_cell.zip"
    if not zip_path.exists():
        return
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parts = Path(member.filename).parts
            if len(parts) > 1 and parts[-1].startswith("ramp_locked_nvt_") and parts[-1].endswith(".template.conf"):
                rel = Path(*parts[1:])
                dest = run_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member.filename))


def _generated_name(run_dir: Path) -> str:
    pdbs = sorted(run_dir.glob("*_periodic_*x.pdb"))
    if not pdbs:
        raise FileNotFoundError(f"No periodic PDB found in {run_dir}")
    return pdbs[0].stem


# ══════════════════════════════════════════════════════════════════════════════
# Benchmark
# ══════════════════════════════════════════════════════════════════════════════


def run_namd_bench(run_dir: Path, n_steps: int, tag: str, conf_name: str) -> dict:
    """Run NAMD benchmark; return dict with ns_per_day and wall_s."""
    namd = _find_namd3()
    conf_path = run_dir / conf_name

    if not conf_path.exists():
        raise FileNotFoundError(f"namd.conf not found in {run_dir}")

    _patch_conf_for_bench(conf_path, n_steps)
    (run_dir / "output").mkdir(exist_ok=True)

    log_path = RESULTS_DIR / f"{tag}_namd.log"
    print(f"\n[RUN] {tag} — {n_steps} steps using {conf_name} …")
    t0 = time.time()

    cmd = [namd, "+p16", "+devices", "0", conf_name]
    result = subprocess.run(
        cmd,
        cwd=str(run_dir),
        capture_output=False,
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
    )
    wall_s = time.time() - t0

    if result.returncode != 0:
        print(f"  NAMD exited with code {result.returncode}; check {log_path}")

    ns_day = _ns_per_day_from_log(log_path, n_steps)
    print(f"  wall time   : {wall_s:.1f} s")
    print(f"  ns/day      : {ns_day:.2f}")

    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    warnings = []
    if result.returncode != 0:
        warnings.append(f"exit_code_{result.returncode}")
    if "FATAL ERROR" in log_text:
        warnings.append("FATAL ERROR")
    if "Low global CUDA exclusion count!" in log_text and "System unstable" in log_text:
        warnings.append("fatal_low_cuda_exclusion")
    if "out of memory" in log_text.lower():
        warnings.append("cuda_out_of_memory")
    if "Low global CUDA exclusion count!" in log_text and not warnings:
        warnings.append("minimization_low_cuda_exclusion")

    return {
        "tag": tag,
        "conf": conf_name,
        "n_steps": n_steps,
        "wall_s": wall_s,
        "ns_per_day": ns_day,
        "warnings": warnings,
    }


def _patch_conf_for_production(conf_path: Path, n_steps: int) -> None:
    """Replace run steps; enforce binary restart and checkpoint freq for production."""
    text = conf_path.read_text()
    lines = []
    for ln in text.splitlines():
        s = ln.strip().lower()
        if s.startswith("run "):
            lines.append(f"run                {n_steps}       ;# production")
        elif s.startswith("binaryrestart"):
            lines.append("binaryrestart      yes")
        elif s.startswith("restartfreq"):
            lines.append("restartfreq        50000")
        else:
            lines.append(ln)
    conf_path.write_text("\n".join(lines) + "\n")


def _patch_conf_for_continuation(conf_path: Path, output_base: str, first_step: int) -> None:
    """Replace minimize/reinitvels/temperature with a restart block for run continuation."""
    text = conf_path.read_text()
    restart_block_written = False
    lines = []
    for ln in text.splitlines():
        s = ln.strip().lower()
        # Strip any pre-existing coordinate/system restart directives to avoid duplicates
        if s.startswith("bincoordinates") or s.startswith("binvelocities") or s.startswith("extendedsystem") or s.startswith("firsttimestep"):
            continue
        if s.startswith("minimize") or s.startswith("reinitvels") or s.startswith("temperature "):
            if not restart_block_written:
                lines += [
                    f"bincoordinates     {output_base}.restart.coor",
                    f"binvelocities      {output_base}.restart.vel",
                    f"extendedSystem     {output_base}.restart.xsc",
                    f"firsttimestep      {first_step}",
                ]
                restart_block_written = True
            continue
        lines.append(ln)
    conf_path.write_text("\n".join(lines) + "\n")


def run_namd_production(run_dir: Path, n_steps: int) -> None:
    """Run or continue a production NAMD simulation in run_dir."""
    namd   = _find_namd3()
    conf_path = run_dir / "production_locked_nvt.conf"
    if not conf_path.exists():
        conf_path = run_dir / "production_locked_nvt.template.conf"

    if not conf_path.exists():
        raise FileNotFoundError(f"production_locked_nvt.conf not found in {run_dir}")

    (run_dir / "output").mkdir(exist_ok=True)

    # Determine output base name from conf
    output_name = None
    for ln in conf_path.read_text().splitlines():
        if ln.strip().lower().startswith("outputname"):
            output_name = ln.split()[-1]
            break
    if output_name is None:
        raise RuntimeError("Could not find outputName in namd.conf")

    restart_coor = run_dir / f"{output_name}.restart.coor"
    continuing   = restart_coor.exists()

    if continuing:
        # Read first step from the XSC restart file
        xsc_path = run_dir / f"{output_name}.restart.xsc"
        first_step = 0
        if xsc_path.exists():
            for ln in xsc_path.read_text().splitlines():
                if not ln.startswith("#") and ln.strip():
                    first_step = int(ln.split()[0])
                    break
        sim_ns_done = first_step * 2e-6
        print(f"\n[PRODUCTION] Continuing from step {first_step:,} ({sim_ns_done:.3f} ns) …")
        _patch_conf_for_production(conf_path, n_steps)
        _patch_conf_for_continuation(conf_path, output_name, first_step)
    else:
        print(f"\n[PRODUCTION] Starting new production run ({n_steps:,} steps, {n_steps*2e-6:.1f} ns) …")
        _patch_conf_for_production(conf_path, n_steps)

    log_path = RESULTS_DIR / "production_namd.log"
    print(f"  log         : {log_path}")
    print(f"  output base : {run_dir / output_name}")
    print(f"  tail -f {log_path}   # to monitor")

    cmd = [namd, "+p16", "+devices", "0", conf_path.name]
    result = subprocess.run(
        cmd,
        cwd=str(run_dir),
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        print(f"\n  NAMD exited with code {result.returncode}; check {log_path}")
    else:
        print(f"\n  Done. Check {log_path} for energies and timing.")


# ══════════════════════════════════════════════════════════════════════════════
# Restraint-ramp smoke workflow
# ══════════════════════════════════════════════════════════════════════════════


def _replace_or_append_conf_line(text: str, key: str, value: str) -> str:
    """Replace a NAMD config directive by key, preserving rough file order."""
    out = []
    replaced = False
    key_l = key.lower()
    for line in text.splitlines():
        if line.strip().lower().startswith(key_l):
            out.append(value)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(value)
    return "\n".join(out) + "\n"


def _patch_conf_for_smoke(conf_path: Path, *, run_steps: int, minimize_steps: int = 500) -> None:
    """Shorten a generated phase config for quick restraint-ramp smoke tests."""
    text = conf_path.read_text()
    replacements = {
        "minimize": f"minimize           {minimize_steps}",
        "run": f"run                {run_steps}",
        "outputEnergies": "outputEnergies     500",
        "dcdFreq": "dcdFreq            1000",
        "xstFreq": "xstFreq            500",
        "restartfreq": f"restartfreq        {run_steps}",
    }
    for key, value in replacements.items():
        text = _replace_or_append_conf_line(text, key, value)
    conf_path.write_text(text)


def _lock_template(run_dir: Path, template: str, out_name: str, z_angstrom: float) -> dict:
    """Patch one locked-cell template from the NPT XST and return lock metadata."""
    xst = run_dir / "output" / f"{_generated_name(run_dir)}_equilibrate_npt.xst"
    cmd = [
        sys.executable,
        "scripts/lock_box_from_xst.py",
        "--xst", str(xst),
        "--template", template,
        "--out", out_name,
        "--z-angstrom", f"{z_angstrom:.3f}",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(run_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"lock_box_from_xst failed for {template}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    meta = {"template": template, "out": out_name, "stdout": result.stdout.strip()}
    m = re.search(r"Locked box: X=([\d.]+) Å\s+Y=([\d.]+) Å\s+Z=([\d.]+) Å", result.stdout)
    if m:
        meta["locked_box_angstrom"] = [float(m.group(i)) for i in range(1, 4)]
    m = re.search(r"Origin:\s+X=([\d.]+) Å\s+Y=([\d.]+) Å\s+Z=([\d.]+) Å", result.stdout)
    if m:
        meta["origin_angstrom"] = [float(m.group(i)) for i in range(1, 4)]
    return meta


def _run_namd_stage(run_dir: Path, conf_name: str, log_name: str, n_threads: int = 16) -> dict:
    """Run one NAMD stage and return process metadata."""
    namd = _find_namd3()
    log_path = run_dir / "output" / log_name
    log_path.parent.mkdir(exist_ok=True)
    print(f"\n[STAGE] {conf_name}")
    t0 = time.time()
    with log_path.open("w") as log_f:
        result = subprocess.run(
            [namd, f"+p{n_threads}", "+devices", "0", conf_name],
            cwd=str(run_dir),
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
    wall_s = time.time() - t0
    print(f"  exit code : {result.returncode}")
    print(f"  wall time : {wall_s:.1f} s")
    return {
        "conf": conf_name,
        "log": str(log_path),
        "returncode": result.returncode,
        "wall_s": wall_s,
    }


def _parse_xst_last(xst_path: Path) -> dict:
    """Return final XST box row fields."""
    if not xst_path.exists():
        return {}
    last = None
    for line in xst_path.read_text(errors="replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 13:
            try:
                last = [float(x) for x in parts[:13]]
            except ValueError:
                pass
    if last is None:
        return {}
    return {
        "step": int(last[0]),
        "a_x": last[1],
        "b_y": last[5],
        "c_z": last[9],
        "origin": [last[10], last[11], last[12]],
        "volume": last[1] * last[5] * last[9],
    }


def _log_health(log_path: Path) -> dict:
    """Extract lightweight pass/fail stats from a NAMD log."""
    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    flags = []
    warnings = []
    if "FATAL ERROR" in text:
        flags.append("fatal_error")
    if "Atoms moving too fast" in text:
        flags.append("atoms_moving_too_fast")
    if "Low global CUDA exclusion count!" in text and "System unstable" in text:
        flags.append("fatal_low_cuda_exclusion")
    if "out of memory" in text.lower():
        flags.append("out_of_memory")
    if "-99999999999.9999" in text:
        flags.append("sentinel_energy")

    try:
        from check_progress import parse_log
        data = parse_log(log_path)
    except Exception:
        data = {}

    stats = {}
    for field in ("TEMP", "POTENTIAL", "PRESSURE", "VOLUME"):
        arr = data.get(field)
        if arr is not None and len(arr):
            stats[field.lower()] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "last": float(arr[-1]),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
            }
    temp = stats.get("temp")
    if temp and (temp["min"] < 250 or temp["max"] > 370):
        warnings.append("temperature_out_of_bounds")
    return {
        "flags": flags,
        "warnings": warnings,
        "energy_frames": int(len(data.get("TS", []))) if data else 0,
        "stats": stats,
    }


def _hardware_summary() -> dict:
    """Best-effort hardware details for reproducibility."""
    out = {}
    try:
        cpu = subprocess.run(
            ["lscpu"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        for key in ("Model name", "CPU(s)"):
            m = re.search(rf"^{re.escape(key)}:\s+(.+)$", cpu, re.MULTILINE)
            if m:
                out[key.lower().replace(" ", "_").replace("(s)", "s")] = m.group(1).strip()
    except Exception:
        pass
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if gpu:
            out["gpu"] = gpu
    except Exception:
        pass
    try:
        namd = subprocess.run(
            [_find_namd3(), "+version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        out["namd"] = (namd.stdout or namd.stderr).splitlines()[:5]
    except Exception:
        pass
    return out


def run_restraint_ramp_smoke(run_dir: Path, stats: dict, *, npt_steps: int, relax_steps: int,
                             ramp_steps: int, prod_steps: int) -> dict:
    """Run a shortened NPT -> locked relaxation -> ramp -> production workflow."""
    _restore_run_configs_from_zip(run_dir)
    name = _generated_name(run_dir)
    z_angstrom = float(stats["periodic_z_nm"]) * 10.0
    output_dir = run_dir / "output"
    output_dir.mkdir(exist_ok=True)

    # Shorten generated configs in place.
    _patch_conf_for_smoke(run_dir / "equilibrate_npt.conf", run_steps=npt_steps)
    npt_meta = _run_namd_stage(run_dir, "equilibrate_npt.conf", "smoke_equilibrate_npt.log")
    if npt_meta["returncode"] != 0:
        stages = [{
            "name": "equilibrate_npt",
            **npt_meta,
            "xst": str(output_dir / f"{name}_equilibrate_npt.xst"),
        }]
        for stage in stages:
            stage["health"] = _log_health(Path(stage["log"]))
            stage["xst_final"] = _parse_xst_last(Path(stage.get("xst", "")))
        summary = {
            "workflow": "periodic_md_restraint_ramp_smoke",
            "design": str(NADOC_FILE),
            "run_dir": str(run_dir),
            "name": name,
            "stats": stats,
            "hardware": _hardware_summary(),
            "lock_metadata": [],
            "stages": stages,
            "passed": False,
        }
        out_path = RESULTS_DIR / "periodic_md_ramp_smoke_summary.json"
        out_path.write_text(json.dumps(summary, indent=2, default=str))
        return summary

    lock_metadata = []
    locked_templates = [
        ("relax_locked_nvt.template.conf", "relax_locked_nvt.conf", relax_steps),
    ]
    for template in sorted(run_dir.glob("ramp_locked_nvt_*.template.conf")):
        locked_templates.append((template.name, template.name.replace(".template.conf", ".conf"), ramp_steps))
    locked_templates.append(("production_locked_nvt.template.conf", "production_locked_nvt.conf", prod_steps))

    for template, out_name, steps in locked_templates:
        lock_metadata.append(_lock_template(run_dir, template, out_name, z_angstrom))
        _patch_conf_for_smoke(run_dir / out_name, run_steps=steps)

    stages: list[dict] = [
        {
            "name": "equilibrate_npt",
            "conf": "equilibrate_npt.conf",
            **npt_meta,
            "xst": str(output_dir / f"{name}_equilibrate_npt.xst"),
        }
    ]
    for template, out_name, _steps in locked_templates:
        stage_name = out_name.removesuffix(".conf")
        meta = _run_namd_stage(run_dir, out_name, f"smoke_{stage_name}.log")
        stages.append({
            "name": stage_name,
            **meta,
            "xst": str(output_dir / f"{name}_{stage_name}.xst"),
            "dcd": str(output_dir / f"{name}_{stage_name}.dcd"),
        })
        if meta["returncode"] != 0:
            break

    for stage in stages:
        log_path = Path(stage["log"])
        stage["health"] = _log_health(log_path)
        stage["xst_final"] = _parse_xst_last(Path(stage.get("xst", "")))
        if stage["name"] != "equilibrate_npt":
            z = stage["xst_final"].get("c_z")
            if z is None or abs(z - z_angstrom) > 0.001:
                stage["health"]["flags"].append("locked_z_drift")

    passed = all(
        stage.get("returncode", 1) == 0 and not stage["health"]["flags"]
        for stage in stages
    )
    summary = {
        "workflow": "periodic_md_restraint_ramp_smoke",
        "design": str(NADOC_FILE),
        "run_dir": str(run_dir),
        "name": name,
        "stats": stats,
        "hardware": _hardware_summary(),
        "lock_metadata": lock_metadata,
        "stages": stages,
        "passed": passed,
    }
    out_path = RESULTS_DIR / "periodic_md_ramp_smoke_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[SUMMARY] ramp smoke {'PASS' if passed else 'FAIL'}")
    print(f"  saved: {out_path}")
    for stage in stages:
        flags = stage["health"]["flags"]
        warnings = stage["health"].get("warnings", [])
        status = "OK" if not flags else ", ".join(flags)
        if warnings:
            status += f"  (warnings: {', '.join(warnings)})"
        print(f"  {stage['name']:<28} {status}")
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════════


def write_summary(stats: dict, benches: list[dict]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)

    # Reference results from exp22
    references = [
        ("A1", "GROMACS vacuum PME",         462_706,  8.40),
        ("B2", "NAMD3 GBIS implicit solv.",   289_470,  2.36),
    ]

    lines = [
        "=" * 72,
        "  B_tube PERIODIC UNIT CELL MD BENCHMARK",
        f"  Design  : B_tube.nadoc  (24 helices, 21 bp × {stats.get('n_periods',1)} period)",
        f"  bp range: [{stats['bp_start']}, {stats['bp_end']})",
        f"  Z cell  : {stats['periodic_z_nm']:.4f} nm (axial PBC)",
        "=" * 72,
        "",
        "  Reference benchmarks (exp22 — full 305 bp B_tube)",
        f"  {'Tag':<8} {'Method':<34} {'atoms':>10}  {'ns/day':>8}",
        "  " + "-" * 65,
    ]
    for tag, method, natoms, ns_day in references:
        lines.append(f"  {tag:<8} {method:<34} {natoms:>10,}  {ns_day:>8.2f}")

    lines += [
        "",
        "  Periodic cell benchmark (exp23 — 1 period, 21 bp)",
        f"  {'Tag':<8} {'Method':<34} {'atoms':>10}  {'ns/day':>8}",
        "  " + "-" * 65,
    ]

    n_atoms = stats.get("total_atoms", 0)
    for bench in benches:
        tag = bench.get("tag", "?")
        method = "NAMD3 periodic cell"
        if "gpu" in tag.lower():
            method += " (GPU-resident probe)"
        else:
            method += " (standard CUDA)"
        ns_day = bench.get("ns_per_day", float("nan"))
        serious = [w for w in bench.get("warnings", []) if w != "minimization_low_cuda_exclusion"]
        warn = "  WARN" if serious else ("  NOTE" if bench.get("warnings") else "")
        lines.append(f"  {tag:<8} {method:<34} {n_atoms:>10,}  {ns_day:>8.2f}{warn}")

    # Speedup vs references
    lines += ["", "  Speedup vs references:"]
    for bench in benches:
        ns_day = bench.get("ns_per_day", float("nan"))
        if not (ns_day and ns_day == ns_day):
            continue
        for ref_tag, method, _, ref_ns in references:
            ratio = ns_day / ref_ns
            lines.append(
                f"  {bench.get('tag')} / {ref_tag}: {ratio:.1f}× faster  "
                f"({ns_day:.2f} / {ref_ns:.2f} ns/day)"
            )

    lines += [
        "",
        f"  Atom count reduction: {max(462_706, 289_470):,} → {n_atoms:,}  "
        f"({max(462_706, 289_470) / max(n_atoms, 1):.1f}× fewer atoms)",
        "",
        "  Notes:",
        "  • Periodic workflow uses restrained NPT for XY discovery, then locked-Z NVT",
        "  • wrapNearest on handles strands that span the periodic boundary",
        "  • Wrap bonds (O3'→P at cell boundary) minimized via image trick",
        "  • GPU-resident probe is trusted only if it has no fatal exclusion/CUDA errors",
        "=" * 72,
    ]

    summary = "\n".join(lines) + "\n"
    print("\n" + summary)
    (RESULTS_DIR / "benchmark_summary.txt").write_text(summary)
    print(f"Saved: {RESULTS_DIR / 'benchmark_summary.txt'}")

    # JSON
    data = {
        "stats":      stats,
        "benchmarks": benches,
        "references": [
            {"tag": t, "method": m, "n_atoms": n, "ns_per_day": ns}
            for t, m, n, ns in references
        ],
    }
    (RESULTS_DIR / "benchmark_results.json").write_text(
        json.dumps(data, indent=2, default=str)
    )
    print(f"Saved: {RESULTS_DIR / 'benchmark_results.json'}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="Exp23: periodic cell MD benchmark + production")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip package build (use existing results/periodic_cell_run/)")
    parser.add_argument("--n-steps",   type=int, default=5000,
                        help="NAMD benchmark steps (default 5000)")
    parser.add_argument("--production", action="store_true",
                        help="Run production MD instead of short benchmark")
    parser.add_argument("--prod-steps", type=int, default=25_000_000,
                        help="Production run steps (default 25000000 = 50 ns at 2 fs)")
    parser.add_argument("--continue-run", action="store_true",
                        help="Continue production from existing restart files in periodic_cell_run/output/")
    parser.add_argument("--gpu-benchmark", action="store_true",
                        help="Also run benchmark_gpu_resident.conf and compare against standard CUDA")
    parser.add_argument("--ramp-smoke", action="store_true",
                        help="Run shortened NPT -> locked relaxation -> restraint ramp -> production workflow")
    parser.add_argument("--smoke-npt-steps", type=int, default=5000,
                        help="NPT steps for --ramp-smoke")
    parser.add_argument("--smoke-relax-steps", type=int, default=5000,
                        help="Locked restrained relaxation steps for --ramp-smoke")
    parser.add_argument("--smoke-ramp-steps", type=int, default=2000,
                        help="Steps for each generated ramp stage in --ramp-smoke")
    parser.add_argument("--smoke-prod-steps", type=int, default=5000,
                        help="Unrestrained production steps for --ramp-smoke")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    design  = _load_design()
    run_dir = RESULTS_DIR / "periodic_cell_run"

    # Build
    if args.skip_build and run_dir.exists():
        print(f"[BUILD] Skipped — using existing {run_dir}")
        stats = get_periodic_cell_stats(design)
    else:
        stats = build_package(design, run_dir)

    if args.ramp_smoke:
        run_restraint_ramp_smoke(
            run_dir,
            stats,
            npt_steps=args.smoke_npt_steps,
            relax_steps=args.smoke_relax_steps,
            ramp_steps=args.smoke_ramp_steps,
            prod_steps=args.smoke_prod_steps,
        )
    elif args.production or args.continue_run:
        _restore_run_configs_from_zip(run_dir)
        run_namd_production(run_dir, args.prod_steps)
    else:
        _restore_run_configs_from_zip(run_dir)
        benches = [
            run_namd_bench(
                run_dir, args.n_steps,
                tag="D1_standard",
                conf_name="benchmark_standard_cuda.conf",
            )
        ]
        if args.gpu_benchmark:
            _restore_run_configs_from_zip(run_dir)
            benches.append(
                run_namd_bench(
                    run_dir, args.n_steps,
                    tag="D2_gpu_resident",
                    conf_name="benchmark_gpu_resident.conf",
                )
            )
        write_summary(stats, benches)


if __name__ == "__main__":
    main()
