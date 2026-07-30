#!/usr/bin/env python3
"""exp49 — is the 1 fs soft start still needed once a vacuum ENRG-MD stage runs first?

THE QUESTION.  Every design that inserts extra bases at crossovers is auto-declashed,
which forces the WHOLE relaxation ladder onto the soft integrator: ``rigidBonds none`` at
**1 fs**.  That is 4x fewer nanoseconds per unit of compute than the 4 fs + HMR path, and
it applies to all 19.2 ns of ladder.

The reason it exists is narrow and mechanical: a freshly built ideal-B-DNA model carries
residual local strain — concentrated at inserted bases, which the builder places into a
junction geometry that has no relaxed conformation — and hitting that with 2 fs +
``rigidBonds all`` on the very first dynamics steps trips a RATTLE "Constraint failure".

The vacuum ENRG-MD pre-stage (Aksimentiev §3.2, shipped 2026-07-30) relaxes *exactly that
strain*, in vacuum, before a single water molecule is placed — and exp48 measured zero
broken base pairs doing it at 3k / 21k / 224k atoms.  So the hypothesis is:

    A vacuum-seeded package does not need the soft integrator at all.

If that holds, an extra-base design's ladder goes from 1 fs to 4 fs — roughly a 4x
wall-clock win on the most expensive class of design NADOC has — and the soft start
becomes a fallback for packages built WITHOUT the vacuum stage rather than a default.

THE MATRIX.  Two seeds x three integrators, on a design that currently forces declash:

                    | 1 fs soft   | 2 fs rigid  | 4 fs rigid + HMR
    ideal build     | control     | expected FAIL (this is why soft exists)
    vacuum-relaxed  | baseline    | HYPOTHESIS  | HYPOTHESIS (the real prize)

A RATTLE failure shows up in the first few thousand steps, so each arm only needs a short
run — the default 25 ps is generous.  Arms are run SEQUENTIALLY: they share one GPU, and
overlapping them would make every timing meaningless and could itself cause failures.

WHAT COUNTS AS A PASS.  Not merely "did not crash": a run can survive while quietly
tearing base pairs.  Each arm reports (a) whether NAMD exited cleanly, (b) the step it
died at if not, (c) the C1'/WC base-pairing fractions afterwards against the same
reference.  An arm that survives with degraded pairing is a FAIL for our purposes.

    python experiments/exp49_softstart_obsolescence/run_arms.py workspace/2hb_1xT.nadoc \\
        -o experiments/exp49_softstart_obsolescence/runs/2hb_1xT

⚠ Do not run this while another NAMD job owns the GPU — the contention invalidates the
timings and can produce spurious instability.  Check with `nvidia-smi` first.
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
    SegmentSpec,
    _min_conf,
    _segment_conf,
    minimize_steps_for_atoms,
    prepare_mgh_slow_release,
)
from backend.core.models import Design  # noqa: E402
from backend.core.namd_runner import find_namd  # noqa: E402
from backend.core.namd_vacuum import build_namd_vacuum_package  # noqa: E402

#: Long enough that a RATTLE failure has certainly happened, short enough to be cheap.
PROBE_PS = 25.0

#: (label, timestep_fs, soft) — `soft` selects rigidBonds none.
INTEGRATORS = [
    ("soft_1fs", 1.0, True),
    ("rigid_2fs", 2.0, False),
    ("rigid_4fs", 4.0, False),
]


def _load(path: Path) -> Design:
    return Design.model_validate_json(path.read_text())


def _run_namd(conf: Path, cwd: Path, namd: str, threads: int) -> dict:
    """Run one NAMD conf to completion; return {ok, returncode, died_at_step, wall_s}."""
    log = cwd / f"{conf.stem}.log"
    t0 = time.monotonic()
    with log.open("w") as fh:
        proc = subprocess.run(
            [namd, f"+p{threads}", "+setcpuaffinity", conf.name],
            cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    wall = time.monotonic() - t0
    text = log.read_text(errors="ignore")
    # Match only genuine ERROR/FATAL lines.  NAMD prints an INFO line on every single
    # run — "NAMD will save positions and velocities to ....crash.csv when atoms are
    # moving too fast" — and a bare substring search for "moving too fast" flags every
    # healthy run as a crash, which is exactly what it did the first time this ran.
    died = None
    for line in text.splitlines():
        s = line.strip()
        if not (s.startswith("ERROR:") or s.startswith("FATAL ERROR")):
            continue
        if ("Constraint failure" in s or "moving too fast" in s
                or "became unstable" in s or "Periodic cell has become too small" in s):
            died = s
            break
    # A clean NAMD run always ends with this; its absence means the process died.
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
    return {
        "ok": proc.returncode == 0 and died is None and finished,
        "returncode": proc.returncode,
        "rattle_error": died,
        "finished": finished,
        "last_step": last_step,
        "ns_day": ns_day,
        "wall_s": round(wall, 1),
        "log": str(log),
    }


def _vacuum_seed(design: Design, out: Path, namd: str, threads: int, ns: float) -> "Path | None":
    """Run the vacuum ENRG-MD stage; return its final .coor, or None on failure."""
    sub, stem, segs = build_namd_vacuum_package(design, out, ns=ns)
    pkg = out / sub
    print(f"  vacuum package: {pkg.name} ({segs[0].steps:,} steps @ {segs[0].timestep_fs} fs)")
    min_conf = next(pkg.glob("*_00_min_vacuum.conf"))
    r = _run_namd(min_conf, pkg, namd, threads)
    print(f"    minimise: {'ok' if r['ok'] else 'FAILED'} ({r['wall_s']}s)")
    if not r["ok"]:
        return None
    r = _run_namd(pkg / f"{segs[0].name}.conf", pkg, namd, threads)
    print(f"    relax:    {'ok' if r['ok'] else 'FAILED'} ({r['wall_s']}s, "
          f"{r['ns_day']} ns/day for {ns} ns)")
    coor = pkg / "output" / f"{segs[0].name}.coor"
    return coor if r["ok"] and coor.exists() else None


def _solute_coords(psf: Path, coor: Path):
    import MDAnalysis as mda
    return mda.Universe(str(psf), str(coor), format="NAMDBIN").atoms.positions.copy()


def _probe_arm(design: Design, out: Path, *, seed_coords, label: str,
               namd: str, threads: int) -> dict:
    """Solvate (optionally from a seed), minimise, then probe each integrator."""
    arm_dir = out / label
    arm_dir.mkdir(parents=True, exist_ok=True)
    kw = {"declash": False, "force_soft": False, "require_full_topology": True}
    if seed_coords is not None:
        kw["solute_coords"] = seed_coords
    sub, stem, _segs = prepare_mgh_slow_release(design, arm_dir, **kw)
    pkg = arm_dir / sub
    psf, pdb = pkg / f"{stem}.psf", pkg / f"{stem}.pdb"

    n_atoms = sum(1 for ln in pdb.read_text().splitlines() if ln.startswith(("ATOM", "HETATM")))
    box = json.loads((pkg / "manifest.json").read_text())["box_ang"]
    min_steps = minimize_steps_for_atoms(n_atoms)
    min_name = f"{stem}_probe_min"
    (pkg / f"{min_name}.conf").write_text(
        _min_conf(min_name, stem, tuple(box), (pkg / "mgh_extrabonds.txt").exists(),
                  min_steps, 0.5))
    print(f"  [{label}] {n_atoms:,} atoms, minimise {min_steps:,} steps")
    m = _run_namd(pkg / f"{min_name}.conf", pkg, namd, threads)
    if not m["ok"]:
        return {"label": label, "minimise": m, "arms": {}}

    c1 = build_c1_pairs(psf, pdb)
    wc = build_wc_pairs(psf, pdb)
    results = {}
    for name, dt, soft in INTEGRATORS:
        steps = max(100, int(round(PROBE_PS * 1000.0 / dt)))
        steps -= steps % 20
        spec = SegmentSpec(
            name=f"{stem}_probe_{name}", stage=f"probe {name}", percent=100.0,
            steps=steps, temp=300.0, damping=5.0, scale=0.5, npt=True,
            previous=min_name, dcd_freq=max(20, steps // 10),
            extra_bonds_file=f"{stem}_k0.5.enm.extra", soft=soft, timestep_fs=dt)
        (pkg / f"{spec.name}.conf").write_text(
            _segment_conf(spec, stem, tuple(box), (pkg / "mgh_extrabonds.txt").exists(),
                          fast=(dt == 4.0),
                          structure_psf=f"{stem}_hmr.psf" if dt == 4.0 else None))
        r = _run_namd(pkg / f"{spec.name}.conf", pkg, namd, threads)
        # Survival is necessary but not sufficient — check the structure too.
        health = {}
        if r["ok"]:
            try:
                h = run_health_check(pkg, spec.name, stem)
                health = {"c1_paired": h.c1_paired_fraction,
                          "wc_ref_relative": h.wc_ref_relative_fraction,
                          "broken_bp": h.broken_bp_count}
            except Exception as exc:  # noqa: BLE001
                health = {"error": str(exc)}
        verdict = "PASS" if r["ok"] and (health.get("c1_paired") or 0) >= 0.90 else "FAIL"
        print(f"    {name:10s} {verdict:4s} steps={r['last_step']:>7,} "
              f"wall={r['wall_s']:>6}s c1={health.get('c1_paired')} "
              f"{r['rattle_error'] or ''}")
        results[name] = {**r, "health": health, "verdict": verdict,
                         "timestep_fs": dt, "steps_requested": steps}
    return {"label": label, "n_atoms": n_atoms, "minimise": m,
            "n_c1_pairs": int(len(c1.pi)), "n_wc_pairs": len(wc), "arms": results}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("design", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--vacuum-ns", type=float, default=0.5)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--fresh", action="store_true", help="delete the output dir first")
    args = ap.parse_args()

    if args.fresh and args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    namd = find_namd()
    design = _load(args.design)
    print(f"NAMD: {namd}\ndesign: {args.design.name}\n")

    print("[1/3] vacuum ENRG-MD seed")
    vac_dir = args.out / "vacuum_stage"
    vac_dir.mkdir(exist_ok=True)
    coor = _vacuum_seed(design, vac_dir, namd, args.threads, args.vacuum_ns)
    if coor is None:
        print("  vacuum stage FAILED — cannot test the hypothesis")
        return 1
    psf = next(p for p in vac_dir.rglob("*_namd_vacuum/*.psf")
               if not p.stem.endswith("_hmr"))
    seed = _solute_coords(psf, coor)
    print(f"  seed: {len(seed):,} atoms\n")

    print("[2/3] IDEAL-seeded arm (the control — 2 fs is expected to fail here)")
    ideal = _probe_arm(design, args.out, seed_coords=None, label="ideal",
                       namd=namd, threads=args.threads)

    print("\n[3/3] VACUUM-seeded arm (the hypothesis)")
    vacuum = _probe_arm(design, args.out, seed_coords=seed, label="vacuum",
                        namd=namd, threads=args.threads)

    report = {"design": str(args.design), "probe_ps": PROBE_PS,
              "vacuum_ns": args.vacuum_ns, "ideal": ideal, "vacuum": vacuum}
    (args.out / "exp49_report.json").write_text(json.dumps(report, indent=2))

    print("\n=== VERDICT ===")
    for name, _dt, _soft in INTEGRATORS:
        i = ideal["arms"].get(name, {}).get("verdict", "—")
        v = vacuum["arms"].get(name, {}).get("verdict", "—")
        print(f"  {name:10s} ideal={i:4s}  vacuum={v:4s}")
    hard_ok = all(vacuum["arms"].get(n, {}).get("verdict") == "PASS"
                  for n in ("rigid_2fs", "rigid_4fs"))
    print("\n  " + ("HYPOTHESIS SUPPORTED: a vacuum-seeded package survives rigid 2 fs "
                    "AND 4 fs — the soft ladder can become a no-vacuum fallback."
                    if hard_ok else
                    "HYPOTHESIS NOT SUPPORTED: the soft start is still doing work. "
                    "Read the RATTLE line above before changing anything."))
    print(f"\n  report: {args.out / 'exp49_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
