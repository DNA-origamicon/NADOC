#!/usr/bin/env python3
"""exp51 — separate the timestep from rigidBonds and from hydrogen-mass repartitioning.

THE PROBLEM.  NADOC treats three integrator settings as one dial:

    1 fs  <-> rigidBonds none <-> plain PSF   (+ GPUresident silently dropped)
    2 fs  <-> rigidBonds all  <-> plain PSF
    4 fs  <-> rigidBonds all  <-> HMR PSF

The physics literature supports each *diagonal* (Ryckaert 1977 for constrained-bond 2 fs;
Feenstra 1999 / Hopkins 2015 for HMR 4 fs).  It does NOT support the claim that the
off-diagonal cells are unusable, and every emitter in this repo makes them unreachable:
``_segment_conf`` hard-codes ``rigid_bonds = "none" if spec.soft else "all"`` and
``eff_psf = structure_psf if fast else None``; ``build_production_conf`` branches on ``ts``
alone (md_protocols.py:1117-1137).  So no run in this repo has ever moved ONE of the three
at a time.

The audit that prompted this found that every claim tying them together rests on a
confounded or missing measurement:

  * exp49 (the sole source for "4 fs + HMR blew up within 32-73 steps", and therefore for
    the whole ``gentle`` 2 fs tier) moved the timestep AND the mass set together, wrote no
    result artefact that still exists, and -- see PHASE 0 below -- calls
    ``prepare_mgh_slow_release`` WITHOUT ``fast=True``, so the ``{stem}_hmr.psf`` its 4 fs
    arm names is never written by that call at all.
  * "4 fs is structurally indistinguishable from 2 fs" cites exp47, which held the
    timestep at 4 fs in all twelve arms.  No 2-vs-4 fs structural pair exists.
  * The only 2 fs/4 fs throughput comparison also flipped GPUresident (2.8x, not ~2x).
  * The one historical 1 fs + ``rigidBonds all`` run (3x4SQ, 497k atoms) was stable, with
    no same-system control at another timestep.

THE MATRIX.  One design, one solvation, one minimisation, one restrained equilibration --
then 3 timesteps x 2 constraint settings x 2 mass sets, changing nothing else.  GPUresident
is held OFF in every cell, because it is the variable that contaminated the historical
comparisons.  The three code-sanctioned cells are marked (*).

                 rigidBonds all              rigidBonds none
    1 fs         std | hmr                   std (*) | hmr
    2 fs         std (*) | hmr               std | hmr
    4 fs         std | hmr (*)               std | hmr

PRE-REGISTERED PREDICTIONS (written before the runs; scored in the report):

  P1  1 fs + rigidBonds all is stable and drifts no worse than 1 fs + none.
      -> the 1 fs <-> flexible-bond coupling is a convention, not a requirement.
  P2  2 fs + HMR is stable and drifts no worse than 2 fs + standard masses.
      -> HMR is safe below 4 fs (md_protocols.py:828-830 asserts this, untested).
  P3  4 fs + rigidBonds all + STANDARD masses fails or drifts badly.
      -> HMR really is load-bearing at 4 fs.  Never run before, anywhere in this repo.
  P4  2 fs + rigidBonds none drifts markedly worse than 2 fs + all (X-H stretch is
      undersampled at 2 fs without constraints).
  P5  4 fs + rigidBonds none fails outright, with or without HMR.

WHAT IS MEASURED.  Survival alone is a weak test -- a run can survive while tearing base
pairs, and Langevin dynamics hides integration error by absorbing it into the bath.  So
each cell reports:

  (a) NVT probe, 25 ps: did NAMD finish, at what step did it die, C1'/WC base pairing
      afterwards against the same reference, and ns/day.
  (b) NVE probe, 10 ps from that cell's own endpoint, thermostat and barostat OFF: total
      energy drift in kcal/mol/ns/atom and temperature slope in K/ns.  This is the
      standard discriminator for whether a timestep is integrating the system correctly.

Every cell draws FRESH velocities at 300 K, because a velocity set equilibrated under one
mass assignment is not a 300 K distribution under another.

    python experiments/exp51_integrator_factorial/run_matrix.py workspace/2hb_1xT.nadoc \\
        -o experiments/exp51_integrator_factorial/runs/2hb_1xT

Do not run this while another NAMD job owns the GPU -- contention invalidates every
timing and can itself cause spurious instability.  Check nvidia-smi first.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core.md_health import build_c1_pairs, build_wc_pairs, run_health_check  # noqa: E402
from backend.core.md_protocols import (  # noqa: E402
    CUTOFF_ANG,
    PAIRLISTDIST_ANG,
    PME_GRID_SPACING,
    SWITCHDIST_ANG,
    SegmentSpec,
    _min_conf,
    _segment_conf,
    minimize_steps_for_atoms,
    prepare_mgh_slow_release,
)
from backend.core.models import Design  # noqa: E402
from backend.core.namd_runner import find_namd  # noqa: E402
from backend.core.sequences import assign_scaffold_sequence  # noqa: E402

#: Long enough for a constraint failure to have certainly happened.
NVT_PS = 25.0
#: Energy-drift window.  Short on purpose: drift is a slope, and a cell that is going to
#: diverge does so early.
NVE_PS = 10.0
#: Restrained settling shared by every cell, so they all start from one state.
EQUIL_PS = 50.0

#: (timestep_fs, rigidbonds, masses).  `masses` picks the PSF: "std" or "hmr".
TIMESTEPS = (1.0, 2.0, 4.0)
RIGID = ("all", "none")
MASSES = ("std", "hmr")

#: The three combinations the shipped code can actually emit.
SANCTIONED = {(1.0, "none", "std"), (2.0, "all", "std"), (4.0, "all", "hmr")}


def cell_id(dt: float, rigid: str, mass: str) -> str:
    return f"dt{dt:g}_{rigid}_{mass}"


# ── NAMD ────────────────────────────────────────────────────────────────────────
def _run_namd(conf: Path, cwd: Path, namd: str, threads: int) -> dict:
    """Run one conf to completion; return survival, last step, ns/day and the log path."""
    log = cwd / f"{conf.stem}.log"
    t0 = time.monotonic()
    with log.open("w") as fh:
        proc = subprocess.run(
            [namd, f"+p{threads}", "+setcpuaffinity", conf.name],
            cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    wall = time.monotonic() - t0
    text = log.read_text(errors="ignore")
    # Only genuine ERROR/FATAL lines.  NAMD prints an INFO line mentioning "moving too
    # fast" on EVERY healthy run, which is why this matches on the line prefix.
    died = None
    for line in text.splitlines():
        s = line.strip()
        if not (s.startswith("ERROR:") or s.startswith("FATAL ERROR")):
            continue
        died = s
        break
    finished = "End of program" in text
    last_step = 0
    for line in reversed(text.splitlines()):
        if line.startswith("ENERGY:"):
            try:
                last_step = int(line.split()[1])
            except (IndexError, ValueError):
                pass
            break
    ns_day = None
    bm = re.findall(r"Benchmark time:.*?([\d.eE+-]+) s/step\s+([\d.eE+-]+) (ns/day|days/ns)",
                    text)
    if bm:
        val, unit = float(bm[-1][1]), bm[-1][2]
        ns_day = val if unit == "ns/day" else (1.0 / val if val else None)
    return {"ok": proc.returncode == 0 and died is None and finished,
            "returncode": proc.returncode, "error": died, "finished": finished,
            "last_step": last_step, "ns_day": ns_day, "wall_s": round(wall, 1),
            "log": log.name}


def _energy_series(log: Path) -> dict:
    """Parse ENERGY: lines into {column: [values]} using the ETITLE header for names."""
    cols: list[str] = []
    out: dict[str, list[float]] = {}
    for line in log.read_text(errors="ignore").splitlines():
        if line.startswith("ETITLE:"):
            if not cols:
                cols = line.split()[1:]
                out = {c: [] for c in cols}
            continue
        if line.startswith("ENERGY:") and cols:
            parts = line.split()[1:]
            if len(parts) < len(cols):
                continue
            for c, v in zip(cols, parts):
                try:
                    out[c].append(float(v))
                except ValueError:
                    out[c].append(float("nan"))
    return out


def _slope(x: list[float], y: list[float]) -> "float | None":
    """Least-squares slope of y on x, or None if there is nothing to fit."""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / sxx


def _drift(log: Path, dt_fs: float, n_atoms: int) -> dict:
    """Total-energy and temperature drift over the LAST HALF of an NVE run.

    The first half is discarded: a fresh-velocity start relaxes into its own ensemble,
    and that transient is not integration error.
    """
    e = _energy_series(log)
    ts, tot, temp = e.get("TS", []), e.get("TOTAL", []), e.get("TEMP", [])
    if len(ts) < 6 or len(tot) != len(ts):
        return {"error": "too few energy samples"}
    half = len(ts) // 2
    ns = [s * dt_fs * 1e-6 for s in ts[half:]]
    de = _slope(ns, tot[half:])
    dT = _slope(ns, temp[half:]) if len(temp) == len(ts) else None
    span = ns[-1] - ns[0] if ns else 0.0
    return {
        "samples": len(ts) - half,
        "window_ns": round(span, 6),
        "total_kcal_per_ns": None if de is None else round(de, 3),
        "total_kcal_per_ns_per_atom": None if de is None else round(de / max(1, n_atoms), 8),
        "temp_K_per_ns": None if dT is None else round(dT, 3),
        "temp_first": round(temp[half], 2) if temp else None,
        "temp_last": round(temp[-1], 2) if temp else None,
    }


# ── Confs ───────────────────────────────────────────────────────────────────────
def _conf(*, name: str, psf: str, stem: str, extras: str, start: str, thermostat: str,
          rigid: str, dt: float, steps: int, dcd_freq: int, energy_freq: int) -> str:
    """One matrix-cell conf.

    Written here rather than through ``_segment_conf`` for one reason: that writer COUPLES
    the three axes this experiment exists to separate (rigidBonds follows ``spec.soft``,
    the PSF follows ``fast``).  Everything that is not under test -- force field, PME,
    cutoffs, switching, exclusions, wrapping -- is imported from the production module, so
    those lines are identical to what a real job runs.
    """
    return f"""\
structure          {psf}
coordinates        {stem}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
wrapAll            off
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         {SWITCHDIST_ANG:.1f}
cutoff             {CUTOFF_ANG:.1f}
pairlistdist       {PAIRLISTDIST_ANG:.1f}
PME                yes
PMEGridSpacing     {PME_GRID_SPACING:g}

# ── the three axes under test ──
rigidBonds         {rigid}
rigidTolerance     1.0e-8
timestep           {dt:g}
# GPUresident is deliberately ABSENT from every cell: it is the variable that
# contaminated the historical 2 fs vs 4 fs comparison.
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

{thermostat}
{start}
outputname         output/{name}
outputEnergies     {energy_freq}
restartfreq        {max(steps, 1)}
binaryrestart      yes
dcdfreq            {dcd_freq}

run                {steps}
"""


def _nvt_thermostat() -> str:
    # Constant VOLUME: the barostat is a second integrator with its own stability
    # behaviour, and holding the cell fixed keeps this matrix about the equations of
    # motion.  langevinHydrogen off matches every production conf in the repo.
    return ("langevin           on\n"
            "langevinTemp       300\n"
            "langevinDamping    1\n"
            "langevinHydrogen   off\n")


def _nve_thermostat() -> str:
    # Nothing.  No thermostat, no barostat -- the only way to see integration error
    # instead of watching a bath absorb it.
    return "langevin           off\n"


# ── The experiment ──────────────────────────────────────────────────────────────
def _prepare(design: Design, out: Path, *, fast: bool) -> dict:
    """Solvate + build a package.  Returns paths and whether the HMR PSF was written."""
    d = out / ("pkg_fast" if fast else "pkg_plain")
    d.mkdir(parents=True, exist_ok=True)
    sub, stem, _segs = prepare_mgh_slow_release(
        design, d, fast=fast, declash=False, force_soft=False, require_full_topology=True)
    pkg = d / sub
    return {"pkg": pkg, "stem": stem,
            "psf_std": pkg / f"{stem}.psf",
            "psf_hmr": pkg / f"{stem}_hmr.psf",
            "hmr_written": (pkg / f"{stem}_hmr.psf").exists()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("design", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--skip-plain-prep", action="store_true",
                    help="skip the fast=False control prep (PHASE 0b)")
    ap.add_argument("--scaffold", default="M13mp18",
                    help="scaffold sequence to assign IN MEMORY if the design has none")
    args = ap.parse_args()

    if args.fresh and args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    namd = find_namd()
    design = Design.model_validate_json(args.design.read_text())
    # An all-atom build refuses an unsequenced scaffold (every unassigned base would be
    # built as thymine).  Assign in memory only — the design file on disk is never
    # written, so the workspace copy stays exactly as the user left it.  The sequence is
    # identical across every cell, so it cannot bias the comparison.
    scaffold_assigned = None
    if not any(s.sequence for s in design.strands if s.strand_type == "scaffold"):
        design, total_nt, padded = assign_scaffold_sequence(design, args.scaffold)
        scaffold_assigned = {"scaffold": args.scaffold, "total_nt": total_nt,
                             "padded_nt": padded}
        print(f"scaffold: none in file → assigned {args.scaffold} "
              f"({total_nt} nt, {padded} padded)")
    print(f"NAMD:   {namd}\ndesign: {args.design.name}\nout:    {args.out}\n")

    report: dict = {"design": str(args.design), "namd": str(namd),
                    "scaffold_assigned": scaffold_assigned,
                    "nvt_ps": NVT_PS, "nve_ps": NVE_PS, "equil_ps": EQUIL_PS}

    # ── PHASE 0: does prep write the HMR PSF, and only when asked? ───────────────
    print("[0a] prepare fast=True  (expect BOTH PSFs)")
    fast_pkg = _prepare(design, args.out, fast=True)
    pkg, stem = fast_pkg["pkg"], fast_pkg["stem"]
    print(f"     package {pkg.name}: hmr_psf_written={fast_pkg['hmr_written']}")
    if not fast_pkg["hmr_written"]:
        print("     FATAL: no HMR PSF even with fast=True — cannot run the mass axis")
        return 1
    if not args.skip_plain_prep:
        print("[0b] prepare fast=False (exp49's call — expect NO hmr psf)")
        plain = _prepare(design, args.out, fast=False)
        print(f"     package {plain['pkg'].name}: hmr_psf_written={plain['hmr_written']}")
        report["exp49_psf_check"] = {
            "fast_true_wrote_hmr": fast_pkg["hmr_written"],
            "fast_false_wrote_hmr": plain["hmr_written"],
            "verdict": ("exp49's 4 fs arm named a PSF its own prep call never wrote"
                        if not plain["hmr_written"] else
                        "prep writes the HMR PSF regardless of fast — exp49 is unaffected"),
        }
        print(f"     -> {report['exp49_psf_check']['verdict']}")

    pdb = pkg / f"{stem}.pdb"
    n_atoms = sum(1 for ln in pdb.read_text().splitlines()
                  if ln.startswith(("ATOM", "HETATM")))
    box = json.loads((pkg / "manifest.json").read_text())["box_ang"]
    mgh = (pkg / "mgh_extrabonds.txt").exists()
    extras = ("extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n"
              if mgh else "")
    report["n_atoms"] = n_atoms
    print(f"\n     {n_atoms:,} atoms, box {['%.1f' % b for b in box]}, "
          f"mgh_extrabonds={mgh}")

    # ── PHASE 1: one minimisation + one restrained equilibration for everybody ───
    min_steps = minimize_steps_for_atoms(n_atoms)
    min_name = f"{stem}_x51_min"
    (pkg / f"{min_name}.conf").write_text(
        _min_conf(min_name, stem, tuple(box), mgh, min_steps, 0.5))
    print(f"\n[1a] minimise {min_steps:,} steps")
    m = _run_namd(pkg / f"{min_name}.conf", pkg, namd, args.threads)
    print(f"     {'ok' if m['ok'] else 'FAILED'} ({m['wall_s']}s) {m['error'] or ''}")
    report["minimise"] = m
    if not m["ok"]:
        return 1

    eq_name = f"{stem}_x51_equil"
    eq_steps = int(EQUIL_PS * 1000.0 / 2.0)
    eq_spec = SegmentSpec(
        name=eq_name, stage="exp51 shared equilibration", percent=100.0, steps=eq_steps,
        temp=300.0, damping=5.0, scale=0.5, npt=True, previous=min_name,
        dcd_freq=max(20, eq_steps // 5),
        extra_bonds_file=f"{stem}_k0.5.enm.extra", soft=False, timestep_fs=2.0)
    (pkg / f"{eq_name}.conf").write_text(
        _segment_conf(eq_spec, stem, tuple(box), mgh, fast=False, force_resident=False))
    print(f"[1b] shared equilibration {EQUIL_PS:g} ps @ 2 fs rigid, restrained k=0.5, NPT")
    eq = _run_namd(pkg / f"{eq_name}.conf", pkg, namd, args.threads)
    print(f"     {'ok' if eq['ok'] else 'FAILED'} ({eq['wall_s']}s, {eq['ns_day']} ns/day) "
          f"{eq['error'] or ''}")
    report["equilibration"] = eq
    if not eq["ok"]:
        return 1

    # Every cell starts from these coordinates and this cell vector, with fresh
    # velocities appropriate to its own mass set.
    start_common = (f"binCoordinates     output/{eq_name}.coor\n"
                    f"extendedSystem     output/{eq_name}.xsc\n"
                    f"temperature        300\n")

    c1 = build_c1_pairs(pkg / f"{stem}.psf", pdb)
    wc = build_wc_pairs(pkg / f"{stem}.psf", pdb)
    report["n_c1_pairs"] = int(len(c1.pi))
    report["n_wc_pairs"] = len(wc)

    # ── PHASE 2+3: the factorial ────────────────────────────────────────────────
    cells: dict[str, dict] = {}
    print(f"\n[2] factorial: {len(TIMESTEPS) * len(RIGID) * len(MASSES)} cells "
          f"x (NVT {NVT_PS:g} ps + NVE {NVE_PS:g} ps)\n")
    print(f"    {'cell':22s} {'NVT':>6s} {'step':>8s} {'c1':>6s} {'ns/day':>8s} "
          f"{'NVE drift kcal/ns/atom':>24s} {'dT K/ns':>9s}")

    for dt in TIMESTEPS:
        for rigid in RIGID:
            for mass in MASSES:
                cid = cell_id(dt, rigid, mass)
                psf = f"{stem}_hmr.psf" if mass == "hmr" else f"{stem}.psf"

                nvt_name = f"{stem}_x51_{cid}_nvt"
                nvt_steps = max(100, int(round(NVT_PS * 1000.0 / dt)))
                nvt_steps -= nvt_steps % 20
                e_freq = max(20, int(round(100.0 / dt)))     # ~1 sample / 0.1 ps
                (pkg / f"{nvt_name}.conf").write_text(_conf(
                    name=nvt_name, psf=psf, stem=stem, extras=extras,
                    start=start_common, thermostat=_nvt_thermostat(), rigid=rigid, dt=dt,
                    steps=nvt_steps, dcd_freq=max(20, nvt_steps // 10),
                    energy_freq=e_freq))
                r = _run_namd(pkg / f"{nvt_name}.conf", pkg, namd, args.threads)

                health = {}
                if r["ok"]:
                    try:
                        h = run_health_check(pkg, nvt_name, stem)
                        health = {"c1_paired": h.c1_paired_fraction,
                                  "wc_ref_relative": h.wc_ref_relative_fraction,
                                  "broken_bp": h.broken_bp_count}
                    except Exception as exc:  # noqa: BLE001
                        health = {"error": str(exc)}

                nve: dict = {"skipped": "NVT failed"}
                drift: dict = {}
                if r["ok"]:
                    nve_name = f"{stem}_x51_{cid}_nve"
                    nve_steps = max(100, int(round(NVE_PS * 1000.0 / dt)))
                    nve_steps -= nve_steps % 20
                    (pkg / f"{nve_name}.conf").write_text(_conf(
                        name=nve_name, psf=psf, stem=stem, extras=extras,
                        start=(f"binCoordinates     output/{nvt_name}.coor\n"
                               f"binVelocities      output/{nvt_name}.vel\n"
                               f"extendedSystem     output/{nvt_name}.xsc\n"),
                        thermostat=_nve_thermostat(), rigid=rigid, dt=dt,
                        steps=nve_steps, dcd_freq=max(20, nve_steps // 5),
                        energy_freq=e_freq))
                    nve = _run_namd(pkg / f"{nve_name}.conf", pkg, namd, args.threads)
                    drift = _drift(pkg / nve["log"], dt, n_atoms)

                cells[cid] = {
                    "timestep_fs": dt, "rigidbonds": rigid, "masses": mass,
                    "psf": psf, "sanctioned": (dt, rigid, mass) in SANCTIONED,
                    "nvt": r, "health": health, "nve": nve, "drift": drift,
                }
                per_atom = drift.get("total_kcal_per_ns_per_atom")
                print(f"    {cid:22s} {'ok' if r['ok'] else 'FAIL':>6s} "
                      f"{r['last_step']:>8,} {health.get('c1_paired', '—'):>6} "
                      f"{(r['ns_day'] or 0):>8.1f} "
                      f"{('—' if per_atom is None else f'{per_atom:+.3e}'):>24s} "
                      f"{(drift.get('temp_K_per_ns') if drift.get('temp_K_per_ns') is not None else '—'):>9}"
                      + (f"  {r['error']}" if r["error"] else ""))

    report["cells"] = cells
    (args.out / "exp51_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\n    report: {args.out / 'exp51_report.json'}")

    # ── Score the pre-registered predictions ────────────────────────────────────
    def ok(cid: str) -> bool:
        c = cells.get(cid, {})
        return bool(c.get("nvt", {}).get("ok")) and (c.get("health", {}).get("c1_paired") or 0) >= 0.90

    def dr(cid: str):
        return cells.get(cid, {}).get("drift", {}).get("total_kcal_per_ns_per_atom")

    def cmp_drift(a: str, b: str, tol: float = 1.5) -> "bool | None":
        """Is |drift(a)| no worse than tol x |drift(b)|?"""
        x, y = dr(a), dr(b)
        if x is None or y is None:
            return None
        return abs(x) <= tol * abs(y)

    print("\n=== PRE-REGISTERED PREDICTIONS ===")
    verdicts = {
        "P1 1 fs + rigid is stable and no worse than 1 fs flexible":
            ok("dt1_all_std") and (cmp_drift("dt1_all_std", "dt1_none_std") is not False),
        "P2 2 fs + HMR is stable and no worse than 2 fs standard masses":
            ok("dt2_all_hmr") and (cmp_drift("dt2_all_hmr", "dt2_all_std") is not False),
        "P3 4 fs + rigid + STANDARD masses is unusable (HMR is load-bearing)":
            (not ok("dt4_all_std")) or (cmp_drift("dt4_all_std", "dt4_all_hmr") is False),
        "P4 2 fs + flexible drifts worse than 2 fs + rigid":
            cmp_drift("dt2_none_std", "dt2_all_std") is False,
        "P5 4 fs + flexible fails with or without HMR":
            (not ok("dt4_none_std")) and (not ok("dt4_none_hmr")),
    }
    for text, held in verdicts.items():
        print(f"  {'HELD    ' if held else 'REFUTED '} {text}")
    report["predictions"] = {k: bool(v) for k, v in verdicts.items()}
    (args.out / "exp51_report.json").write_text(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
