#!/usr/bin/env python3
"""Prepare NAMD GBIS implicit-solvent screening runs for the 1hb duplex.

The package uses the bridge-minimized dry duplex from exp23 as a small,
traceable system for developing an implicit-solvent recipe before retrying
full B-tube.  Generated configs are intentionally staged from conservative
to more aggressive integration settings.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT / "experiments/exp23_periodic_cell_benchmark/results/single_helix_bridge_min"
RUN_DIR = ROOT / "experiments/exp25_full_origami_relaxation/results/runs/F028_implicit_screen/1hb_gbis_bridge_min"
FORCEFIELD = ROOT / "backend/data/forcefield/par_all36_na.prm"


COMMON_CONF = """\
structure          {run_dir}/duplex_dry.psf
coordinates        {run_dir}/duplex_dry.pdb
outputName         {run_dir}/output/{name}

set temperature    {temperature}
{initial_temperature_line}

paraTypeCharmm     on
parameters         {forcefield}

GBIS               on
solventDielectric  78.5
ionConcentration   {ion_concentration}
alphaCutoff        14
SASA               off

exclude            scaled1-4
oneFourScaling     1.0
cutoff             16.0
switching          on
switchdist         15.0
pairlistdist       20.0
margin             8.0

timestep           {timestep}
nonbondedFreq      {nonbonded_freq}
fullElectFrequency {full_elect_freq}
stepspercycle      10

langevin           {langevin}
langevinDamping    {damping}
langevinTemp       $temperature
langevinHydrogen   off

rigidBonds         none
wrapAll            off

dcdFile            {run_dir}/output/{name}.dcd
dcdFreq            {dcd_freq}
outputEnergies     {energy_freq}
restartFreq        {restart_freq}
binaryOutput       yes
binaryRestart      yes

{restart_block}
{constraints_block}
{commands}
"""


RUNS = [
    {
        "name": "G001_min_20k",
        "temperature": 1,
        "timestep": 0.5,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "off",
        "damping": 10.0,
        "dcd_freq": 1000,
        "energy_freq": 1000,
        "restart_freq": 1000,
        "restart_from": None,
        "constraints": 10.0,
        "commands": "minimize           20000",
    },
    {
        "name": "G002_warm50_0p25fs_2ps",
        "temperature": 50,
        "timestep": 0.25,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 10.0,
        "dcd_freq": 1000,
        "energy_freq": 1000,
        "restart_freq": 8000,
        "restart_from": "G001_min_20k",
        "constraints": 5.0,
        "commands": "reinitvels         $temperature\nrun                8000        ;# 2 ps",
    },
    {
        "name": "G003_ramp150_0p5fs_5ps",
        "temperature": 150,
        "timestep": 0.5,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 8.0,
        "dcd_freq": 1000,
        "energy_freq": 1000,
        "restart_freq": 10000,
        "restart_from": "G002_warm50_0p25fs_2ps",
        "constraints": 3.0,
        "commands": "run                10000       ;# 5 ps",
    },
    {
        "name": "G004_ramp300_0p25fs_10ps",
        "temperature": 300,
        "timestep": 0.25,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 20.0,
        "dcd_freq": 2000,
        "energy_freq": 2000,
        "restart_freq": 40000,
        "restart_from": "G003_ramp150_0p5fs_5ps",
        "use_velocities": False,
        "constraints": 3.0,
        "commands": "reinitvels         $temperature\nrun                40000       ;# 10 ps",
    },
    {
        "name": "G005_300K_0p5fs_pos2_50ps",
        "temperature": 300,
        "timestep": 0.5,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 10.0,
        "dcd_freq": 2000,
        "energy_freq": 2000,
        "restart_freq": 25000,
        "restart_from": "G004_ramp300_0p25fs_10ps",
        "constraints": 2.0,
        "commands": "run                100000      ;# 50 ps",
    },
    {
        "name": "G006_300K_1fs_pos1_50ps",
        "temperature": 300,
        "timestep": 1.0,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 5.0,
        "dcd_freq": 1000,
        "energy_freq": 1000,
        "restart_freq": 25000,
        "restart_from": "G005_300K_0p5fs_pos2_50ps",
        "constraints": 1.0,
        "commands": "run                50000       ;# 50 ps",
    },
    {
        "name": "G007_300K_0p5fs_release_50ps",
        "temperature": 300,
        "timestep": 0.5,
        "nonbonded_freq": 1,
        "full_elect_freq": 1,
        "langevin": "on",
        "damping": 10.0,
        "dcd_freq": 1000,
        "energy_freq": 1000,
        "restart_freq": 25000,
        "restart_from": "G005_300K_0p5fs_pos2_50ps",
        "use_velocities": False,
        "constraints": None,
        "commands": "reinitvels         $temperature\nrun                40000       ;# 20 ps",
    },
]


HEALTH_SCRIPT = r'''#!/usr/bin/env python3
"""Health check and plotting for 1hb NAMD GBIS duplex runs."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree
import MDAnalysis as mda


SEARCH_LO = 8.5
SEARCH_HI = 13.0
PAIRED_MAX = 12.0
STRAINED_MAX = 15.0


def c1prime(universe: mda.Universe):
    sel = universe.select_atoms("name C1'")
    if not len(sel):
        sel = universe.select_atoms("name C1X")
    if not len(sel):
        raise RuntimeError("No C1' atoms found in topology/coordinates.")
    return sel


def build_pairs(psf: Path, pdb: Path):
    u = mda.Universe(str(psf), str(pdb))
    atoms = c1prime(u)
    pos = atoms.positions
    segids = atoms.segids
    tree = cKDTree(pos)
    used = np.zeros(len(pos), dtype=bool)
    pairs = []
    for i in range(len(pos)):
        if used[i]:
            continue
        candidates = []
        for j in tree.query_ball_point(pos[i], SEARCH_HI):
            if j <= i or used[j] or segids[j] == segids[i]:
                continue
            d = float(np.linalg.norm(pos[i] - pos[j]))
            if d >= SEARCH_LO:
                candidates.append((d, j))
        if candidates:
            candidates.sort()
            j = candidates[0][1]
            used[i] = True
            used[j] = True
            pairs.append((i, j))
    if not pairs:
        raise RuntimeError("Could not identify antiparallel C1' pairs.")
    return np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])


def parse_log(log_path: Path):
    rows = []
    perf = None
    failed = False
    errors = []
    if not log_path.exists():
        return rows, perf, failed, errors
    energy_re = re.compile(r"^ENERGY:\s+(.+)")
    header = None
    with log_path.open(errors="replace") as fh:
        for line in fh:
            if "ERROR:" in line or "FATAL ERROR" in line:
                failed = True
                errors.append(line.strip())
            if "Info: Benchmark time:" in line and "days/ns" in line:
                m = re.search(r"([0-9.]+)\s+days/ns,\s+([0-9.]+)\s+MB", line)
                if m:
                    days_per_ns = float(m.group(1))
                    if days_per_ns > 0:
                        perf = 1.0 / days_per_ns
            if line.startswith("PERFORMANCE:"):
                m = re.search(r"averaging\s+([0-9.]+)\s+ns/day", line)
                if m:
                    perf = float(m.group(1))
            if line.startswith("ETITLE:"):
                header = line.split()[1:]
                continue
            match = energy_re.match(line)
            if match and header:
                values = match.group(1).split()
                if len(values) >= len(header):
                    rec = {}
                    for key, value in zip(header, values):
                        try:
                            rec[key] = float(value)
                        except ValueError:
                            pass
                    rows.append(rec)
    return rows, perf, failed, errors[-5:]


def analyse_dcd(psf: Path, dcd: Path, pair_i: np.ndarray, pair_j: np.ndarray):
    if not dcd.exists() or dcd.stat().st_size == 0:
        return None
    u = mda.Universe(str(psf), str(dcd))
    atoms = c1prime(u)
    n_frames = len(u.trajectory)
    if n_frames == 0:
        return None
    times, paired, mean_d, max_d = [], [], [], []
    dt_ps = float(u.trajectory.dt or 0.0)
    for ts in u.trajectory:
        d = np.linalg.norm(atoms.positions[pair_i] - atoms.positions[pair_j], axis=1)
        times.append(float(ts.time if dt_ps > 0 else ts.frame) * 1e-3 if dt_ps > 0 else float(ts.frame))
        paired.append(float(np.mean(d < PAIRED_MAX)))
        mean_d.append(float(np.mean(d)))
        max_d.append(float(np.max(d)))
    return {
        "frames": n_frames,
        "time_axis": "ns" if dt_ps > 0 else "frame",
        "time": times,
        "paired_fraction": paired,
        "mean_c1p_distance_A": mean_d,
        "max_c1p_distance_A": max_d,
        "final_paired_pct": paired[-1] * 100.0,
        "final_mean_c1p_A": mean_d[-1],
        "final_max_c1p_A": max_d[-1],
    }


def verdict(energies, traj, failed):
    if failed:
        return "FAIL"
    if energies:
        last = energies[-1]
        temp = last.get("TEMP")
        total = last.get("TOTAL")
        if total is not None and (not math.isfinite(total) or abs(total) > 1.0e20):
            return "FAIL"
        if temp is not None and (not math.isfinite(temp) or temp > 450):
            return "FAIL"
    if traj:
        if traj["final_max_c1p_A"] >= STRAINED_MAX:
            return "FAIL"
        if traj["final_paired_pct"] < 90.0:
            return "WARN"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    psf = run_dir / "duplex_dry.psf"
    pdb = run_dir / "duplex_dry.pdb"
    output = run_dir / "output"
    pair_i, pair_j = build_pairs(psf, pdb)

    summary = {
        "run_dir": str(run_dir),
        "n_pairs": int(len(pair_i)),
        "runs": [],
    }

    for log in sorted(output.glob("G*.log")):
        name = log.stem
        energies, ns_day, failed, errors = parse_log(log)
        traj = analyse_dcd(psf, output / f"{name}.dcd", pair_i, pair_j)
        rec = {
            "name": name,
            "log": str(log),
            "energy_lines": len(energies),
            "ns_per_day": ns_day,
            "failed": failed,
            "errors": errors,
            "verdict": verdict(energies, traj, failed),
            "last_energy": energies[-1] if energies else None,
            "trajectory": traj,
        }
        summary["runs"].append(rec)

    out_json = args.out or (run_dir / "health_summary.json")
    out_json.write_text(json.dumps(summary, indent=2))

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)
    for rec in summary["runs"]:
        traj = rec["trajectory"]
        if not traj:
            continue
        label = rec["name"].replace("G00", "G")
        x = np.array(traj["time"])
        axes[0].plot(x, np.array(traj["paired_fraction"]) * 100.0, label=label)
        axes[1].plot(x, traj["mean_c1p_distance_A"], label=label)
        axes[2].plot(x, traj["max_c1p_distance_A"], label=label)
    axes[0].axhline(90, color="tab:orange", linestyle="--", linewidth=1)
    axes[0].set_ylabel("C1' paired (%)")
    axes[1].axhline(PAIRED_MAX, color="tab:green", linestyle="--", linewidth=1)
    axes[1].set_ylabel("Mean C1'-C1' (A)")
    axes[2].axhline(STRAINED_MAX, color="tab:red", linestyle="--", linewidth=1)
    axes[2].set_ylabel("Max C1'-C1' (A)")
    axes[2].set_xlabel("Trajectory time (ns, per run)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="best")
    fig.suptitle(f"1hb GBIS duplex health ({len(pair_i)} C1' pairs)")
    fig.tight_layout()
    fig.savefig(run_dir / "health_summary.png", dpi=160)

    print(json.dumps({
        "summary": str(out_json),
        "plot": str(run_dir / "health_summary.png"),
        "runs": [
            {
                "name": r["name"],
                "verdict": r["verdict"],
                "ns_per_day": r["ns_per_day"],
                "final_paired_pct": (r["trajectory"] or {}).get("final_paired_pct"),
                "final_max_c1p_A": (r["trajectory"] or {}).get("final_max_c1p_A"),
            }
            for r in summary["runs"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


RUNNER = """#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMD="${NAMD:-/home/jojo/Applications/NAMD_3.0.2/namd3}"
P="${P:-12}"
PEMAP="${NAMD_PEMAP:-0-15}"

mkdir -p "$RUN_DIR/output"
namd_args=(+p"$P" +setcpuaffinity)
if [[ -n "$PEMAP" ]]; then
  namd_args+=(+pemap "$PEMAP")
fi

for conf in "$RUN_DIR"/G*.conf; do
  name="$(basename "$conf" .conf)"
  log="$RUN_DIR/output/${name}.log"
  echo "==> $name"
  "$NAMD" "${namd_args[@]}" "$conf" > "$log" 2>&1
  python "$RUN_DIR/health_1hb_gbis.py" --run-dir "$RUN_DIR"
done
"""


def restart_block(run_dir: Path, restart_from: str | None, use_velocities: bool) -> str:
    if not restart_from:
        return ""
    out = run_dir / "output" / restart_from
    lines = [f"binCoordinates     {out}.restart.coor"]
    vel = out.with_suffix(".restart.vel")
    if use_velocities and not restart_from.startswith("G001_min"):
        lines.append(f"binVelocities      {out}.restart.vel")
    return "\n".join(lines)


def initial_temperature_line(restart_from: str | None, use_velocities: bool) -> str:
    if use_velocities and restart_from and not restart_from.startswith("G001_min"):
        return ""
    return "temperature        $temperature"


def constraints_block(run_dir: Path, constraints: float | None) -> str:
    if constraints is None:
        return ""
    return "\n".join([
        "constraints        on",
        f"consref            {run_dir}/duplex_dry.pdb",
        f"conskfile          {run_dir}/constraints_all.pdb",
        "conskcol           B",
        f"constraintScaling  {constraints}",
    ])


def make_constraints(src_pdb: Path, dst_pdb: Path) -> None:
    lines = []
    for line in src_pdb.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            line = f"{line[:60]}{1.00:6.2f}{1.00:6.2f}{line[72:] if len(line) > 72 else ''}"
        lines.append(line)
    dst_pdb.write_text("\n".join(lines) + "\n")


def write_configs(run_dir: Path, ion_concentration: float) -> None:
    for spec in RUNS:
        spec = {**spec}
        use_velocities = spec.pop("use_velocities", True)
        name = spec["name"]
        text = COMMON_CONF.format(
            run_dir=run_dir,
            name=name,
            forcefield=FORCEFIELD,
            ion_concentration=ion_concentration,
            initial_temperature_line=initial_temperature_line(spec["restart_from"], use_velocities),
            restart_block=restart_block(run_dir, spec["restart_from"], use_velocities),
            constraints_block=constraints_block(run_dir, spec["constraints"]),
            **{k: v for k, v in spec.items() if k not in {"name", "restart_from", "constraints"}},
        )
        (run_dir / f"{name}.conf").write_text(text)


def write_notes(run_dir: Path, ion_concentration: float) -> None:
    (run_dir / "README.md").write_text(f"""\
# 1hb GBIS Implicit-Solvent Screen

This package tests whether an all-atom, dry, bridge-minimized 1hb duplex can
remain stable in NAMD GBIS before retrying B-tube.  It uses:

- Source structure: `{SRC_DIR.relative_to(ROOT)}/duplex_dry.psf,pdb`
- Force field: CHARMM36 nucleic acid parameters from `backend/data/forcefield/par_all36_na.prm`
- GBIS: solvent dielectric 78.5, ion concentration {ion_concentration} M,
  alpha cutoff 14 A, no PME, 16/15/20 A cutoff/switch/pairlist.
- Health criterion: C1'-C1' base-pair distances, PASS if no detected pair
  reaches 15 A and final paired fraction remains at least 90%.

Run with:

```bash
cd {run_dir}
P=4 ./run_sequence.sh
```

Recompute health summary:

```bash
python health_1hb_gbis.py --run-dir {run_dir}
```
""")


def setup(run_dir: Path, ion_concentration: float, overwrite: bool) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(exist_ok=True)
    for name in ["duplex_dry.psf", "duplex_dry.pdb"]:
        dst = run_dir / name
        if dst.exists() and not overwrite:
            continue
        shutil.copy2(SRC_DIR / name, dst)
    make_constraints(run_dir / "duplex_dry.pdb", run_dir / "constraints_all.pdb")
    write_configs(run_dir, ion_concentration)
    (run_dir / "run_sequence.sh").write_text(RUNNER)
    (run_dir / "run_sequence.sh").chmod(0o755)
    (run_dir / "health_1hb_gbis.py").write_text(HEALTH_SCRIPT)
    (run_dir / "health_1hb_gbis.py").chmod(0o755)
    write_notes(run_dir, ion_concentration)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--ion-concentration", type=float, default=0.30)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    setup(args.run_dir.resolve(), args.ion_concentration, args.overwrite)
    print(args.run_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
