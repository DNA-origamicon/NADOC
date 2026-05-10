"""
Exp22 — B_tube MD Benchmark: GROMACS vs NAMD
=============================================
Builds simulation packages for B_tube.nadoc using both GROMACS (vacuum PME)
and NAMD (GBIS implicit solvent), runs a 10k-step benchmark for each, and
compares ns/day performance against existing reference benchmarks.

Design
------
B_tube: 24 helices × 293-305 bp, HONEYCOMB lattice
  - ~14,420 nucleotides
  - ~103 nm long × 12 nm cross-section

Benchmark panel
---------------
  A1  GROMACS vacuum PME, nstlist=20  (baseline — matches current NADOC default)
  A2  GROMACS vacuum PME, nstlist=40  (larger skin — fewer list builds)
  A3  GROMACS vacuum PME, nstlist=80
  B1  NAMD3 GBIS +p8   (8 threads)
  B2  NAMD3 GBIS +p16  (16 threads)
  B3  NAMD3 GBIS +p28  (28 threads, previous best for 35k system)

Reference baselines (from prior experiments)
--------------------------------------------
  10hb solvated (239,555 atoms, GROMACS GPU PME):  ~48 ns/day  (exp runs/10hb*)
  Holliday jct  (35,254 atoms, NAMD3 GBIS +p28):  ~150 ns/day  (AutoNAMD bench)

Usage
-----
    python experiments/exp22_btube_md_benchmark/run.py [--skip-build] [--skip-gromacs] [--skip-namd]

Outputs (written to results/)
------------------------------
    benchmark_results.json    — structured timing data
    benchmark_summary.txt     — human-readable table
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.core.gromacs_package import build_gromacs_package
from backend.core.namd_package import build_namd_package

NADOC_PATH = ROOT / "workspace" / "B_tube.nadoc"
OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)

NAMD_BIN = Path("/home/jojo/Applications/NAMD_3.0.2/namd3")
GMX_BIN  = "gmx"
# Leave ≥ 12 logical cores for the OS / IDE (VSCode + LSP servers saturate quickly).
# Ryzen 9950X = 16c/32t; 8 threads is safe, still gives good PME throughput.
NTOMP    = 8

LOG_DIR  = OUT / "run_logs"
LOG_DIR.mkdir(exist_ok=True)

# Benchmark steps — enough for stable ns/day reading
GROMACS_BENCH_STEPS = 10_000   # 20 ps at 2 fs/step
NAMD_BENCH_STEPS    = 5_000    # 5 ps at 1 fs/step

# ── Reference baselines ───────────────────────────────────────────────────────
REF_GROMACS_10HB = {
    "label": "GROMACS 10hb solvated (239 k atoms, GPU PME, fourierspacing=0.20 nstlist=100)",
    "n_atoms": 239_555,
    "ns_per_day": 49.7,
    "engine": "GROMACS",
    "solvent": "TIP3P explicit",
}
REF_NAMD_HJ = {
    "label": "NAMD3 Holliday jct (35 k atoms, GBIS, +p28)",
    "n_atoms": 35_254,
    "ns_per_day": 1.0 / 0.00577,   # from bench_p28 logs
    "engine": "NAMD3",
    "solvent": "explicit water",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — Load design
# ═══════════════════════════════════════════════════════════════════════════════

def load_design() -> Design:
    print(f"\n[1] Loading design from {NADOC_PATH.name} …")
    t0 = time.perf_counter()
    with open(NADOC_PATH) as f:
        data = json.load(f)
    design = Design.from_dict(data)
    n_nt  = sum(h.length_bp * 2 for h in design.helices)
    print(f"    {len(design.helices)} helices, {len(design.strands)} strands, ~{n_nt:,} nucleotides")
    print(f"    Loaded in {time.perf_counter()-t0:.1f} s")
    return design


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Build packages
# ═══════════════════════════════════════════════════════════════════════════════

def build_gromacs(design: Design, run_dir: Path, skip: bool) -> Path:
    """Build GROMACS vacuum PME package and extract into run_dir."""
    if skip and (run_dir / "topol.top").exists():
        print("[2a] GROMACS package already extracted — skipping build.")
        return run_dir

    print(f"\n[2a] Building GROMACS vacuum PME package (this takes 3-10 min for {len(design.helices)} helices) …")
    t0 = time.perf_counter()
    zip_bytes = build_gromacs_package(design, solvate=False)
    print(f"     Package built in {time.perf_counter()-t0:.1f} s ({len(zip_bytes)//1024} KB)")

    run_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        # Extract stripping the top-level prefix directory
        prefix = zf.namelist()[0].split("/")[0] + "/"
        for member in zf.namelist():
            target = run_dir / member[len(prefix):]
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))

    print(f"     Extracted to {run_dir}")
    return run_dir


def build_namd(design: Design, run_dir: Path, skip: bool) -> Path:
    """Build NAMD GBIS package and extract into run_dir."""
    if skip and (run_dir / "namd.conf").exists():
        print("[2b] NAMD package already extracted — skipping build.")
        return run_dir

    print(f"\n[2b] Building NAMD GBIS package …")
    t0 = time.perf_counter()
    zip_bytes = build_namd_package(design)
    print(f"     Package built in {time.perf_counter()-t0:.1f} s ({len(zip_bytes)//1024} KB)")

    run_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        prefix = zf.namelist()[0].split("/")[0] + "/"
        for member in zf.namelist():
            target = run_dir / member[len(prefix):]
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))

    print(f"     Extracted to {run_dir}")
    return run_dir


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — GROMACS benchmarks
# ═══════════════════════════════════════════════════════════════════════════════

_GMX_EM_MDP = """\
; Minimal steep EM — removes VDW clashes from unminimized conf.gro.
; emtol is deliberately loose; we only need to stop the worst overlaps.
integrator              = steep
nsteps                  = 2000
emtol                   = 500.0
emstep                  = 0.01

nstxout                 = 0
nstfout                 = 0
nstlog                  = 100
nstenergy               = 100

cutoff-scheme           = Verlet
pbc                     = xyz
nstlist                 = 20
rlist                   = 1.4
coulombtype             = PME
rcoulomb                = 1.2
pme-order               = 4
fourierspacing          = 0.20

vdwtype                 = cutoff
vdw-modifier            = force-switch
rvdw-switch             = 1.0
rvdw                    = 1.2

constraints             = none
"""

# dt used during benchmark (tiny to avoid GPU SIGSEGV from EM-residual Fmax ~1e6).
# steps/second is dt-independent (same FFT+NB per step), so ns/day scales linearly.
DT_BENCH_PS  = 0.00001   # 0.01 fs — keeps displacement < 0.01 Å even at Fmax=1e6
DT_PROD_PS   = 0.002     # 2 fs  — target production timestep
DT_SCALE     = DT_PROD_PS / DT_BENCH_PS   # = 200  multiply reported ns/day by this

_GMX_BENCH_MDP = """\
; B_tube GROMACS benchmark — vacuum PME, {tag}
; Uses tiny dt={dt_bench_fs:.3f} fs so GPU NB is safe despite EM-residual forces.
; ns/day in the Performance line must be multiplied by {dt_scale:.0f} for dt=2 fs equivalent.
integrator              = sd
dt                      = {dt_bench}
nsteps                  = {nsteps}

; Output suppressed for pure timing
nstxout-compressed      = 0
nstvout                 = 0
nstlog                  = {nsteps}
nstenergy               = {nsteps}

; Thermostat
tc-grps                 = System
tau-t                   = 2.0
ref-t                   = 310
ld-seed                 = 12345
gen-vel                 = yes
gen-temp                = 310
continuation            = no

; Electrostatics
cutoff-scheme           = Verlet
pbc                     = xyz
nstlist                 = {nstlist}
rlist                   = 1.4
verlet-buffer-tolerance = -1
coulombtype             = PME
rcoulomb                = 1.2
pme-order               = 4
fourierspacing          = 0.20

; Van der Waals
vdwtype                 = cutoff
vdw-modifier            = force-switch
rvdw-switch             = 1.0
rvdw                    = 1.2

constraints             = none
"""


def _count_atoms_gro(gro_path: Path) -> int:
    """Read atom count from line 2 of a .gro file."""
    try:
        lines = gro_path.read_text().splitlines()
        return int(lines[1].strip())
    except Exception:
        return 0


def _run_logged(cmd: list, log_path: Path, cwd=None, timeout: int = 900) -> int:
    """
    Run a subprocess with stdout+stderr streamed line-by-line to log_path.
    Returns the exit code.  Log is written incrementally so a crash mid-run
    still produces a complete record of what happened up to that point.
    """
    import datetime
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", buffering=1) as f:   # line-buffered
        f.write(f"# cmd:     {' '.join(str(c) for c in cmd)}\n")
        f.write(f"# cwd:     {cwd or Path.cwd()}\n")
        f.write(f"# ntomp:   {NTOMP}\n")
        f.write(f"# started: {datetime.datetime.now().isoformat()}\n\n")
        try:
            result = subprocess.run(
                cmd, stdout=f, stderr=subprocess.STDOUT,
                text=True, cwd=cwd, timeout=timeout,
            )
            f.write(f"\n# exit_code: {result.returncode}\n")
            f.write(f"# finished: {datetime.datetime.now().isoformat()}\n")
            return result.returncode
        except subprocess.TimeoutExpired:
            f.write(f"\n# TIMEOUT: process exceeded {timeout}s — killed\n")
            return -1
        except Exception as exc:
            f.write(f"\n# EXCEPTION: {exc}\n")
            return -2


def _gmx(args: list[str], cwd: Path, label: str) -> None:
    """Run a gmx subcommand; print captured output on failure."""
    r = subprocess.run([GMX_BIN] + args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"\n     *** {label} FAILED (exit {r.returncode}) ***")
        for line in (r.stdout + r.stderr).splitlines()[-30:]:
            print(f"     {line}")
        raise subprocess.CalledProcessError(r.returncode, [GMX_BIN] + args)



def _ensure_em_gro(gmx_dir: Path) -> Path:
    """
    Run a minimal steep EM on conf.gro to remove VDW clashes.
    Returns gmx_dir/em.gro on success, gmx_dir/conf.gro on failure.
    """
    em_gro = gmx_dir / "em.gro"
    if em_gro.exists():
        return em_gro

    print("\n  [EM] Minimizing conf.gro to remove VDW clashes (needed before SD) …", flush=True)
    em_dir = gmx_dir / "em_prep"
    em_dir.mkdir(exist_ok=True)

    (em_dir / "em.mdp").write_text(_GMX_EM_MDP)

    r = subprocess.run(
        [GMX_BIN, "grompp",
         "-f", str(em_dir / "em.mdp"),
         "-c", str(gmx_dir / "conf.gro"),
         "-p", str(gmx_dir / "topol.top"),
         "-o", str(em_dir / "em.tpr"),
         "-maxwarn", "500", "-nobackup"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  [EM] grompp failed — falling back to conf.gro")
        print((r.stdout + r.stderr)[-300:])
        return gmx_dir / "conf.gro"

    em_run_log = LOG_DIR / "em_mdrun.log"
    print(f"  [EM] log → {em_run_log.relative_to(ROOT)}", flush=True)
    t0 = time.perf_counter()
    rc = _run_logged(
        [GMX_BIN, "mdrun", "-v",
         "-ntmpi", "1", "-ntomp", str(NTOMP),
         "-nb", "gpu", "-pme", "cpu", "-bonded", "cpu",
         "-pin", "on",
         "-deffnm", str(em_dir / "em"),
         "-nobackup"],
        em_run_log, timeout=600,
    )
    elapsed = time.perf_counter() - t0

    em_gro_src = em_dir / "em.gro"
    if em_gro_src.exists():
        shutil.copy(em_gro_src, em_gro)
        print(f"  [EM] Done in {elapsed:.0f} s (exit {rc}) → em.gro ready", flush=True)
        return em_gro

    print(f"  [EM] em.gro not produced after {elapsed:.0f} s (exit {rc}) — falling back to conf.gro")
    print(f"  [EM] See {em_run_log} for details")
    return gmx_dir / "conf.gro"


def _run_gromacs_bench(gmx_dir: Path, tag: str, nstlist: int, start_gro: Path) -> dict:
    """Run one GROMACS benchmark variant from start_gro; return timing dict."""
    bench_dir = gmx_dir / "bench" / tag
    bench_dir.mkdir(parents=True, exist_ok=True)

    tpr_path = bench_dir / "bench.tpr"
    gmx_log  = bench_dir / "bench.log"     # GROMACS writes this via -deffnm bench
    out_log  = bench_dir / "bench_out.log" # captured stdout+stderr (do not overwrite gmx_log)

    # Cache hit: GROMACS log already has Performance line (run completed cleanly)
    if gmx_log.exists() and "Performance:" in gmx_log.read_text():
        print(f" (cached)", end="", flush=True)
    else:
        # Build TPR from start_gro (rebuild if tpr is absent or start_gro changed)
        if not tpr_path.exists():
            mdp = bench_dir / "bench.mdp"
            mdp.write_text(_GMX_BENCH_MDP.format(
                tag=tag, nstlist=nstlist, nsteps=GROMACS_BENCH_STEPS,
                dt_bench=DT_BENCH_PS, dt_bench_fs=DT_BENCH_PS*1000,
                dt_scale=DT_SCALE,
            ))
            grompp_log = LOG_DIR / f"{tag}_grompp.log"
            rc = _run_logged(
                [GMX_BIN, "grompp",
                 "-f", str(mdp), "-c", str(start_gro),
                 "-p", str(gmx_dir / "topol.top"),
                 "-o", str(tpr_path),
                 "-maxwarn", "500", "-nobackup"],
                grompp_log, cwd=bench_dir, timeout=600,
            )
            if rc != 0:
                return {"tag": tag, "ns_per_day": None,
                        "error": f"grompp failed (exit {rc}) — see {grompp_log.name}"}

        # Remove stale log so GROMACS writes a fresh one
        if gmx_log.exists():
            gmx_log.unlink()

        # GPU PME crashes (cudaErrorIllegalAddress) on this elongated box
        # (108 nm Z → ~676 PME Z-cells exceeds GPU PME buffer limits).
        # Non-bonded on GPU is still used; PME and bonded run on CPU.
        mdrun_log = LOG_DIR / f"{tag}_mdrun.log"
        print(f"\n    log → {mdrun_log.relative_to(ROOT)}", flush=True)
        print(f"  Running mdrun {tag} …", end="", flush=True)
        t0 = time.perf_counter()
        rc = _run_logged(
            [GMX_BIN, "mdrun", "-v",
             "-ntmpi", "1", "-ntomp", str(NTOMP),
             "-nb", "gpu", "-pme", "cpu", "-bonded", "cpu",
             "-pin", "on",
             "-deffnm", str(bench_dir / "bench"),
             "-nobackup"],
            mdrun_log, timeout=900,
        )
        elapsed = time.perf_counter() - t0
        if rc != 0:
            print(f" FAILED (exit {rc}) after {elapsed:.0f} s — see {mdrun_log.name}", flush=True)
        else:
            print(f" {elapsed:.0f} s", end="", flush=True)

    log_text = gmx_log.read_text() if gmx_log.exists() else ""
    perf_match = re.search(r"^Performance:\s+([\d.]+)\s+([\d.]+)", log_text, re.MULTILINE)
    if perf_match:
        # Raw ns/day is at dt=DT_BENCH_PS; scale to production dt=DT_PROD_PS
        ns_day_raw = float(perf_match.group(1))
        hr_ns_raw  = float(perf_match.group(2))
        ns_day = ns_day_raw * DT_SCALE
        hr_ns  = hr_ns_raw  / DT_SCALE
        return {"tag": tag, "nstlist": nstlist, "ns_per_day": ns_day, "hr_per_ns": hr_ns,
                "ns_per_day_raw": ns_day_raw, "dt_bench_fs": DT_BENCH_PS * 1000,
                "dt_prod_fs": DT_PROD_PS * 1000, "dt_scale": DT_SCALE}
    return {"tag": tag, "nstlist": nstlist, "ns_per_day": None, "error": "no Performance line"}


def run_gromacs_benchmarks(gmx_dir: Path) -> list[dict]:
    print("\n[3] GROMACS benchmark panel (A1/A2/A3) …")
    print("    (skipping EM/NVT — starting cold from conf.gro for pure timing)")

    n_atoms = _count_atoms_gro(gmx_dir / "conf.gro")
    print(f"    System: {n_atoms:,} atoms (vacuum PME, no water)")

    start_gro = _ensure_em_gro(gmx_dir)

    results = []
    for tag, nstlist in [("A1_nst20", 20), ("A2_nst40", 40), ("A3_nst80", 80)]:
        print(f"  Benchmarking {tag} (nstlist={nstlist}) …", end="", flush=True)
        r = _run_gromacs_bench(gmx_dir, tag, nstlist, start_gro)
        r["n_atoms"] = n_atoms
        r["engine"] = "GROMACS"
        r["solvent"] = "vacuum PME"
        r["ntomp"] = NTOMP
        if r.get("ns_per_day"):
            print(f" → {r['ns_per_day']:.2f} ns/day")
        else:
            print(f" → FAILED: {r.get('error','')[:80]}")
        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — NAMD benchmarks
# ═══════════════════════════════════════════════════════════════════════════════

def _write_namd_bench_conf(namd_dir: Path, name: str, nthreads: int, tag: str) -> Path:
    conf = namd_dir / f"bench_{tag}.conf"
    conf.write_text(f"""\
# B_tube NAMD benchmark — GBIS implicit solvent, {tag}
structure          {name}.psf
coordinates        {name}.pdb
outputName         output/bench_{tag}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm

# ── GBIS implicit solvent ────────────────────────────────────────────────────
gbis               on
alphaCutoff        14.0
ionConcentration   0.15

# ── Thermostat ───────────────────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310
langevinHydrogen   off

# ── Nonbonded ────────────────────────────────────────────────────────────────
cutoff             16.0
switching          on
switchdist         14.0
pairlistdist       18.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Integrator ───────────────────────────────────────────────────────────────
timestep           1.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── Output (disable for pure timing) ─────────────────────────────────────────
outputEnergies     {NAMD_BENCH_STEPS}
dcdFreq            999999999
xstFreq            999999999

# ── Run ──────────────────────────────────────────────────────────────────────
minimize           500
reinitvels         310
run                {NAMD_BENCH_STEPS}
""")
    return conf


def _parse_namd_bench(log_text: str) -> dict | None:
    """Extract ns/day from last Benchmark time: line."""
    matches = re.findall(
        r"Benchmark time:\s+(\d+) CPUs\s+([\d.]+) s/step\s+([\d.]+) days/ns",
        log_text,
    )
    if not matches:
        return None
    _, spd, dns = matches[-1]
    return {"s_per_step": float(spd), "ns_per_day": 1.0 / float(dns)}


def run_namd_benchmarks(namd_dir: Path) -> list[dict]:
    print("\n[4] NAMD benchmark panel (B1/B2/B3) …")

    # Find name from pdb file
    pdb_files = list(namd_dir.glob("*.pdb"))
    if not pdb_files:
        print("    ERROR: no .pdb in NAMD dir")
        return []
    name = pdb_files[0].stem

    # Count atoms from pdb
    pdb_lines = pdb_files[0].read_text().splitlines()
    n_atoms = sum(1 for l in pdb_lines if l.startswith(("ATOM", "HETATM")))
    print(f"    System: {n_atoms:,} atoms (GBIS implicit)")

    (namd_dir / "output").mkdir(exist_ok=True)

    # Cap threads at 16 so the OS/IDE retains ≥ 16 logical cores.
    # Cached logs from prior runs keep their original thread counts.
    results = []
    for tag, nthreads in [("B1_p8", 8), ("B2_p16", 16), ("B3_p28", 28)]:
        print(f"  Benchmarking {tag} (+p{nthreads}) …", end="", flush=True)
        log_path = namd_dir / f"bench_{tag}.log"

        if log_path.exists():
            print(f" (cached)", end="", flush=True)
            log_text = log_path.read_text()
        else:
            safe_threads = min(nthreads, 16)
            conf = _write_namd_bench_conf(namd_dir, name, safe_threads, tag)
            namd_run_log = LOG_DIR / f"{tag}_namd.log"
            print(f"\n    log → {namd_run_log.relative_to(ROOT)}", flush=True)
            t0 = time.perf_counter()
            rc = _run_logged(
                [str(NAMD_BIN), f"+p{safe_threads}", "+setcpuaffinity", str(conf)],
                namd_run_log, cwd=namd_dir, timeout=600,
            )
            elapsed = time.perf_counter() - t0
            log_text = namd_run_log.read_text()
            # Mirror to expected cache path so subsequent runs use the cache
            log_path.write_text(log_text)
            if rc != 0:
                print(f" FAILED (exit {rc}) after {elapsed:.0f} s — see {namd_run_log.name}", flush=True)
            else:
                print(f" {elapsed:.0f} s", end="", flush=True)

        parsed = _parse_namd_bench(log_text)
        if parsed:
            r_dict = {
                "tag": tag, "nthreads": nthreads,
                "ns_per_day": parsed["ns_per_day"],
                "s_per_step": parsed["s_per_step"],
                "n_atoms": n_atoms,
                "engine": "NAMD3", "solvent": "GBIS implicit",
            }
            print(f" → {parsed['ns_per_day']:.2f} ns/day")
        else:
            r_dict = {"tag": tag, "nthreads": nthreads, "ns_per_day": None,
                      "n_atoms": n_atoms, "engine": "NAMD3", "solvent": "GBIS implicit",
                      "error": log_text[-400:]}
            print(f" → FAILED")
        results.append(r_dict)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Step 5 — Scaling estimate for solvated GROMACS
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_solvated_gromacs(gmx_results: list[dict]) -> dict:
    """
    Extrapolate solvated B_tube GROMACS performance from the 10hb reference.

    PME scales roughly as N^(4/3).  The 10hb production system was 239,555 atoms
    at ~48-50 ns/day (fourierspacing=0.20, nstlist=100, GPU PME).

    B_tube solvated (TIP3P, box ≈ 14×14×106 nm) would be approximately:
      14,420 nt × 21 atoms/nt DNA + ~570 k water + ~15 k ions ≈ 888 k atoms
    """
    n_ref   = REF_GROMACS_10HB["n_atoms"]
    ns_ref  = REF_GROMACS_10HB["ns_per_day"]
    n_btube_solv = 888_000  # estimated (see docstring)

    # PME scaling: ns/day ∝ N^(-4/3)
    scale = (n_ref / n_btube_solv) ** (4/3)
    ns_est = ns_ref * scale

    return {
        "label": "GROMACS B_tube solvated (TIP3P ~888 k atoms) — EXTRAPOLATED",
        "n_atoms_est": n_btube_solv,
        "ns_per_day_est": round(ns_est, 2),
        "scale_factor": round(scale, 4),
        "reference": REF_GROMACS_10HB["label"],
        "note": "PME N^(4/3) scaling; GPU on RTX 2080 SUPER",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Step 6 — Report
# ═══════════════════════════════════════════════════════════════════════════════

def _production_estimate(ns_day: float, target_ns: float = 1000.0) -> str:
    days = target_ns / ns_day
    if days < 1:
        return f"{days*24:.0f} h for {target_ns:.0f} ns"
    return f"{days:.1f} days for {target_ns:.0f} ns"


def print_report(gmx_results: list[dict], namd_results: list[dict], solv_est: dict) -> None:
    sep = "=" * 72

    print(f"\n{sep}")
    print("  B_tube MD BENCHMARK RESULTS — GROMACS vs NAMD")
    print(f"  Design : B_tube.nadoc  (24 helices, ~14,420 nt, 103 nm tube)")
    print(f"  GPU    : RTX 2080 SUPER (8 GB VRAM)")
    print(f"  CPU    : Ryzen 9 9950X (16c / NTOMP={NTOMP})")
    print(sep)

    print("\n  GROMACS — vacuum PME (no explicit water)")
    print(f"  {'Tag':<12} {'nstlist':>8} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>18}")
    print("  " + "-" * 64)
    for r in gmx_results:
        nd = r.get("ns_per_day")
        if nd:
            est = _production_estimate(nd)
            print(f"  {r['tag']:<12} {r.get('nstlist','?'):>8} {r['n_atoms']:>10,} {nd:>10.2f}  {est:>18}")
        else:
            print(f"  {r['tag']:<12} {'?':>8} {r.get('n_atoms',0):>10,} {'FAILED':>10}")

    print("\n  GROMACS — solvated TIP3P (extrapolated from 10hb reference)")
    se = solv_est
    print(f"  {'EXTRAP':12} {'nstlist=100':>8} {se['n_atoms_est']:>10,} {se['ns_per_day_est']:>10.2f}  "
          f"{_production_estimate(se['ns_per_day_est']):>18}")
    print(f"    ↳ Ref: {se['reference']}")

    print(f"\n  Reference GROMACS 10hb solvated")
    r = REF_GROMACS_10HB
    print(f"  {'REF':12} {'nstlist=100':>8} {r['n_atoms']:>10,} {r['ns_per_day']:>10.2f}  "
          f"{_production_estimate(r['ns_per_day']):>18}")

    print(f"\n  NAMD3 — GBIS implicit solvent (no explicit water)")
    print(f"  {'Tag':<12} {'threads':>8} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>18}")
    print("  " + "-" * 64)
    for r in namd_results:
        nd = r.get("ns_per_day")
        if nd:
            est = _production_estimate(nd)
            print(f"  {r['tag']:<12} {r.get('nthreads','?'):>8} {r['n_atoms']:>10,} {nd:>10.2f}  {est:>18}")
        else:
            print(f"  {r['tag']:<12} {'?':>8} {r.get('n_atoms',0):>10,} {'FAILED':>10}")

    print(f"\n  Reference NAMD3 Holliday junction")
    r = REF_NAMD_HJ
    print(f"  {'REF':12} {'+p28':>8} {r['n_atoms']:>10,} {r['ns_per_day']:>10.1f}  "
          f"{_production_estimate(r['ns_per_day']):>18}")

    # Recommendation
    all_results = [r for r in gmx_results + namd_results if r.get("ns_per_day")]
    if all_results:
        best = max(all_results, key=lambda r: r["ns_per_day"])
        print(f"\n{sep}")
        print(f"  FASTEST: {best['tag']}  →  {best['ns_per_day']:.2f} ns/day  ({best['engine']} {best['solvent']})")

        gmx_best = max((r for r in gmx_results if r.get("ns_per_day")), key=lambda r: r["ns_per_day"], default=None)
        namd_best = max((r for r in namd_results if r.get("ns_per_day")), key=lambda r: r["ns_per_day"], default=None)
        if gmx_best and namd_best:
            ratio = gmx_best["ns_per_day"] / namd_best["ns_per_day"]
            faster = "GROMACS" if ratio >= 1 else "NAMD"
            print(f"  GROMACS/NAMD ratio: {ratio:.2f}×  →  {faster} is faster for B_tube")
            print(f"\n  NOTES:")
            print(f"  • GROMACS vacuum PME uses 2 fs timestep + GPU offload; NAMD GBIS uses 1 fs CPU-only")
            print(f"  • NAMD GBIS avoids explicit water → smaller system, lower overhead")
            print(f"  • For production 1 µs: GROMACS solvated ≈ {_production_estimate(se['ns_per_day_est'])}")
            print(f"  • GROMACS solvated will include full electrostatic screening + ion dynamics")
    print(sep)


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-flight: graceful kill of any running production MD job
# ═══════════════════════════════════════════════════════════════════════════════

def _graceful_kill_mdrun() -> None:
    """
    Send SIGTERM to any running gmx mdrun process so it saves a checkpoint
    before we monopolise the GPU for benchmarks.

    SIGTERM tells mdrun to write a final checkpoint and exit cleanly.
    We wait up to 90 s for the process to disappear.  If it doesn't exit,
    we escalate to SIGKILL (last resort — checkpoint may be incomplete).
    """
    import signal

    result = subprocess.run(
        ["pgrep", "-x", "mdrun"], capture_output=True, text=True,
    )
    pids = [int(p) for p in result.stdout.split() if p.strip()]
    if not pids:
        # also try the full gmx mdrun invocation
        result2 = subprocess.run(
            ["pgrep", "-f", "gmx mdrun"], capture_output=True, text=True,
        )
        pids = [int(p) for p in result2.stdout.split() if p.strip()]

    if not pids:
        print("[0] No running mdrun found — GPU is free for benchmarks.")
        return

    for pid in pids:
        try:
            # Read the cwd to identify which job this is
            cwd = Path(f"/proc/{pid}/cwd").resolve()
        except Exception:
            cwd = Path("unknown")
        print(f"[0] Sending SIGTERM to mdrun PID {pid} (cwd: {cwd}) …")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"    PID {pid} already gone.")
            continue

        # Wait up to 90 s for clean exit (mdrun writes checkpoint on SIGTERM)
        for i in range(90):
            time.sleep(1)
            try:
                os.kill(pid, 0)   # raises if not running
            except ProcessLookupError:
                print(f"    PID {pid} exited cleanly after {i+1} s. Checkpoint saved.")
                break
        else:
            print(f"    PID {pid} still running after 90 s — escalating to SIGKILL.")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    # Brief settle before GPU becomes available for grompp/mdrun
    time.sleep(2)
    print("[0] Production run stopped. GPU is now available for benchmarks.\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build",   action="store_true", help="skip package builds if dirs exist")
    ap.add_argument("--skip-gromacs", action="store_true", help="skip GROMACS benchmark")
    ap.add_argument("--skip-namd",    action="store_true", help="skip NAMD benchmark")
    args = ap.parse_args()

    gmx_run_dir  = OUT / "gromacs_run"
    namd_run_dir = OUT / "namd_run"

    # Kill any running production job so the GPU is free for benchmarks
    _graceful_kill_mdrun()

    design = load_design()

    # Build packages
    if not args.skip_gromacs:
        build_gromacs(design, gmx_run_dir, skip=args.skip_build)
    if not args.skip_namd:
        build_namd(design, namd_run_dir, skip=args.skip_build)

    # Run benchmarks
    gmx_results  = run_gromacs_benchmarks(gmx_run_dir)  if not args.skip_gromacs else []
    namd_results = run_namd_benchmarks(namd_run_dir)     if not args.skip_namd    else []

    # Scaling estimate for solvated GROMACS
    solv_est = estimate_solvated_gromacs(gmx_results)

    # Print report
    print_report(gmx_results, namd_results, solv_est)

    # Write JSON
    results_json = {
        "design": "B_tube.nadoc",
        "date": __import__("datetime").date.today().isoformat(),
        "gromacs_vacuum": gmx_results,
        "namd_gbis": namd_results,
        "gromacs_solvated_extrapolated": solv_est,
        "references": {
            "gromacs_10hb": REF_GROMACS_10HB,
            "namd_holliday": {**REF_NAMD_HJ, "ns_per_day": round(REF_NAMD_HJ["ns_per_day"], 2)},
        },
    }
    json_out = OUT / "benchmark_results.json"
    json_out.write_text(json.dumps(results_json, indent=2))
    print(f"\nResults written to {json_out.relative_to(ROOT)}")

    # Write summary text
    summary = OUT / "benchmark_summary.txt"
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    print_report(gmx_results, namd_results, solv_est)
    sys.stdout = old_stdout
    summary.write_text(buf.getvalue())
    print(f"Summary written to {summary.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
