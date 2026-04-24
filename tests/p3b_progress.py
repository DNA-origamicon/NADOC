#!/usr/bin/env python3
"""Quick progress check for the Phase 3b validation run."""
import subprocess, glob, os, re, time
from pathlib import Path

def _find_active_dirs():
    """Find the active validate_phase3b temp dirs and run dirs."""
    # pdb2gmx working dir (tmpXXXXXX with input.pdb)
    pdb2gmx_dirs = sorted(glob.glob("/tmp/tmp*/input.pdb"),
                          key=os.path.getmtime, reverse=True)
    # kept run dirs
    kept = sorted(glob.glob("/tmp/nadoc_p3b_*"), key=os.path.getmtime, reverse=True)
    return pdb2gmx_dirs, kept

def _gmx_stage(d: Path) -> str:
    if (d / "em.log").exists() and not (d / "run.sh").exists():
        # in pdb2gmx phase — check ITP count
        n_itp = len(list(d.glob("topol_DNA_chain_*.itp")))
        return f"pdb2gmx ({n_itp} chain ITP files written)"
    if not (d / "conf_raw.gro").exists():
        return "pdb2gmx (topology)"
    if not (d / "em.tpr").exists():
        return "grompp (EM)"
    em_log = d / "em.log"
    if em_log.exists():
        txt = em_log.read_text(errors='replace')
        steps = re.findall(r'^Step\s+(\d+)', txt, re.MULTILINE)
        fmax  = re.findall(r'Fmax=\s*([\d.e+\-]+)', txt)
        step_str  = steps[-1] if steps else "?"
        fmax_str  = fmax[-1]  if fmax  else "?"
        converged = 'converged to Fmax' in txt
        if converged:
            return f"EM CONVERGED at step {step_str}  Fmax={fmax_str}"
        return f"EM running — step {step_str}  Fmax={fmax_str}"
    return "waiting for EM"

print(f"=== Phase 3b validation progress  [{time.strftime('%H:%M:%S')}] ===\n")

# Check if validate process is alive
ps = subprocess.run(['pgrep', '-f', 'validate_phase3b'], capture_output=True, text=True)
pids = ps.stdout.strip().split()
print(f"validate_phase3b PIDs: {pids if pids else 'NOT RUNNING'}")

ps2 = subprocess.run(['pgrep', '-f', 'gmx pdb2gmx'], capture_output=True, text=True)
pdb2gmx_pids = ps2.stdout.strip().split()
print(f"gmx pdb2gmx PIDs:      {pdb2gmx_pids if pdb2gmx_pids else 'not running'}")

ps3 = subprocess.run(['pgrep', '-f', 'gmx mdrun'], capture_output=True, text=True)
mdrun_pids = ps3.stdout.strip().split()
print(f"gmx mdrun PIDs:        {mdrun_pids if mdrun_pids else 'not running'}\n")

# Active pdb2gmx dir
active_dirs, _ = _find_active_dirs()
if active_dirs:
    d = Path(active_dirs[0]).parent
    n_itp = len(list(d.glob("topol_DNA_chain_*.itp")))
    n_posre = len(list(d.glob("posre_DNA_chain_*.itp")))
    has_gro = (d / "conf_raw.gro").exists()
    has_tpr = (d / "em.tpr").exists()
    has_emlog = (d / "em.log").exists()
    print(f"Active dir: {d}")
    print(f"  topology ITP files:  {n_itp}/64")
    print(f"  posre ITP files:     {n_posre}/64")
    print(f"  conf_raw.gro:        {'YES' if has_gro else 'no'}")
    print(f"  em.tpr:              {'YES' if has_tpr else 'no'}")
    if has_emlog:
        txt = (d / "em.log").read_text(errors='replace')
        steps = re.findall(r'^Step\s+(\d+)', txt, re.MULTILINE)
        fmax  = re.findall(r'Fmax=\s*([\d.e+\-]+)', txt)
        print(f"  EM step:             {steps[-1] if steps else '?'}/500")
        print(f"  Fmax:                {fmax[-1] if fmax else '?'}")

# Kept run dirs
_, kept = _find_active_dirs()
if kept:
    print(f"\nKept run dirs:")
    for kd in kept:
        p = Path(kd)
        em_log = p / "em.log"
        if em_log.exists():
            txt = em_log.read_text(errors='replace')
            steps = re.findall(r'^Step\s+(\d+)', txt, re.MULTILINE)
            conv  = 'CONVERGED' if 'converged to Fmax' in txt else 'running'
            print(f"  {p.name}: step={steps[-1] if steps else '?'} {conv}")
        else:
            print(f"  {p.name}: (no em.log yet)")

print(f"\nFull log tail:")
log = Path("/tmp/phase3b_validation.log")
if log.exists():
    lines = log.read_text(errors='replace').splitlines()
    for l in lines[-12:]:
        print(f"  {l}")
