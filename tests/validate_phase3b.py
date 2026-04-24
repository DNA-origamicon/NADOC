#!/usr/bin/env python3
"""
Phase 3b validation — per-strand ARBD spline vs ideal B-DNA baseline.

Compares GROMACS EM step count and initial LJ energy between:
  1. Ideal B-DNA starting structure (baseline)
  2. Phase 3b: per-strand CubicSpline from mrdna ARBD fine-stage positions

Success criterion: Phase 3b EM converges in significantly fewer steps than
baseline, demonstrating that CG pre-relax resolves crossover LJ clashes.

Usage:
    python tests/validate_phase3b.py [--keep] [--mrdna-dir DIR]

    --keep         Keep GROMACS run directories after completion
    --mrdna-dir    Path to mrdna output directory (default: /tmp/mrdna_u6hb_rerun)
    --stage        mrdna stage index to use for fine-stage PSF/DCD (default: 2)
    --stem         mrdna output stem name (default: u6hb_loop_fix)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.core.gromacs_package import _build_gromacs_input_pdb, _find_gmx

_DEFAULT_MRDNA_DIR = Path("/tmp/mrdna_u6hb_rerun")
_DEFAULT_STEM      = "u6hb_loop_fix"
_DEFAULT_STAGE     = 2
_DESIGN_FILE       = ROOT / "Examples" / "U6hb.nadoc"
_EM_MAX_STEPS      = 500

_EM_MDP = """\
integrator  = steep
nsteps      = {nsteps}
emtol       = 1000.0
emstep      = 0.01
nstxout     = 0
nstlog      = 10
nstenergy   = 10
coulombtype = PME
rcoulomb    = 1.0
vdwtype     = cut-off
rvdw        = 1.0
pbc         = xyz
"""


def _load_design() -> Design:
    return Design.model_validate_json(_DESIGN_FILE.read_text())


def _run_em_only(run_dir: Path, design: Design,
                 nuc_pos_override: dict | None = None,
                 label: str = "baseline") -> dict:
    """
    Build PDB, run pdb2gmx + grompp + mdrun (EM only), return stats dict.
    Calls GROMACS directly — no run.sh intermediary.
    """
    gmx = _find_gmx()
    ff  = "charmm36-feb2026_cgenff-5.0"

    # ── 1. Build input PDB ────────────────────────────────────────────────
    pdb_text = _build_gromacs_input_pdb(design, ff=ff,
                                        nuc_pos_override=nuc_pos_override)
    input_pdb = run_dir / "input.pdb"
    input_pdb.write_text(pdb_text)

    # ── 2. pdb2gmx ────────────────────────────────────────────────────────
    pdb_lines = [l for l in pdb_text.splitlines() if l.startswith(("ATOM", "HETATM"))]
    n_chains  = 1 + sum(1 for a, b in zip(pdb_lines, pdb_lines[1:]) if a[21] != b[21])

    r = subprocess.run(
        [gmx, "pdb2gmx", "-f", "input.pdb", "-o", "conf.gro",
         "-p", "topol.top", "-ignh", "-ff", ff, "-water", "none",
         "-nobackup", "-ter"],
        input="4\n6\n" * n_chains,
        capture_output=True, text=True, cwd=run_dir,
    )
    if r.returncode != 0:
        print(f"  [pdb2gmx FAILED]\n{r.stderr[-1000:]}")
        return {'label': label, 'returncode': r.returncode, 'elapsed_s': 0,
                'steps': 0, 'converged': False, 'lj_initial': None,
                'error': 'pdb2gmx failed'}

    # ── 3. Write em.mdp ────────────────────────────────────────────────────
    (run_dir / "em.mdp").write_text(_EM_MDP.format(nsteps=_EM_MAX_STEPS))

    # ── 4. grompp ─────────────────────────────────────────────────────────
    r = subprocess.run(
        [gmx, "grompp", "-f", "em.mdp", "-c", "conf.gro",
         "-p", "topol.top", "-o", "em.tpr", "-maxwarn", "20", "-nobackup"],
        capture_output=True, text=True, cwd=run_dir,
    )
    if r.returncode != 0:
        print(f"  [grompp FAILED]\n{r.stderr[-1000:]}")
        return {'label': label, 'returncode': r.returncode, 'elapsed_s': 0,
                'steps': 0, 'converged': False, 'lj_initial': None,
                'error': 'grompp failed'}

    # ── 5. mdrun (EM, CPU-only steep) ─────────────────────────────────────
    t0 = time.time()
    ntomp = max(1, int(subprocess.check_output(["nproc", "--all"]).strip()) - 4)
    r = subprocess.run(
        [gmx, "mdrun", "-v", "-ntmpi", "1", "-ntomp", str(ntomp),
         "-nb", "gpu", "-deffnm", "em"],
        capture_output=True, text=True, cwd=run_dir,
    )
    elapsed = time.time() - t0

    # ── 6. Parse em.log ───────────────────────────────────────────────────
    em_log   = run_dir / "em.log"
    steps_done = 0
    lj_initial = None
    converged  = False

    if em_log.exists():
        log_txt = em_log.read_text(errors='replace')

        # Step count — last "Step=" or "Step " line
        step_matches = re.findall(r'Step=\s*(\d+)|^\s*(\d+)\s+[-\d]', log_txt, re.MULTILINE)
        last_steps = re.findall(r'^\s*(\d+)\s+[-\d.e+]', log_txt, re.MULTILINE)
        if last_steps:
            steps_done = int(last_steps[-1])

        # Initial LJ — GROMACS energy table: "LJ (SR)" is a column header;
        # the value is on the next line in the same column position.
        lines = log_txt.splitlines()
        for li, line in enumerate(lines[:-1]):
            if 'LJ (SR)' in line and li + 1 < len(lines):
                # Find position of "LJ (SR)" in the header and extract the
                # corresponding column value from the next line.
                col = line.index('LJ (SR)')
                nums = re.findall(r'[-+]?\d+\.\d+e[+-]\d+', lines[li + 1])
                hdr_nums = re.findall(r'[-+]?\d+\.\d+e[+-]\d+|\S+', line)
                # Count which column index LJ (SR) is in the header
                hdr_fields = line.split()
                lj_col = next(
                    (i for i, f in enumerate(hdr_fields) if 'LJ' in f), None
                )
                val_fields = lines[li + 1].split()
                if lj_col is not None and lj_col < len(val_fields):
                    try:
                        lj_initial = float(val_fields[lj_col])
                        break
                    except ValueError:
                        pass

        converged = ('converged to Fmax' in log_txt or
                     'Norm of force' in log_txt)

    return {
        'label':      label,
        'returncode': r.returncode,
        'elapsed_s':  elapsed,
        'steps':      steps_done,
        'converged':  converged,
        'lj_initial': lj_initial,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep',      action='store_true')
    parser.add_argument('--mrdna-dir', default=str(_DEFAULT_MRDNA_DIR))
    parser.add_argument('--stem',      default=_DEFAULT_STEM)
    parser.add_argument('--stage',     type=int, default=_DEFAULT_STAGE)
    args = parser.parse_args()

    mrdna_dir = Path(args.mrdna_dir)
    psf_path  = str(mrdna_dir / f"{args.stem}-{args.stage}.psf")
    dcd_path  = str(mrdna_dir / "output" / f"{args.stem}-{args.stage}.dcd")

    print("=== Phase 3b validation — U6hb EM benchmark ===")
    print(f"Design:    {_DESIGN_FILE}")
    print(f"mrdna PSF: {psf_path}")
    print(f"EM cap:    {_EM_MAX_STEPS} steps")
    print()

    if not Path(psf_path).exists() or not Path(dcd_path).exists():
        print("ERROR: mrdna fine-stage files not found.")
        return 1

    design = _load_design()
    print(f"Design loaded: {len(design.helices)} helices, {len(design.strands)} strands")
    print()

    results = []

    # ── Baseline ──────────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix='nadoc_p3b_baseline_') as d:
        base_dir = Path(d)
        print("Running baseline (ideal B-DNA)...")
        r = _run_em_only(base_dir, design, label='baseline')
        results.append(r)
        lj_str = f"{r['lj_initial']:.3e}" if r['lj_initial'] is not None else "N/A"
        print(f"  Steps: {r['steps']}  LJ_init: {lj_str}  "
              f"converged: {r['converged']}  time: {r['elapsed_s']:.1f}s")
        if args.keep:
            shutil.copytree(d, '/tmp/nadoc_p3b_baseline', dirs_exist_ok=True)

    print()

    # ── Phase 3b ──────────────────────────────────────────────────────────
    print("Computing per-strand spline override...")
    t0 = time.time()
    from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands
    override = nuc_pos_override_from_arbd_strands(
        design, psf_path, dcd_path, frame=-1, sigma_nt=1.5
    )
    print(f"  Override: {len(override)} entries in {time.time()-t0:.1f}s")
    print()

    with tempfile.TemporaryDirectory(prefix='nadoc_p3b_spline_') as d:
        spline_dir = Path(d)
        print("Running Phase 3b (per-strand spline)...")
        r = _run_em_only(spline_dir, design, nuc_pos_override=override, label='phase3b')
        results.append(r)
        lj_str = f"{r['lj_initial']:.3e}" if r['lj_initial'] is not None else "N/A"
        print(f"  Steps: {r['steps']}  LJ_init: {lj_str}  "
              f"converged: {r['converged']}  time: {r['elapsed_s']:.1f}s")
        if args.keep:
            shutil.copytree(d, '/tmp/nadoc_p3b_spline', dirs_exist_ok=True)

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("=== Results ===")
    print(f"{'Label':<12} {'Steps':>8} {'LJ_initial':>14} {'Converged':>10} {'Time(s)':>8}")
    for r in results:
        lj = f"{r['lj_initial']:.3e}" if r['lj_initial'] is not None else "N/A"
        print(f"{r['label']:<12} {r['steps']:>8} {lj:>14} {str(r['converged']):>10} "
              f"{r['elapsed_s']:>8.1f}")

    base = results[0]
    p3b  = results[1]
    if base['steps'] > 0 and p3b['steps'] > 0:
        step_ratio = p3b['steps'] / base['steps']
        print(f"\nStep ratio (Phase3b / baseline): {step_ratio:.2f}x")
        if step_ratio < 0.5:
            print("PASS — Phase 3b reduces EM steps by >50%")
            return 0
        else:
            print("MARGINAL — Phase 3b did not achieve >50% step reduction")
            return 1
    else:
        print("WARNING: Step count parse failed — check em.log files in kept dirs")
        return 1


if __name__ == "__main__":
    sys.exit(main())
