#!/usr/bin/env python3
"""Set up an origami-MD protocol closer to published equilibration practice."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments" / "exp25_full_origami_relaxation"
SRC = ROOT / "experiments" / "exp22_btube_md_benchmark" / "results" / "namd_run"
RUNS = EXP / "results" / "runs"
REF_PDB = EXP / "results" / "B_tube_full_F001_minimized_reference.pdb"


COMMON = """\
structure          {psf}
coordinates        {pdb}
outputName         output/{name}

paraTypeCharmm     on
parameters         {ff}/par_all36_na.prm

gbis               on
alphaCutoff        14.0
ionConcentration   0.15

temperature        310
langevin           on
langevinDamping    1
langevinTemp       310
langevinHydrogen   off

cutoff             16.0
switching          on
switchdist         14.0
pairlistdist       28.0
margin             10.0
exclude            scaled1-4
oneFourScaling     1.0

timestep           0.25
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
rigidBonds         all

outputEnergies     200
dcdFreq            1000
dcdFile            output/{name}.dcd
xstFreq            1000
xstFile            output/{name}.xst
restartfreq        10000
binaryrestart      yes
"""


def _restraint_pdb(src: Path, dst: Path, k: float = 1.0) -> None:
    lines: list[str] = []
    for line in src.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 66:
            line = f"{line[:54]}  1.00{k:6.2f}{line[66:]}"
        lines.append(line)
    dst.write_text("\n".join(lines) + "\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main() -> None:
    f010 = RUNS / "F010_established_practice_gbis_enm"
    (f010 / "output").mkdir(parents=True, exist_ok=True)
    _restraint_pdb(REF_PDB, f010 / "restraints_minimized.pdb")

    common = COMMON.format(
        psf=SRC / "B_tube.psf",
        pdb=REF_PDB,
        ff=SRC / "forcefield",
        name="{name}",
    )

    # Stage 00: literature-like positional restraint startup, but still short
    # enough to serve as a local smoke. Production-scale use should extend this
    # from ps to ns before moving on.
    name = "F010_00_positional_310K"
    _write(f010 / f"{name}.conf", common.format(name=name) + f"""\

constraints        on
consref            restraints_minimized.pdb
conskfile          restraints_minimized.pdb
conskcol           B
constraintScaling  1.0

binCoordinates     {RUNS / 'F001_min_only_5k' / 'output' / 'F001_min_only_5k.restart.coor'}
extendedSystem     {RUNS / 'F001_min_only_5k' / 'output' / 'F001_min_only_5k.restart.xsc'}
reinitvels         310

minimize           20000
run                40000
""")

    # Stage 01: switch to ENM local-order restraints while keeping a weak
    # positional scaffold. This mirrors published practice better than dropping
    # from full positional restraints directly to nothing.
    name = "F010_01_enm_weakpos_310K"
    _write(f010 / f"{name}.conf", common.format(name=name) + """\

constraints        on
consref            restraints_minimized.pdb
conskfile          restraints_minimized.pdb
conskcol           B
constraintScaling  0.10

extraBonds         on
extraBondsFile     local_order_enm.extrabonds

binCoordinates     output/F010_00_positional_310K.restart.coor
extendedSystem     output/F010_00_positional_310K.restart.xsc
binVelocities      output/F010_00_positional_310K.restart.vel

run                100000
""")

    # Stage 02: ENM-only local-order equilibration. This is the closest GBIS
    # analogue to the published elastic-network release stage.
    name = "F010_02_enm_only_310K"
    _write(f010 / f"{name}.conf", common.format(name=name) + """\

extraBonds         on
extraBondsFile     local_order_enm.extrabonds

binCoordinates     output/F010_01_enm_weakpos_310K.restart.coor
extendedSystem     output/F010_01_enm_weakpos_310K.restart.xsc
binVelocities      output/F010_01_enm_weakpos_310K.restart.vel

run                250000
""")

    _write(f010 / "README.md", """\
# F010 Established-Practice GBIS+ENM Protocol

This protocol addresses the main literature-practice gaps without yet paying
the full explicit-solvent cost:

- starts from the F001 minimized atomistic reference,
- uses 310 K Langevin with damping 1 ps^-1,
- performs longer restrained minimization before dynamics,
- transitions from Cartesian positional restraints to local-order ENM
  restraints,
- uses the Watson-Crick monitor for pass/fail analysis.

Generate `local_order_enm.extrabonds` with:

```bash
python experiments/exp25_full_origami_relaxation/scripts/generate_enm_restraints.py \\
  --psf experiments/exp22_btube_md_benchmark/results/namd_run/B_tube.psf \\
  --pdb experiments/exp25_full_origami_relaxation/results/B_tube_full_F001_minimized_reference.pdb \\
  --out experiments/exp25_full_origami_relaxation/results/runs/F010_established_practice_gbis_enm/local_order_enm.extrabonds \\
  --report experiments/exp25_full_origami_relaxation/metrics/F010_enm_report.json
```

Run stages in order from this directory. For production-scale validation,
increase Stage 00/01 from ps-scale smoke lengths to ns-scale windows.
""")

    print(f"Wrote {f010}")


if __name__ == "__main__":
    main()
