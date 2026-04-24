"""
test_gromacs_health.py — Base-pair C1'–C1' distance health checks.

Tests simple DNA duplex structures to verify:
  1. build_gromacs_package produces geometrically correct PDB/GRO
  2. Energy minimisation preserves B-DNA geometry (C1'–C1' ≈ 10.4 Å)
  3. Short restrained NVT maintains base-pair integrity

B-DNA reference:  C1'–C1' = 10.4 Å  (ideal)
Health thresholds: intact < 12 Å | strained 12–15 Å | disrupted > 15 Å

Usage (from repo root, miniforge python):
    /home/jojo/miniforge3/bin/python test_gromacs_health.py
    /home/jojo/miniforge3/bin/python test_gromacs_health.py --keep
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

import numpy as np

# ── NADOC imports ─────────────────────────────────────────────────────────────
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix,
    LatticeType, Strand, StrandType, Vec3,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.gromacs_package import build_gromacs_package, _find_gmx
from backend.core.bp_analysis import (
    analyse_duplex_gro,
    BpDistanceReport,
)


# ══════════════════════════════════════════════════════════════════════════════
# §1  DESIGN FACTORIES
# ══════════════════════════════════════════════════════════════════════════════

def make_duplex(n_bp: int, name: str | None = None) -> Design:
    """
    Single-helix antiparallel B-DNA duplex with ``n_bp`` base pairs.

    Strand 0 (scaffold): FORWARD, bp 0 … n_bp-1, 5'→3'
    Strand 1 (staple):   REVERSE, bp n_bp-1 … 0, 5'→3'
    """
    name = name or f"duplex_{n_bp}bp"
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=n_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=n_bp,
    )
    scaffold = Strand(
        id="fwd",
        domains=[Domain(
            helix_id="h0", start_bp=0, end_bp=n_bp - 1,
            direction=Direction.FORWARD,
        )],
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="rev",
        domains=[Domain(
            helix_id="h0", start_bp=n_bp - 1, end_bp=0,
            direction=Direction.REVERSE,
        )],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        id=name,
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.SQUARE,
        metadata=DesignMetadata(name=name),
    )


# ══════════════════════════════════════════════════════════════════════════════
# §2  FAST-MODE MDP TEMPLATES  (fewer steps, same physics as production)
# ══════════════════════════════════════════════════════════════════════════════

# EM: 5 000 steps, loose tolerance — converges in seconds for small duplexes.
_EM_FAST = textwrap.dedent("""\
    integrator    = steep
    emtol         = 100.0
    emstep        = 0.01
    nsteps        = 5000
    cutoff-scheme = Verlet
    pbc           = xyz
    nstlist       = 20
    coulombtype   = reaction-field
    rcoulomb      = 1.2
    epsilon-rf    = 80.0
    vdwtype       = cutoff
    vdw-modifier  = force-switch
    rvdw-switch   = 1.0
    rvdw          = 1.2
    nstxout       = 0
    nstvout       = 0
    nstenergy     = 500
    nstlog        = 500
""")

# NVT: 500 steps = 1 ps, with POSRES — just enough to check thermal stability.
_NVT_FAST = textwrap.dedent("""\
    integrator           = sd
    dt                   = 0.002
    nsteps               = 500
    define               = -DPOSRES
    refcoord_scaling     = com
    tc-grps              = System
    tau-t                = 10.0
    ref-t                = 310
    ld-seed              = -1
    pcoupl               = no
    nstlog               = 100
    nstenergy            = 100
    nstxout-compressed   = 500
    compressed-x-precision = 1000
    cutoff-scheme        = Verlet
    pbc                  = xyz
    nstlist              = 20
    coulombtype          = reaction-field
    rcoulomb             = 1.2
    epsilon-rf           = 80.0
    vdwtype              = cutoff
    vdw-modifier         = force-switch
    rvdw-switch          = 1.0
    rvdw                 = 1.2
    constraints          = h-bonds
    constraint-algorithm = LINCS
    lincs-iter           = 1
    lincs-order          = 4
    gen-vel              = yes
    gen-temp             = 310
    gen-seed             = -1
    comm-mode            = Linear
    nstcomm              = 100
""")


# ══════════════════════════════════════════════════════════════════════════════
# §3  GROMACS RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def _gmx(cmd: list[str], cwd: Path, log_path: Path, gmx: str) -> None:
    """Run a single GROMACS command, raise RuntimeError on non-zero exit."""
    result = subprocess.run(
        [gmx] + cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    log_path.write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"gmx {cmd[0]} failed (see {log_path}):\n"
            f"{result.stderr[-1500:]}"
        )


def run_simulation(pkg_dir: Path, gmx: str, ncpu: int) -> dict[str, Path]:
    """
    Run EM (5 000 steps) + restrained NVT (500 steps) inside ``pkg_dir``.

    Returns a dict of labelled GRO snapshot paths:
      ``conf``  — initial structure (before EM)
      ``em``    — post energy-minimisation
      ``nvt``   — post NVT equilibration (1 ps, position-restrained)
    """
    out = pkg_dir / "output"
    out.mkdir(exist_ok=True)
    log = pkg_dir / "logs"
    log.mkdir(exist_ok=True)

    # Write fast-mode MDP files alongside the bundled ones.
    (pkg_dir / "_em_fast.mdp").write_text(_EM_FAST)
    (pkg_dir / "_nvt_fast.mdp").write_text(_NVT_FAST)

    # ── EM ────────────────────────────────────────────────────────────────────
    _gmx(["grompp",
          "-f", "_em_fast.mdp", "-c", "conf.gro", "-p", "topol.top",
          "-o", "output/em.tpr", "-maxwarn", "20", "-nobackup"],
         pkg_dir, log / "em_grompp.log", gmx)

    _gmx(["mdrun", "-v", "-deffnm", "output/em",
          "-ntmpi", "1", "-ntomp", str(ncpu), "-nobackup"],
         pkg_dir, log / "em_mdrun.log", gmx)

    # ── NVT restrained ────────────────────────────────────────────────────────
    # -r is required since GROMACS 2018 whenever define = -DPOSRES is active:
    # it provides the reference coordinates for position restraints.
    # We restrain to the EM-minimised structure (not conf.gro) so that the
    # POSRES target matches the force-field-relaxed geometry.
    _gmx(["grompp",
          "-f", "_nvt_fast.mdp", "-c", "output/em.gro", "-r", "output/em.gro",
          "-p", "topol.top", "-o", "output/nvt.tpr", "-maxwarn", "20", "-nobackup"],
         pkg_dir, log / "nvt_grompp.log", gmx)

    _gmx(["mdrun", "-v", "-deffnm", "output/nvt",
          "-ntmpi", "1", "-ntomp", str(ncpu), "-nobackup"],
         pkg_dir, log / "nvt_mdrun.log", gmx)

    return {
        "conf": pkg_dir / "conf.gro",
        "em":   out / "em.gro",
        "nvt":  out / "nvt.gro",
    }


# ══════════════════════════════════════════════════════════════════════════════
# §4  TEST RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def _strand_lengths(design: Design) -> list[int]:
    return [
        sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)
        for s in design.strands
    ]


def run_test(
    design: Design,
    name: str,
    gmx: str,
    ncpu: int,
    keep_dir: Path | None = None,
) -> bool:
    """
    Build, simulate, and health-check a single duplex design.
    Returns True if all snapshots pass the C1'–C1' distance criteria.
    """
    n_bp = design.helices[0].length_bp
    slens = _strand_lengths(design)

    _bar = "─" * 62
    print(f"\n┌{_bar}┐")
    print(f"│  TEST: {name:<54}│")
    print(f"│  {n_bp} bp, {len(design.strands)} strands, "
          f"strand lengths {slens}"
          f"{' ' * max(0, 36 - len(str(slens)))}│")
    print(f"└{_bar}┘")

    # ── build ZIP ──────────────────────────────────────────────────────────────
    print("  [1/3] Building GROMACS package…", end=" ", flush=True)
    try:
        zip_bytes = build_gromacs_package(design)
        print(f"OK  ({len(zip_bytes):,} bytes)")
    except Exception as exc:
        print(f"FAIL\n        {exc}")
        return False

    # ── extract ZIP ────────────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpstr:
        tmpdir = Path(tmpstr)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmpdir)
        subdirs = [p for p in tmpdir.iterdir() if p.is_dir()]
        extracted = subdirs[0] if subdirs else tmpdir

        if keep_dir is not None:
            pkg_dir = keep_dir / name
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir)
            shutil.copytree(extracted, pkg_dir)
            work_dir = pkg_dir
        else:
            work_dir = extracted

        # ── run simulation ─────────────────────────────────────────────────────
        print(f"  [2/3] Running EM + NVT (ncpu={ncpu})…", end=" ", flush=True)
        try:
            snapshots = run_simulation(work_dir, gmx, ncpu)
            print("OK")
        except Exception as exc:
            print(f"FAIL\n        {exc}")
            return False

        # ── analyse base pair distances ────────────────────────────────────────
        print(f"  [3/3] C1'–C1' base pair distances (ideal = 10.4 Å):")
        print(f"        {'snapshot':<20}  {'mean':>7}  {'std':>5}  "
              f"{'min':>7}  {'max':>7}  "
              f"{'intact%':>8}  {'strained%':>9}  verdict")
        print("        " + "─" * 72)

        labels = {
            "conf": "initial (pre-EM)",
            "em":   "post-EM",
            "nvt":  "post-NVT (1 ps, POSRES)",
        }
        all_pass = True
        reports: list[BpDistanceReport] = []

        for key, gro_path in snapshots.items():
            label = labels[key]
            try:
                r = analyse_duplex_gro(gro_path, n_bp,
                                       strand_lengths=slens, label=label)
                reports.append(r)
                v = r.verdict
                v_str = f"[{v}]" if v == "PASS" else f"[{v}] ◄"
                print(
                    f"        {label:<20}  "
                    f"{r.mean:>7.3f}  {r.std:>5.3f}  "
                    f"{r.min:>7.3f}  {r.max:>7.3f}  "
                    f"{r.intact_pct:>8.1f}  {r.strained_pct:>9.1f}  {v_str}"
                )
                if v != "PASS":
                    all_pass = False
            except Exception as exc:
                print(f"        {label:<20}  ERROR: {exc}")
                all_pass = False

        # Per-pair detail only if there is a failure or warning
        if not all_pass:
            for r in reports:
                if r.verdict != "PASS":
                    print(f"\n  Per-pair table [{r.label}]:")
                    print(textwrap.indent(r.per_pair_table(), "    "))

        # Save per-pair tables to disk when keeping output
        if keep_dir is not None:
            for r in reports:
                fname = r.label.replace(" ", "_").replace("(", "").replace(")", "") + "_bp.txt"
                (work_dir / fname).write_text(r.per_pair_table())

        return all_pass


# ══════════════════════════════════════════════════════════════════════════════
# §5  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    keep = "--keep" in sys.argv
    keep_dir = Path("bp_health_runs") if keep else None

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  GROMACS base-pair health check — C1′–C1′ distance metric   ║")
    print("║  B-DNA ideal: 10.4 Å | intact <12 | strained 12-15 | >15 Å ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Prefer the conda/miniforge gmx (CUDA-enabled, newer) over the apt one.
    # shutil.which() picks the first match in PATH, which is usually the apt
    # binary (/usr/bin/gmx).  Check the conda prefix first.
    _conda_gmx = Path("/home/jojo/miniforge3/bin/gmx")
    if _conda_gmx.exists():
        gmx = str(_conda_gmx)
    else:
        try:
            gmx = _find_gmx()
        except RuntimeError as exc:
            print(f"\n[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)

    ncpu = min(8, os.cpu_count() or 4)
    print(f"\n  GROMACS : {gmx}")
    print(f"  CPUs    : {ncpu}")
    if keep_dir:
        print(f"  Output  : {keep_dir.resolve()}/")

    # ── test cases ────────────────────────────────────────────────────────────
    cases: list[tuple[Design, str]] = [
        (make_duplex(12, "duplex_12bp"), "duplex_12bp — 12 bp (one helical turn)"),
        (make_duplex(21, "duplex_21bp"), "duplex_21bp — 21 bp (two helical turns)"),
        (make_duplex(42, "duplex_42bp"), "duplex_42bp — 42 bp (four helical turns)"),
    ]

    results: dict[str, bool] = {}
    for design, label in cases:
        passed = run_test(design, design.id, gmx, ncpu, keep_dir=keep_dir)
        results[label] = passed

    # ── summary ───────────────────────────────────────────────────────────────
    print("\n┌────────────────────────────────────────────────────────────┐")
    print("│  SUMMARY                                                   │")
    print("├────────────────────────────────────────────────────────────┤")
    for label, passed in results.items():
        status = "PASS" if passed else "FAIL"
        pad = 54 - len(label)
        print(f"│  {label}{' ' * pad}{status}  │")
    print("└────────────────────────────────────────────────────────────┘")

    if all(results.values()):
        print("\n[PASS] All tests passed.\n")
        sys.exit(0)
    else:
        print("\n[FAIL] One or more tests failed.\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
