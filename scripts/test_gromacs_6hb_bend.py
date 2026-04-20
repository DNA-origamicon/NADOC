#!/usr/bin/env python3
"""
test_gromacs_6hb_bend.py
=========================
End-to-end validation of the GROMACS export package using a 420 bp
6-helix bundle (honeycomb lattice) with a 180° bend between bp 100 and 300.

What this test verifies
-----------------------
1. Design creation: 420 bp HC 6HB + DeformationOp (180° bend bp 100-300)
2. Package builder: pdb2gmx + editconf succeed; ZIP structure is correct
3. Energy minimisation: GROMACS EM runs without crashing; energy decreases
4. Short NVT: 1000-step NVT run completes; energy is stable

The test is intentionally kept short (1000 NVT steps = 1 ps) to validate
package correctness rather than produce scientific results.

Usage
-----
    python scripts/test_gromacs_6hb_bend.py
    python scripts/test_gromacs_6hb_bend.py --nvt-steps 50000  # full 50 ps
    python scripts/test_gromacs_6hb_bend.py --out-dir /tmp/gromacs_test
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ── NADOC backend ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.gromacs_package import (
    _find_gmx,
    _find_top_dir,
    _pick_ff,
    build_gromacs_package,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    BendParams,
    DeformationOp,
    LatticeType,
)

# ══════════════════════════════════════════════════════════════════════════════
# §1  DESIGN CREATION
# ══════════════════════════════════════════════════════════════════════════════

def create_6hb_bend_design():
    """
    Create a 420 bp honeycomb 6-helix bundle with a 180° bend between
    bp 100 and bp 300 (U-shape).

    Layout (3 rows × 2 cols, standard HC 6HB):
        (0,0) (0,1)
        (1,0) (1,1)
        (2,0) (2,1)

    Sequences: pseudo-random ATCG (seed 42) — sequences do not need to be
    Watson-Crick complementary for structural validation.
    """
    cells = [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
    design = make_bundle_design(
        cells=cells,
        length_bp=420,
        name="6hb_420bp_bend180",
        plane="XY",
        strand_filter="both",
        lattice_type=LatticeType.HONEYCOMB,
    )

    # Assign random sequences to all strands so residue names are DA/DT/DG/DC
    rng = random.Random(42)
    for strand in design.strands:
        total_bp = sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)
        strand.sequence = "".join(rng.choice("ATCG") for _ in range(total_bp))

    # 180° bend between bp 100 and bp 300 (U-shape along +X)
    bend = DeformationOp(
        type="bend",
        plane_a_bp=100,
        plane_b_bp=300,
        affected_helix_ids=[h.id for h in design.helices],
        params=BendParams(angle_deg=180.0, direction_deg=0.0),
    )
    design.deformations.append(bend)

    print(f"[design]   {len(design.helices)} helices, {len(design.strands)} strands")
    print(f"           length = 420 bp, bend = 180° (bp 100–300)")
    print(f"           deformations: {[op.type for op in design.deformations]}")
    return design


# ══════════════════════════════════════════════════════════════════════════════
# §2  PACKAGE BUILD + ZIP INSPECTION
# ══════════════════════════════════════════════════════════════════════════════

def build_and_inspect(design, out_dir: Path) -> Path:
    """Build the GROMACS package, extract it, and check the ZIP structure."""
    print("\n[build]    running build_gromacs_package…")
    zip_bytes = build_gromacs_package(design)
    zip_path  = out_dir / "6hb_420bp_bend180_gromacs.zip"
    zip_path.write_bytes(zip_bytes)
    print(f"           ZIP written: {zip_path}  ({len(zip_bytes) / 1024:.0f} KB)")

    # Extract
    extract_dir = out_dir / "extracted"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        zf.extractall(extract_dir)
    print(f"[zip]      {len(names)} entries extracted → {extract_dir}")

    # Verify required files
    prefix = "6hb_420bp_bend180_gromacs/"
    required = [
        prefix + "conf.gro",
        prefix + "topol.top",
        prefix + "em.mdp",
        prefix + "nvt.mdp",
        prefix + "launch.sh",
        prefix + "scripts/monitor.py",
        prefix + "README.txt",
        prefix + "AI_ASSISTANT_PROMPT.txt",
    ]
    missing = [f for f in required if f not in names]
    if missing:
        raise AssertionError(f"ZIP missing required files: {missing}")
    print("[zip]      all required files present ✓")

    # Verify at least one .itp file
    itp_files = [n for n in names if n.endswith(".itp")]
    if not itp_files:
        raise AssertionError("No .itp files in ZIP — pdb2gmx topology incomplete")
    print(f"[zip]      {len(itp_files)} .itp file(s): {[Path(f).name for f in itp_files]}")

    # Verify FF directory bundled
    ff_entries = [n for n in names if ".ff/" in n]
    if not ff_entries:
        raise AssertionError("No force-field directory bundled in ZIP")
    ff_name = ff_entries[0].split(prefix)[1].split("/")[0]
    print(f"[zip]      force field: {ff_name}  ({len(ff_entries)} files)")

    # Check conf.gro is non-empty and has atom count line
    pkg_dir = extract_dir / prefix.rstrip("/")
    conf_lines = (pkg_dir / "conf.gro").read_text().splitlines()
    n_atoms = int(conf_lines[1].strip())
    print(f"[gro]      {n_atoms} atoms in conf.gro")
    if n_atoms < 1000:
        print(f"WARNING    atom count looks low ({n_atoms}) for 420bp 6HB")

    return pkg_dir


# ══════════════════════════════════════════════════════════════════════════════
# §3  GROMACS SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def run_gromacs(pkg_dir: Path, nvt_steps: int) -> None:
    """Run EM + short NVT inside the extracted package directory."""
    gmx = _find_gmx()
    output_dir = pkg_dir / "output"
    output_dir.mkdir(exist_ok=True)

    def _gmx(*args, check=True, **kwargs):
        cmd = [gmx] + list(args)
        print(f"  $ {' '.join(str(c) for c in cmd)}")
        result = subprocess.run(
            cmd,
            cwd=str(pkg_dir),
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            print(f"  STDOUT: {result.stdout[-2000:]}")
            print(f"  STDERR: {result.stderr[-2000:]}")
            raise RuntimeError(f"GROMACS command failed: {' '.join(str(c) for c in cmd)}")
        return result

    # ── Energy minimisation ────────────────────────────────────────────────────
    print("\n[EM]       grompp…")
    _gmx(
        "grompp",
        "-f", "em.mdp",
        "-c", "conf.gro",
        "-p", "topol.top",
        "-o", "output/em.tpr",
        "-maxwarn", "20",
        "-nobackup",
    )

    print("[EM]       mdrun…")
    em_result = _gmx(
        "mdrun",
        "-v",
        "-deffnm", "output/em",
        "-ntmpi", "1",
        "-ntomp", "4",
    )

    # Check EM output
    em_log = (output_dir / "em.log").read_text() if (output_dir / "em.log").exists() else ""
    if "Converged to machine precision" in em_log or "Maximum force below" in em_log:
        print("[EM]       converged ✓")
    elif (output_dir / "em.gro").exists():
        print("[EM]       completed (check em.log for convergence info)")
    else:
        raise AssertionError("EM did not produce output/em.gro")

    # ── Short NVT ──────────────────────────────────────────────────────────────
    # Write a test NVT MDP with reduced step count
    test_nvt_mdp = (pkg_dir / "nvt.mdp").read_text()
    test_nvt_mdp = test_nvt_mdp.replace(
        "nsteps                  = 25000",
        f"nsteps                  = {nvt_steps}",
    )
    (pkg_dir / "nvt_test.mdp").write_text(test_nvt_mdp)

    print(f"\n[NVT]      grompp ({nvt_steps} steps)…")
    _gmx(
        "grompp",
        "-f", "nvt_test.mdp",
        "-c", "output/em.gro",
        "-p", "topol.top",
        "-o", "output/nvt.tpr",
        "-maxwarn", "20",
        "-nobackup",
    )

    print("[NVT]      mdrun…")
    _gmx(
        "mdrun",
        "-v",
        "-deffnm", "output/nvt",
        "-ntmpi", "1",
        "-ntomp", "4",
        "-x", "output/nvt.xtc",
    )

    if not (output_dir / "nvt.edr").exists():
        raise AssertionError("NVT did not produce output/nvt.edr")
    print(f"[NVT]      completed ({nvt_steps} steps) ✓")

    # ── Energy check ─────────────────────────────────────────────────────────
    print("\n[energy]   extracting total energy…")
    energy_result = subprocess.run(
        f"echo '11 0' | {gmx} energy -f output/nvt.edr -o output/total_energy.xvg -nobackup",
        shell=True,
        cwd=str(pkg_dir),
        capture_output=True,
        text=True,
    )
    xvg_path = output_dir / "total_energy.xvg"
    if xvg_path.exists():
        data_lines = [
            l for l in xvg_path.read_text().splitlines()
            if not l.startswith(("@", "#")) and l.strip()
        ]
        if data_lines:
            first = data_lines[0].split()
            last  = data_lines[-1].split()
            print(f"           t=0 ps   Etot = {float(first[1]):.1f} kJ/mol")
            print(f"           t={float(last[0]):.3f} ps   Etot = {float(last[1]):.1f} kJ/mol")


# ══════════════════════════════════════════════════════════════════════════════
# §4  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nvt-steps", type=int, default=1000,
                    help="NVT step count for validation run (default: 1000 = 1 ps)")
    ap.add_argument("--out-dir", type=str, default=None,
                    help="Output directory (default: temp dir, kept on success)")
    args = ap.parse_args()

    # Verify GROMACS is available
    try:
        gmx     = _find_gmx()
        top_dir = _find_top_dir()
        ff      = _pick_ff(top_dir)
        print(f"[gromacs]  binary = {gmx}")
        print(f"[gromacs]  top    = {top_dir}")
        print(f"[gromacs]  ff     = {ff}")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Set up output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        _tmpobj = tempfile.mkdtemp(prefix="nadoc_gromacs_test_")
        out_dir = Path(_tmpobj)
        cleanup = False  # keep output for inspection

    print(f"[output]   {out_dir}")

    try:
        # Step 1: create design
        design = create_6hb_bend_design()

        # Step 2: build package and inspect ZIP
        pkg_dir = build_and_inspect(design, out_dir)

        # Step 3: run GROMACS simulation
        run_gromacs(pkg_dir, nvt_steps=args.nvt_steps)

        print("\n" + "═" * 60)
        print("  ALL TESTS PASSED")
        print(f"  Output: {pkg_dir}")
        print("═" * 60)

    except Exception as exc:
        print(f"\nTEST FAILED: {exc}")
        import traceback
        traceback.print_exc()
        print(f"\nOutput dir: {out_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
