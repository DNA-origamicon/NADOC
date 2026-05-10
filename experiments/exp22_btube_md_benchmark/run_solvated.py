"""
Exp22b — B_tube Solvated MD Benchmark: GROMACS vs NAMD (explicit TIP3P)
=========================================================================
Extends exp22 with explicit-solvent variants:

  C1  GROMACS solvated TIP3P — nstlist=20, CPU PME, GPU NB
  C2  GROMACS solvated TIP3P — nstlist=20, GPU PME (attempt; may fail on elongated box)
  D1  NAMD3 solvated CUDASOAintegrate — +p8 +devices 0

Both use 1.2 nm padding (same system, ~2.5 M atoms).
GROMACS uses the tiny-dt trick (dt=0.00001 ps, scale ×200) because DNA is
unminimized at the water interface.  NAMD uses real 2 fs timestep with
CUDASOAintegrate + rigidBonds water.

Results are combined with the prior vacuum panel from benchmark_results.json
for a full six-variant comparison table.

Usage
-----
    python experiments/exp22_btube_md_benchmark/run_solvated.py [--skip-build]
    python experiments/exp22_btube_md_benchmark/run_solvated.py --skip-build
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.core.gromacs_package import build_gromacs_package
from backend.core.namd_solvate import build_namd_solvated_package, get_solvation_stats

NADOC_PATH = ROOT / "workspace" / "B_tube.nadoc"
OUT   = Path(__file__).parent / "results"
SOUT  = OUT / "solvated"           # all solvated-run artefacts live here
OUT.mkdir(exist_ok=True)
SOUT.mkdir(exist_ok=True)

NAMD_BIN = Path("/home/jojo/Applications/NAMD_3.0.2/namd3")
GMX_BIN  = "gmx"
NTOMP    = 8        # threads for GROMACS mdrun (leaves ≥ 24 for OS / IDE)

LOG_DIR  = SOUT / "run_logs"
LOG_DIR.mkdir(exist_ok=True)

# Benchmark parameters
GROMACS_BENCH_STEPS  = 10_000
NAMD_BENCH_STEPS     = 5_000
NAMD_MINIMIZE_STEPS  = 500

# Tiny-dt trick for GROMACS (same as vacuum benchmark)
DT_BENCH_PS  = 0.00001   # 0.01 fs
DT_PROD_PS   = 0.002     # 2 fs production
DT_SCALE     = int(DT_PROD_PS / DT_BENCH_PS)   # 200

PADDING_NM   = 1.2
ION_CONC_MM  = 150.0

# ── MDP templates ──────────────────────────────────────────────────────────────

_IONS_MDP = """\
; Minimal MDP for grompp before genion — no real dynamics
integrator  = steep
nsteps      = 0
pbc         = xyz
cutoff-scheme = Verlet
coulombtype = PME
rcoulomb    = 1.2
rvdw        = 1.2
"""

# Short steepest-descent EM to remove water-DNA close contacts.
# Without this, even dt=0.00001 ps causes GPU SIGSEGV at step 0 from LJ
# forces (~1e12 kJ/mol/nm) on overlapping water/DNA atoms near skip-site bridges.
_EM_MDP = """\
; Pre-benchmark steepest-descent EM — removes water/DNA close contacts
integrator              = steep
nsteps                  = 500
emtol                   = 1000.0
emstep                  = 0.001

pbc                     = xyz
cutoff-scheme           = Verlet
nstlist                 = 10
coulombtype             = PME
rcoulomb                = 1.2
fourierspacing          = 0.20
vdwtype                 = cutoff
rvdw                    = 1.2
constraints             = none
define                  = -DFLEXIBLE
"""

_SOLVATED_BENCH_MDP = """\
; B_tube GROMACS solvated benchmark — TIP3P explicit water, {tag}
; Tiny dt={dt_bench_fs:.3f} fs prevents GPU SIGSEGV from EM-residual DNA forces.
; Scale ns/day × {dt_scale} for production-dt=2 fs equivalent.
; -DFLEXIBLE: use flexible TIP3P (no SETTLE) so unminimized water survives step 1.
; SETTLE fails on clashing water in unminimized DNA-solvent structures regardless of dt.
define                  = -DFLEXIBLE

integrator              = sd
dt                      = {dt_bench}
nsteps                  = {nsteps}

nstxout-compressed      = 0
nstvout                 = 0
nstlog                  = {nsteps}
nstenergy               = {nsteps}

tc-grps                 = System
tau-t                   = 2.0
ref-t                   = 310
ld-seed                 = 12345
gen-vel                 = yes
gen-temp                = 310
continuation            = no

cutoff-scheme           = Verlet
pbc                     = xyz
nstlist                 = {nstlist}
rlist                   = 1.4
verlet-buffer-tolerance = -1
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


# ══════════════════════════════════════════════════════════════════════════════
# Shared utilities (mirrors run.py — kept local to avoid import coupling)
# ══════════════════════════════════════════════════════════════════════════════

def _run_logged(cmd: list, log_path: Path, cwd=None, timeout: int = 1800) -> int:
    import datetime
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", buffering=1) as f:
        f.write(f"# cmd:     {' '.join(str(c) for c in cmd)}\n")
        f.write(f"# cwd:     {cwd or Path.cwd()}\n")
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
            f.write(f"\n# TIMEOUT: {timeout}s — process killed\n")
            return -1
        except Exception as exc:
            f.write(f"\n# EXCEPTION: {exc}\n")
            return -2


def _gmx_quiet(args: list, cwd: Path, label: str) -> subprocess.CompletedProcess:
    r = subprocess.run([GMX_BIN] + args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).splitlines()[-25:]
        raise RuntimeError(f"{label} failed (exit {r.returncode}):\n" + "\n".join(tail))
    return r


def _count_atoms_gro(gro_path: Path) -> int:
    try:
        return int(gro_path.read_text().splitlines()[1].strip())
    except Exception:
        return 0


def _graceful_kill_mdrun() -> None:
    result = subprocess.run(["pgrep", "-x", "mdrun"], capture_output=True, text=True)
    pids = [int(p) for p in result.stdout.split() if p.strip()]
    if not pids:
        result2 = subprocess.run(["pgrep", "-f", "gmx mdrun"], capture_output=True, text=True)
        pids = [int(p) for p in result2.stdout.split() if p.strip()]
    if not pids:
        print("[0] No running mdrun found — GPU is free.")
        return
    import signal
    for pid in pids:
        print(f"[0] SIGTERM → mdrun PID {pid} …")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        for i in range(90):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                print(f"    exited after {i+1} s")
                break
        else:
            os.kill(pid, signal.SIGKILL)
    time.sleep(2)
    print("[0] GPU free.\n")


def _extract_zip(zip_bytes: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        prefix = zf.namelist()[0].split("/")[0] + "/"
        for member in zf.namelist():
            target = dest / member[len(prefix):]
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Load design
# ══════════════════════════════════════════════════════════════════════════════

def load_design() -> Design:
    print(f"\n[1] Loading design from {NADOC_PATH.name} …")
    with open(NADOC_PATH) as f:
        design = Design.model_validate_json(f.read())
    n_nt = sum(h.length_bp * 2 for h in design.helices)
    print(f"    {len(design.helices)} helices, {len(design.strands)} strands, ~{n_nt:,} nucleotides")
    return design


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Build solvated packages
# ══════════════════════════════════════════════════════════════════════════════

def build_gromacs_solvated(design: Design, run_dir: Path, skip: bool) -> Path:
    marker = run_dir / "conf.gro"  # solvated conf (gromacs_package uses this name)
    if skip and marker.exists() and _count_atoms_gro(marker) > 500_000:
        print(f"[2a] GROMACS solvated already built ({_count_atoms_gro(marker):,} atoms) — skipping.")
        return run_dir

    print(f"\n[2a] Building GROMACS solvated package (pdb2gmx + solvate + genion, ~10 min) …")
    t0 = time.perf_counter()
    zip_bytes = build_gromacs_package(
        design,
        solvate=True,
        ion_conc_mM=ION_CONC_MM,
    )
    dt = time.perf_counter() - t0
    print(f"     Package built in {dt:.0f} s ({len(zip_bytes)//1024:,} KB)")

    run_dir.mkdir(parents=True, exist_ok=True)
    _extract_zip(zip_bytes, run_dir)

    n_atoms = _count_atoms_gro(run_dir / "conf.gro")
    print(f"     Solvated system: {n_atoms:,} atoms in {run_dir.name}/")
    return run_dir


def build_namd_solvated(design: Design, run_dir: Path, skip: bool) -> Path:
    marker = run_dir / "namd.conf"
    if skip and marker.exists():
        pdb = list(run_dir.glob("*.pdb"))
        if pdb:
            n = sum(1 for l in pdb[0].read_text().splitlines() if l.startswith(("ATOM","HETATM")))
            if n > 500_000:
                print(f"[2b] NAMD solvated already built ({n:,} atoms) — skipping.")
                return run_dir

    print(f"\n[2b] Building NAMD solvated package (gmx solvate + PSF merge, ~5-10 min) …")
    t0 = time.perf_counter()
    zip_bytes = build_namd_solvated_package(design, padding_nm=PADDING_NM, ion_conc_mM=ION_CONC_MM)
    dt = time.perf_counter() - t0
    print(f"     Package built in {dt:.0f} s ({len(zip_bytes)//1024:,} KB)")

    run_dir.mkdir(parents=True, exist_ok=True)
    _extract_zip(zip_bytes, run_dir)

    pdb = list(run_dir.glob("*.pdb"))[0]
    n = sum(1 for l in pdb.read_text().splitlines() if l.startswith(("ATOM","HETATM")))
    print(f"     Solvated system: {n:,} atoms in {run_dir.name}/")
    return run_dir


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — GROMACS solvated benchmarks  (C1 CPU-PME, C2 GPU-PME attempt)
# ══════════════════════════════════════════════════════════════════════════════

def _run_gromacs_solvated_em(gmx_dir: Path) -> Path:
    """Run a short steepest-descent EM on conf.gro → em.gro.

    Required before benchmarking: water placed by gmx solvate may overlap
    with DNA skip-site bridge atoms (unusual positions), producing LJ forces
    ~1e12 kJ/mol/nm that crash the GPU kernel at step 0 regardless of dt.
    """
    em_dir = gmx_dir / "em"
    em_gro = em_dir / "em.gro"

    if em_gro.exists() and _count_atoms_gro(em_gro) > 500_000:
        print(f"    EM already done ({_count_atoms_gro(em_gro):,} atoms in em.gro) — skipping.")
        return em_gro

    em_dir.mkdir(exist_ok=True)
    mdp = em_dir / "em.mdp"
    mdp.write_text(_EM_MDP)
    tpr = em_dir / "em.tpr"

    print(f"    Running pre-benchmark EM (500 steps steep, ~20-40 min for 3.6 M atoms) …")
    grompp_log = LOG_DIR / "em_grompp.log"
    rc = _run_logged(
        [GMX_BIN, "grompp",
         "-f", str(mdp),
         "-c", str(gmx_dir / "conf.gro"),
         "-p", str(gmx_dir / "topol.top"),
         "-o", str(tpr),
         "-maxwarn", "500", "-nobackup"],
        grompp_log, cwd=em_dir, timeout=3600,
    )
    if rc != 0:
        raise RuntimeError(f"EM grompp failed (exit {rc}) — see {grompp_log}")

    mdrun_log = LOG_DIR / "em_mdrun.log"
    print(f"    log → {mdrun_log.relative_to(ROOT)}", flush=True)
    t0 = time.perf_counter()
    rc = _run_logged(
        [GMX_BIN, "mdrun", "-v",
         "-ntmpi", "1", "-ntomp", str(NTOMP),
         "-nb", "gpu", "-pme", "cpu", "-bonded", "cpu",
         "-pin", "on",
         "-deffnm", str(em_dir / "em"),
         "-nobackup"],
        mdrun_log, timeout=7200,
    )
    elapsed = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"EM mdrun failed (exit {rc}) after {elapsed:.0f} s — see {mdrun_log}")

    print(f"    EM done in {elapsed:.0f} s → {em_gro.relative_to(ROOT)}")
    return em_gro


def _run_gromacs_solvated_bench(
    gmx_dir: Path,
    tag: str,
    nstlist: int,
    gpu_pme: bool,
    start_gro: Path | None = None,
) -> dict:
    bench_dir = gmx_dir / "bench" / tag
    bench_dir.mkdir(parents=True, exist_ok=True)

    conf = start_gro if start_gro else gmx_dir / "conf.gro"
    tpr_path = bench_dir / "bench.tpr"
    gmx_log  = bench_dir / "bench.log"

    if gmx_log.exists() and "Performance:" in gmx_log.read_text():
        print(f" (cached)", end="", flush=True)
    else:
        if not tpr_path.exists():
            mdp = bench_dir / "bench.mdp"
            mdp.write_text(_SOLVATED_BENCH_MDP.format(
                tag=tag, nstlist=nstlist, nsteps=GROMACS_BENCH_STEPS,
                dt_bench=DT_BENCH_PS,
                dt_bench_fs=DT_BENCH_PS * 1000,
                dt_scale=DT_SCALE,
            ))
            grompp_log = LOG_DIR / f"{tag}_grompp.log"
            rc = _run_logged(
                [GMX_BIN, "grompp",
                 "-f", str(mdp),
                 "-c", str(conf),
                 "-p", str(gmx_dir / "topol.top"),
                 "-o", str(tpr_path),
                 "-maxwarn", "500", "-nobackup"],
                grompp_log, cwd=bench_dir, timeout=900,
            )
            if rc != 0:
                return {"tag": tag, "ns_per_day": None,
                        "error": f"grompp failed (exit {rc})"}

        if gmx_log.exists():
            gmx_log.unlink()

        pme_flag = "gpu" if gpu_pme else "cpu"
        mdrun_log = LOG_DIR / f"{tag}_mdrun.log"
        print(f"\n    log → {mdrun_log.relative_to(ROOT)}", flush=True)
        print(f"  Running mdrun {tag} (PME={pme_flag}) …", end="", flush=True)
        t0 = time.perf_counter()
        rc = _run_logged(
            [GMX_BIN, "mdrun", "-v",
             "-ntmpi", "1", "-ntomp", str(NTOMP),
             "-nb", "gpu", "-pme", pme_flag, "-bonded", "cpu",
             "-pin", "on",
             "-deffnm", str(bench_dir / "bench"),
             "-nobackup"],
            mdrun_log, timeout=3600,
        )
        elapsed = time.perf_counter() - t0
        if rc != 0:
            print(f" FAILED (exit {rc}) after {elapsed:.0f} s", flush=True)
            return {"tag": tag, "ns_per_day": None,
                    "error": f"mdrun exit {rc} after {elapsed:.0f}s (PME={pme_flag}). "
                             f"See {mdrun_log.name}"}
        else:
            print(f" {elapsed:.0f} s", end="", flush=True)

    n_atoms = _count_atoms_gro(gmx_dir / "conf.gro")
    log_text = gmx_log.read_text() if gmx_log.exists() else ""
    m = re.search(r"^Performance:\s+([\d.]+)\s+([\d.]+)", log_text, re.MULTILINE)
    if m:
        ns_day_raw = float(m.group(1))
        ns_day     = ns_day_raw * DT_SCALE
        hr_ns      = float(m.group(2)) / DT_SCALE
        return {
            "tag": tag, "nstlist": nstlist,
            "ns_per_day": ns_day, "hr_per_ns": hr_ns,
            "ns_per_day_raw": ns_day_raw,
            "dt_bench_fs": DT_BENCH_PS * 1000,
            "dt_prod_fs": DT_PROD_PS * 1000,
            "dt_scale": DT_SCALE,
            "n_atoms": n_atoms,
            "engine": "GROMACS",
            "solvent": "TIP3P explicit",
            "pme": "gpu" if gpu_pme else "cpu",
        }
    return {"tag": tag, "nstlist": nstlist, "ns_per_day": None,
            "n_atoms": n_atoms, "error": "no Performance line in bench.log"}


def run_gromacs_solvated_benchmarks(gmx_dir: Path) -> list[dict]:
    print("\n[3] GROMACS solvated benchmark panel (C1/C2) …")
    n_atoms = _count_atoms_gro(gmx_dir / "conf.gro")
    print(f"    System: {n_atoms:,} atoms (TIP3P explicit, ~{n_atoms/1e6:.2f} M)")

    # EM required: water placed by gmx solvate may overlap with DNA skip-site
    # bridge atoms → LJ forces ~1e12 kJ/mol/nm → GPU SIGSEGV at step 0.
    em_gro = _run_gromacs_solvated_em(gmx_dir)

    results = []

    # C1: CPU PME (safe on elongated box)
    print(f"  Benchmarking C1_cpu_pme (nstlist=20, CPU PME) …", end="", flush=True)
    r = _run_gromacs_solvated_bench(gmx_dir, "C1_cpu_pme", 20, gpu_pme=False, start_gro=em_gro)
    r.setdefault("n_atoms", n_atoms)
    if r.get("ns_per_day"):
        print(f" → {r['ns_per_day']:.2f} ns/day")
    else:
        print(f" → FAILED: {r.get('error','')[:80]}")
    results.append(r)

    # C2: GPU PME (may fail on elongated box — GPU PME buffer limit)
    print(f"  Benchmarking C2_gpu_pme (nstlist=20, GPU PME attempt) …", end="", flush=True)
    r2 = _run_gromacs_solvated_bench(gmx_dir, "C2_gpu_pme", 20, gpu_pme=True, start_gro=em_gro)
    r2.setdefault("n_atoms", n_atoms)
    if r2.get("ns_per_day"):
        print(f" → {r2['ns_per_day']:.2f} ns/day  ✓ GPU PME worked!")
    else:
        print(f" → FAILED (expected on elongated box): {r2.get('error','')[:60]}")
    results.append(r2)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — NAMD solvated benchmark  (D1 CUDASOAintegrate)
# ══════════════════════════════════════════════════════════════════════════════

def _write_namd_solvated_bench_conf(namd_dir: Path, name: str) -> Path:
    """Write a stripped-down NAMD conf for benchmarking (from the package conf)."""
    src = namd_dir / "namd.conf"
    conf_text = src.read_text()

    # Patch run/minimize for benchmark
    # Replace 'minimize N' and 'run N' with benchmark values
    conf_text = re.sub(r"^minimize\s+\d+", f"minimize {NAMD_MINIMIZE_STEPS}", conf_text, flags=re.MULTILINE)
    conf_text = re.sub(r"^run\s+\d+", f"run {NAMD_BENCH_STEPS}", conf_text, flags=re.MULTILINE)

    # Suppress trajectory output
    conf_text = re.sub(r"^dcdFreq\s+\d+", "dcdFreq 999999999", conf_text, flags=re.MULTILINE)
    conf_text = re.sub(r"^xstFreq\s+\d+", "xstFreq 999999999", conf_text, flags=re.MULTILINE)
    conf_text = re.sub(r"^restartfreq\s+\d+", "restartfreq 999999999", conf_text, flags=re.MULTILINE)
    conf_text = re.sub(r"^outputEnergies\s+\d+", f"outputEnergies {NAMD_BENCH_STEPS}", conf_text, flags=re.MULTILINE)

    bench_conf = namd_dir / "bench_D1.conf"
    bench_conf.write_text(conf_text)
    return bench_conf


def _parse_namd_timing(log_text: str, timestep_fs: float = 2.0) -> dict | None:
    """Parse ns/day from NAMD log.

    Tries 'Benchmark time:' first; falls back to last TIMING line.
    """
    # Primary: Benchmark time lines
    matches = re.findall(
        r"Benchmark time:\s+(\d+) CPUs\s+([\d.]+) s/step\s+([\d.]+) days/ns",
        log_text,
    )
    if matches:
        _, spd, dns = matches[-1]
        return {"s_per_step": float(spd), "ns_per_day": 1.0 / float(dns),
                "source": "Benchmark time"}

    # Fallback: TIMING lines (NAMD prints these periodically)
    # Format: TIMING: <step>  CPU: X.X, Y.Y/step  Wall: X.X, Y.Y/step, ...
    timing_matches = re.findall(
        r"TIMING:\s+\d+\s+CPU:[\d. ,]+Wall:[\d. ,]+?([\d.]+)/step",
        log_text,
    )
    if timing_matches:
        s_per_step = float(timing_matches[-1])
        ns_per_day = (timestep_fs * 1e-6) / s_per_step * 86400
        return {"s_per_step": s_per_step, "ns_per_day": ns_per_day,
                "source": "TIMING fallback"}

    return None


def run_namd_solvated_benchmark(namd_dir: Path) -> list[dict]:
    print("\n[4] NAMD solvated benchmark (D1 CUDASOAintegrate) …")

    pdb_files = list(namd_dir.glob("*.pdb"))
    if not pdb_files:
        return [{"tag": "D1_cuda_soa", "ns_per_day": None, "error": "no .pdb found"}]
    name = pdb_files[0].stem
    n_atoms = sum(1 for l in pdb_files[0].read_text().splitlines()
                  if l.startswith(("ATOM", "HETATM")))
    print(f"    System: {n_atoms:,} atoms (TIP3P, CUDASOAintegrate)")

    (namd_dir / "output").mkdir(exist_ok=True)

    tag = "D1_cuda_soa"
    log_path = SOUT / f"{tag}_namd.log"

    if log_path.exists():
        log_text = log_path.read_text()
        parsed   = _parse_namd_timing(log_text)
        if parsed:
            print(f"  {tag} (cached) → {parsed['ns_per_day']:.2f} ns/day")
            return [{
                "tag": tag, "threads": 8, "gpu": "CUDASOAintegrate",
                "ns_per_day": parsed["ns_per_day"],
                "s_per_step": parsed["s_per_step"],
                "n_atoms": n_atoms,
                "engine": "NAMD3", "solvent": "TIP3P explicit",
                "timing_source": parsed["source"],
            }]

    bench_conf = _write_namd_solvated_bench_conf(namd_dir, name)

    print(f"  Running {tag} (+p8 +devices 0, minimize {NAMD_MINIMIZE_STEPS} + run {NAMD_BENCH_STEPS}) …",
          end="", flush=True)
    print(f"\n    log → {log_path.relative_to(ROOT)}", flush=True)
    t0 = time.perf_counter()
    rc = _run_logged(
        [str(NAMD_BIN), "+p8", "+devices", "0", "+setcpuaffinity", str(bench_conf)],
        log_path, cwd=namd_dir, timeout=3600,
    )
    elapsed = time.perf_counter() - t0

    log_text = log_path.read_text()
    parsed   = _parse_namd_timing(log_text)

    if rc != 0 or not parsed:
        tail = log_text.splitlines()[-20:]
        print(f" FAILED (exit {rc}) after {elapsed:.0f} s")
        print("  Last 20 lines of log:")
        for l in tail:
            print(f"    {l}")
        return [{"tag": tag, "n_atoms": n_atoms, "ns_per_day": None,
                 "engine": "NAMD3", "solvent": "TIP3P explicit",
                 "error": f"exit {rc} / no timing found"}]

    print(f" {elapsed:.0f} s → {parsed['ns_per_day']:.2f} ns/day")
    return [{
        "tag": tag, "threads": 8, "gpu": "CUDASOAintegrate",
        "ns_per_day": parsed["ns_per_day"],
        "s_per_step": parsed["s_per_step"],
        "n_atoms": n_atoms,
        "engine": "NAMD3", "solvent": "TIP3P explicit",
        "timing_source": parsed["source"],
    }]


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 — Load prior vacuum results from benchmark_results.json
# ══════════════════════════════════════════════════════════════════════════════

def load_vacuum_results() -> dict:
    json_path = OUT / "benchmark_results.json"
    if not json_path.exists():
        print(f"  WARNING: {json_path} not found — vacuum results unavailable.")
        return {}
    with open(json_path) as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# Step 6 — Print full comparison report
# ══════════════════════════════════════════════════════════════════════════════

def _est(ns_day: float, target_ns: float = 1000.0) -> str:
    if ns_day <= 0:
        return "—"
    days = target_ns / ns_day
    return f"{days:.1f} d / µs" if days >= 1 else f"{days*24:.0f} h / µs"


def print_full_report(
    vacuum_data: dict,
    gmx_solv: list[dict],
    namd_solv: list[dict],
) -> None:
    sep = "=" * 76

    print(f"\n{sep}")
    print("  B_tube MD BENCHMARK — GROMACS vs NAMD  (vacuum + solvated)")
    print(f"  Design : B_tube.nadoc  (24 helices, ~14,420 nt, 103 nm tube)")
    print(f"  GPU    : RTX 2080 SUPER (8 GB VRAM)")
    print(f"  CPU    : Ryzen 9 9950X (16c / NTOMP={NTOMP})")
    print(sep)

    # ── GROMACS vacuum (from prior run) ─────────────────────────────────────
    print("\n  ── GROMACS vacuum PME (no explicit water) ──────────────────────")
    print(f"  {'Tag':<14} {'nstlist':>8} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>14}")
    print("  " + "-" * 60)
    for r in vacuum_data.get("gromacs_vacuum", []):
        nd = r.get("ns_per_day")
        tag = r.get("tag", "?")
        if nd:
            print(f"  {tag:<14} {r.get('nstlist','?'):>8} {r.get('n_atoms',0):>10,} {nd:>10.2f}  {_est(nd):>14}")
        else:
            print(f"  {tag:<14} {'?':>8} {r.get('n_atoms',0):>10,} {'FAILED':>10}")

    # ── GROMACS solvated (new) ───────────────────────────────────────────────
    print("\n  ── GROMACS solvated TIP3P (explicit water + NaCl, this run) ───")
    print(f"  {'Tag':<14} {'PME':>6} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>14}")
    print("  " + "-" * 60)
    for r in gmx_solv:
        nd = r.get("ns_per_day")
        tag = r.get("tag", "?")
        pme_label = r.get("pme", "cpu").upper()
        if nd:
            print(f"  {tag:<14} {pme_label:>6} {r.get('n_atoms',0):>10,} {nd:>10.2f}  {_est(nd):>14}")
        else:
            err = r.get("error", "")[:40]
            print(f"  {tag:<14} {pme_label:>6} {r.get('n_atoms',0):>10,} {'FAILED':>10}  ({err})")

    # ── NAMD vacuum GBIS (from prior run) ───────────────────────────────────
    print("\n  ── NAMD3 vacuum GBIS (implicit solvent, prior run) ─────────────")
    print(f"  {'Tag':<14} {'threads':>8} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>14}")
    print("  " + "-" * 60)
    for r in vacuum_data.get("namd_gbis", []):
        nd = r.get("ns_per_day")
        tag = r.get("tag", "?")
        if nd:
            print(f"  {tag:<14} {r.get('nthreads','?'):>8} {r.get('n_atoms',0):>10,} {nd:>10.2f}  {_est(nd):>14}")
        else:
            print(f"  {tag:<14} {'?':>8} {r.get('n_atoms',0):>10,} {'FAILED':>10}")

    # ── NAMD solvated CUDASOAintegrate (new) ────────────────────────────────
    print("\n  ── NAMD3 solvated TIP3P + CUDASOAintegrate (this run) ─────────")
    print(f"  {'Tag':<14} {'mode':>16} {'n_atoms':>10} {'ns/day':>10}  {'1 µs estimate':>14}")
    print("  " + "-" * 60)
    for r in namd_solv:
        nd = r.get("ns_per_day")
        tag = r.get("tag", "?")
        mode = r.get("gpu", "CUDASOAintegrate")
        if nd:
            print(f"  {tag:<14} {mode:>16} {r.get('n_atoms',0):>10,} {nd:>10.2f}  {_est(nd):>14}")
        else:
            err = r.get("error", "")[:40]
            print(f"  {tag:<14} {mode:>16} {r.get('n_atoms',0):>10,} {'FAILED':>10}  ({err})")

    # ── Summary ─────────────────────────────────────────────────────────────
    all_results = (
        [r for r in vacuum_data.get("gromacs_vacuum", []) if r.get("ns_per_day")]
        + [r for r in gmx_solv    if r.get("ns_per_day")]
        + [r for r in vacuum_data.get("namd_gbis", [])   if r.get("ns_per_day")]
        + [r for r in namd_solv   if r.get("ns_per_day")]
    )
    if not all_results:
        print(f"\n{sep}")
        return

    best = max(all_results, key=lambda r: r["ns_per_day"])

    # Best solvated result
    solv_results = [r for r in gmx_solv + namd_solv if r.get("ns_per_day")]

    print(f"\n{sep}")
    print(f"  OVERALL FASTEST : {best['tag']:16s}  {best['ns_per_day']:.2f} ns/day  "
          f"({best.get('engine','?')} {best.get('solvent','')})")

    if solv_results:
        best_solv = max(solv_results, key=lambda r: r["ns_per_day"])
        print(f"  BEST SOLVATED   : {best_solv['tag']:16s}  {best_solv['ns_per_day']:.2f} ns/day  "
              f"({best_solv.get('engine','?')} {best_solv.get('solvent','')})")

        gmx_s_best  = max((r for r in gmx_solv  if r.get("ns_per_day")),
                          key=lambda r: r["ns_per_day"], default=None)
        namd_s_best = max((r for r in namd_solv if r.get("ns_per_day")),
                          key=lambda r: r["ns_per_day"], default=None)
        if gmx_s_best and namd_s_best:
            ratio = gmx_s_best["ns_per_day"] / namd_s_best["ns_per_day"]
            faster = "GROMACS" if ratio >= 1 else "NAMD"
            print(f"  SOLVATED RATIO  : GROMACS/NAMD = {ratio:.2f}×  → {faster} is faster solvated")

        # Atom-count-normalized comparison (ns/day per 100k atoms for same physics)
        print(f"\n  Atom-count note:")
        for r in solv_results:
            nd = r["ns_per_day"]
            na = r.get("n_atoms", 1)
            norm = nd * (na / 1e6)   # ns·M_atoms / day (higher = more work done)
            print(f"    {r['tag']:<20}  {na:>10,} atoms  {nd:>7.2f} ns/day  "
                  f"(norm: {norm:.2f} ns·M_atoms/day)")

    print(f"\n  NOTES:")
    print(f"  • GROMACS solvated: tiny-dt (dt=0.01 fs, ×{DT_SCALE}), -DFLEXIBLE water, CPU PME, GPU NB")
    print(f"  • GROMACS solvated GPU PME: may fail on 105 nm elongated box (buffer limit)")
    print(f"  • NAMD solvated CUDASOAintegrate: full GPU-resident (NB+PME+bonds on GPU)")
    print(f"  • NAMD GBIS: CPU-only (Born radii on CPU, force tables degrade GPU kernel)")
    print(f"  • Vacuum GROMACS uses reaction-field; solvated uses PME — different accuracy")
    print(sep)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build",    action="store_true", help="skip build if dirs exist")
    ap.add_argument("--skip-gromacs",  action="store_true")
    ap.add_argument("--skip-namd",     action="store_true")
    args = ap.parse_args()

    gmx_run_dir  = SOUT / "gromacs_solvated_run"
    namd_run_dir = SOUT / "namd_solvated_run"

    _graceful_kill_mdrun()

    design = load_design()

    # Build
    if not args.skip_gromacs:
        build_gromacs_solvated(design, gmx_run_dir, skip=args.skip_build)
    if not args.skip_namd:
        build_namd_solvated(design, namd_run_dir, skip=args.skip_build)

    # Benchmark
    gmx_solv  = run_gromacs_solvated_benchmarks(gmx_run_dir)  if not args.skip_gromacs else []
    namd_solv = run_namd_solvated_benchmark(namd_run_dir)       if not args.skip_namd    else []

    # Load prior vacuum results
    vacuum_data = load_vacuum_results()

    # Report
    print_full_report(vacuum_data, gmx_solv, namd_solv)

    # Write JSON
    results = {
        "design": "B_tube.nadoc",
        "date": __import__("datetime").date.today().isoformat(),
        "padding_nm": PADDING_NM,
        "ion_conc_mM": ION_CONC_MM,
        "gromacs_solvated": gmx_solv,
        "namd_solvated": namd_solv,
        "vacuum_reference": vacuum_data,
    }
    out_json = SOUT / "solvated_benchmark_results.json"
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {out_json.relative_to(ROOT)}")

    # Human-readable summary
    summary_path = SOUT / "solvated_benchmark_summary.txt"
    import io as _io
    buf = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    print_full_report(vacuum_data, gmx_solv, namd_solv)
    sys.stdout = old_stdout
    summary_path.write_text(buf.getvalue())
    print(f"Summary written to {summary_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
