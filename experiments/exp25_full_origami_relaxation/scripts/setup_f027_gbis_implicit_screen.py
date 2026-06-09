#!/usr/bin/env python3
"""Build DNA-only NAMD/GBIS benchmark package from the F027 solvated run.

This package is deliberately for fast relative screening benchmarks.  It strips
explicit solvent and ions, then runs NAMD's GBIS implicit solvent model.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import MDAnalysis as mda


ROOT = Path(__file__).resolve().parents[3]
SRC = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F027_literature_aligned_enm_production/B_tube_namd_solvated"
)
OUT = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F027_gbis_implicit_screen/B_tube_gbis_dna_only"
)
DNA_RESNAMES = {"DA", "DT", "DG", "DC"}
ION_RESNAMES = {"SOD", "CLA", "MGH"}


@dataclass(frozen=True)
class AtomRecord:
    old_id: int
    segid: str
    resid: str
    resname: str
    name: str
    atom_type: str
    charge: float
    mass: float
    imove: str


def _read_count(line: str) -> int:
    return int(line.split()[0])


def _read_int_section(lines: list[str], start: int, width: int) -> tuple[list[tuple[int, ...]], int]:
    count = _read_count(lines[start])
    need = count * width
    vals: list[int] = []
    i = start + 1
    while len(vals) < need:
        vals.extend(int(x) for x in lines[i].split())
        i += 1
    return [tuple(vals[j : j + width]) for j in range(0, need, width)], i


def _write_int_section(fh, title: str, rows: list[tuple[int, ...]], width: int) -> None:
    fh.write(f"\n{len(rows):8d} {title}\n")
    flat = [value for row in rows for value in row]
    per_line = 8 if width == 2 else 12
    for i in range(0, len(flat), per_line):
        fh.write("".join(f"{x:8d}" for x in flat[i : i + per_line]) + "\n")


def write_subset_psf(src_psf: Path, out_psf: Path, keep_resnames: set[str] = DNA_RESNAMES) -> dict[str, int]:
    lines = src_psf.read_text().splitlines()
    natom_idx = next(i for i, line in enumerate(lines) if "!NATOM" in line)
    natom = _read_count(lines[natom_idx])

    atoms: list[AtomRecord] = []
    keep_old: set[int] = set()
    for line in lines[natom_idx + 1 : natom_idx + 1 + natom]:
        parts = line.split()
        rec = AtomRecord(
            old_id=int(parts[0]),
            segid=parts[1],
            resid=parts[2],
            resname=parts[3],
            name=parts[4],
            atom_type=parts[5],
            charge=float(parts[6]),
            mass=float(parts[7]),
            imove=parts[8] if len(parts) > 8 else "0",
        )
        if rec.resname in keep_resnames:
            keep_old.add(rec.old_id)
            atoms.append(rec)

    old_to_new = {rec.old_id: i + 1 for i, rec in enumerate(atoms)}

    sections = {
        "!NBOND": ("!NBOND: bonds", 2),
        "!NTHETA": ("!NTHETA: angles", 3),
        "!NPHI": ("!NPHI: dihedrals", 4),
        "!NIMPHI": ("!NIMPHI: impropers", 4),
    }
    filtered: dict[str, list[tuple[int, ...]]] = {}
    for marker, (_title, width) in sections.items():
        idx = next(i for i, line in enumerate(lines) if marker in line)
        rows, _next = _read_int_section(lines, idx, width)
        filtered[marker] = [
            tuple(old_to_new[x] for x in row)
            for row in rows
            if all(x in keep_old for x in row)
        ]

    with out_psf.open("w") as fh:
        fh.write("PSF EXT\n\n")
        fh.write("       3 !NTITLE\n")
        fh.write(" REMARKS F027 GBIS DNA-only implicit-solvent benchmark topology\n")
        fh.write(" REMARKS Derived from F027 solvated B_tube.psf\n")
        fh.write(" REMARKS Explicit water and ions stripped for relative screening only\n\n")
        fh.write(f"{len(atoms):8d} !NATOM\n")
        for new_id, rec in enumerate(atoms, 1):
            fh.write(
                f"{new_id:10d} {rec.segid:<8s} {rec.resid:<8s} {rec.resname:<8s} "
                f"{rec.name:<8s} {rec.atom_type:<8s} {rec.charge:14.6f} "
                f"{rec.mass:13.6f} {int(rec.imove):8d}\n"
            )
        for marker in ("!NBOND", "!NTHETA", "!NPHI", "!NIMPHI"):
            title, width = sections[marker]
            _write_int_section(fh, title, filtered[marker], width)
        fh.write("\n       0 !NDON: donors\n")
        fh.write("\n       0 !NACC: acceptors\n")
        fh.write("\n       0 !NNB\n")
        fh.write("\n       0       0 !NGRP NST2\n")
        fh.write("\n       0       0 !NUMLP NUMLPH\n")

    return {
        "atoms": len(atoms),
        "bonds": len(filtered["!NBOND"]),
        "angles": len(filtered["!NTHETA"]),
        "dihedrals": len(filtered["!NPHI"]),
        "impropers": len(filtered["!NIMPHI"]),
    }


def write_subset_pdb(src_psf: Path, src_coor: Path, out_pdb: Path, selection: str = "resname DA DT DG DC") -> int:
    u = mda.Universe(src_psf, src_coor, format="NAMDBIN")
    dna = u.select_atoms(selection)
    dna.write(str(out_pdb))
    return dna.n_atoms


def render_conf(
    name: str,
    *,
    sasa: bool = False,
    ion_concentration: float = 0.3,
    structure: str = "B_tube_gbis.psf",
    coordinates: str = "B_tube_gbis.pdb",
    include_ion_params: bool = False,
) -> str:
    sasa_block = "SASA               on\nsurfaceTension     0.006\n" if sasa else "SASA               off\n"
    ion_param_block = (
        "parameters         forcefield/toppar_water_ions_cufix.str\n"
        "parameters         forcefield/par_stub_ions_nbfix.str\n"
        if include_ion_params
        else ""
    )
    return f"""# F027 implicit-solvent fast-screen benchmark, not production MD.
structure          {structure}
coordinates        {coordinates}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
{ion_param_block}

GBIS               on
solventDielectric  78.5
ionConcentration   {ion_concentration}
alphaCutoff        14
{sasa_block}
switching          on
switchdist         15
cutoff             16
pairlistdist       18
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         all
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off
langevinTemp       300
langevinDamping    1

timestep           2.0
nonbondedFreq      2
fullElectFrequency 4
stepspercycle      20

temperature        300
outputEnergies     500
restartfreq        5000
binaryrestart      yes
outputName         output/{name}
dcdFile            output/{name}.dcd
dcdFreq            1000
run                5000
"""


def render_minwarm_conf(name: str, *, ion_concentration: float = 0.3) -> str:
    return f"""# F027 implicit-solvent fast-screen benchmark, not production MD.
# Minimize after stripping explicit solvent before assigning velocities.
structure          B_tube_gbis.psf
coordinates        B_tube_gbis.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm

GBIS               on
solventDielectric  78.5
ionConcentration   {ion_concentration}
alphaCutoff        14
SASA               off

switching          on
switchdist         15
cutoff             16
pairlistdist       18
exclude            scaled1-4
oneFourScaling     1.0

langevin           on
langevinHydrogen   off
langevinTemp       300
langevinDamping    5
temperature        300

timestep           1.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      20

outputEnergies     250
restartfreq        2500
binaryrestart      yes
outputName         output/{name}
dcdFile            output/{name}.dcd
dcdFreq            1000
minimize           5000
reinitvels         300
run                5000
"""


def render_posrest_conf(name: str, *, scale: float = 1.0, ion_concentration: float = 0.3) -> str:
    return f"""# F027 implicit-solvent restrained benchmark, not production MD.
# Strong positional restraints test whether GBIS can serve as a fast local screen.
structure          B_tube_gbis.psf
coordinates        B_tube_gbis.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm

GBIS               on
solventDielectric  78.5
ionConcentration   {ion_concentration}
alphaCutoff        14
SASA               off

switching          on
switchdist         15
cutoff             16
pairlistdist       18
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         all
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off
langevinTemp       300
langevinDamping    5
temperature        300

timestep           2.0
nonbondedFreq      2
fullElectFrequency 4
stepspercycle      20

constraints        on
consref            constraints_all_dna.pdb
conskfile          constraints_all_dna.pdb
conskcol           B
constraintScaling  {scale}

outputEnergies     500
restartfreq        5000
binaryrestart      yes
outputName         output/{name}
dcdFile            output/{name}.dcd
dcdFreq            1000
run                5000
"""


def render_runner() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../../.." && pwd)"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMD="${NAMD_BIN:-/home/jojo/Applications/NAMD_3.0.2/namd3}"
THREADS="${NAMD_THREADS:-12}"
PEMAP="${NAMD_PEMAP:-0-15}"
HEALTH="$ROOT/experiments/exp25_full_origami_relaxation/scripts/f027_health_check.py"
stages=("$@")
if [[ "${#stages[@]}" -eq 0 ]]; then
  stages=(F027_gbis_03_pos1_dna_only_10ps F027_gbis_00_minwarm_dna_only_5ps F027_gbis_01_dna_only_10ps F027_gbis_02_dna_only_sasa_10ps)
fi

cd "$PKG_DIR"
mkdir -p output
namd_args=("+p${THREADS}" "+setcpuaffinity")
if [[ -n "$PEMAP" ]]; then
  namd_args+=("+pemap" "$PEMAP")
fi
for stage in "${stages[@]}"; do
  if [[ -f "output/${stage}.coor" ]]; then
    echo "[F027-gbis] Skip completed $stage"
  else
    echo "[F027-gbis] Running $stage with ${namd_args[*]}"
    "$NAMD" "${namd_args[@]}" "${stage}.conf" > "${stage}.log" 2>&1
  fi
  echo "[F027-gbis] Health check $stage"
  python "$HEALTH" \
    --package-dir "$PKG_DIR" \
    --segment "$stage" \
    --stage "$stage" \
    --name-stem B_tube_gbis \
    --min-c1 0.70 \
    --min-wc 0.85 \
    --paired-max-ang 16.0 \
    --wc-policy warn \
    --jsonl output/F027_gbis_health.jsonl \
    --summary output/F027_gbis_latest_health.json
done
echo "[F027-gbis] Benchmark batch complete"
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "forcefield").mkdir(exist_ok=True)
    shutil.copy2(SRC / "forcefield/par_all36_na.prm", OUT / "forcefield/par_all36_na.prm")
    counts = write_subset_psf(SRC / "B_tube.psf", OUT / "B_tube_gbis.psf")
    n_pdb = write_subset_pdb(
        SRC / "B_tube.psf",
        SRC / "output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.coor",
        OUT / "B_tube_gbis.pdb",
    )
    pdb_lines = []
    for line in (OUT / "B_tube_gbis.pdb").read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            line = f"{line[:60]}{1.0:6.2f}{line[66:]}"
        pdb_lines.append(line)
    (OUT / "constraints_all_dna.pdb").write_text("\n".join(pdb_lines) + "\n")
    (OUT / "F027_gbis_01_dna_only_10ps.conf").write_text(
        render_conf("F027_gbis_01_dna_only_10ps", sasa=False)
    )
    (OUT / "F027_gbis_00_minwarm_dna_only_5ps.conf").write_text(
        render_minwarm_conf("F027_gbis_00_minwarm_dna_only_5ps")
    )
    (OUT / "F027_gbis_02_dna_only_sasa_10ps.conf").write_text(
        render_conf("F027_gbis_02_dna_only_sasa_10ps", sasa=True)
    )
    (OUT / "F027_gbis_03_pos1_dna_only_10ps.conf").write_text(
        render_posrest_conf("F027_gbis_03_pos1_dna_only_10ps", scale=1.0)
    )
    runner = OUT / "run_f027_gbis_benchmarks.sh"
    runner.write_text(render_runner())
    runner.chmod(0o755)
    print(f"Wrote {OUT}")
    print({**counts, "pdb_atoms": n_pdb})

    out_ions = OUT.parent / "B_tube_gbis_dna_ions"
    out_ions.mkdir(parents=True, exist_ok=True)
    (out_ions / "forcefield").mkdir(exist_ok=True)
    for prm in ("par_all36_na.prm", "toppar_water_ions_cufix.str", "par_stub_ions_nbfix.str"):
        shutil.copy2(SRC / f"forcefield/{prm}", out_ions / f"forcefield/{prm}")
    counts_ions = write_subset_psf(
        SRC / "B_tube.psf",
        out_ions / "B_tube_gbis_ions.psf",
        DNA_RESNAMES | ION_RESNAMES,
    )
    n_pdb_ions = write_subset_pdb(
        SRC / "B_tube.psf",
        SRC / "output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.coor",
        out_ions / "B_tube_gbis_ions.pdb",
        "resname DA DT DG DC SOD CLA MGH",
    )
    (out_ions / "F027_gbis_ions_01_10ps.conf").write_text(
        render_conf(
            "F027_gbis_ions_01_10ps",
            structure="B_tube_gbis_ions.psf",
            coordinates="B_tube_gbis_ions.pdb",
            include_ion_params=True,
        )
    )
    runner_ions = out_ions / "run_f027_gbis_ions_benchmark.sh"
    runner_ions.write_text(
        render_runner()
        .replace("B_tube_gbis", "B_tube_gbis_ions")
        .replace("F027_gbis_00_minwarm_dna_only_5ps F027_gbis_01_dna_only_10ps F027_gbis_02_dna_only_sasa_10ps", "F027_gbis_ions_01_10ps")
        .replace("F027_gbis_03_pos1_dna_only_10ps ", "")
    )
    runner_ions.chmod(0o755)
    print(f"Wrote {out_ions}")
    print({**counts_ions, "pdb_atoms": n_pdb_ions})


if __name__ == "__main__":
    main()
