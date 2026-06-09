"""Generate short full-origami NAMD GBIS relaxation probes for B_tube."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "experiments" / "exp22_btube_md_benchmark" / "results" / "namd_run"
OUT = ROOT / "experiments" / "exp25_full_origami_relaxation" / "results" / "runs"


COMMON = """\
structure          {psf}
coordinates        {pdb}
outputName         output/{name}

paraTypeCharmm     on
parameters         {ff}/par_all36_na.prm

gbis               on
alphaCutoff        14.0
ionConcentration   0.15

temperature        {temp}
langevin           on
langevinDamping    {damping}
langevinTemp       {temp}
langevinHydrogen   off

cutoff             16.0
switching          on
switchdist         14.0
pairlistdist       24.0
margin             8.0
exclude            scaled1-4
oneFourScaling     1.0

timestep           {timestep}
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
rigidBonds         all

outputEnergies     {energy_freq}
dcdFreq            {dcd_freq}
dcdFile            output/{name}.dcd
xstFreq            {energy_freq}
xstFile            output/{name}.xst
restartfreq        {restart_freq}
binaryrestart      yes

constraints        on
consref            restraints_initial.pdb
conskfile          restraints_initial.pdb
conskcol           B
constraintScaling  {constraint_scaling}
"""


MIN_ONLY = COMMON + """\

minimize           5000
run                0
"""


RESTART = COMMON + """\
binCoordinates     {restart_coor}
extendedSystem     {restart_xsc}
{velocity_block}

run                {steps}
"""


def _restraint_pdb(src: Path, dst: Path) -> None:
    lines: list[str] = []
    for line in src.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 66:
            # Occupancy 1.00, B-factor 1.00. Scaling is controlled in the conf.
            line = f"{line[:54]}  1.00  1.00{line[66:]}"
        lines.append(line)
    dst.write_text("\n".join(lines) + "\n")


def _write_stage(
    name: str,
    *,
    temp: float,
    damping: float,
    timestep: float,
    constraint_scaling: float,
    steps: int,
    restart_from: str | None,
    reinit_temp: float | None = None,
    minimize_only: bool = False,
) -> None:
    run_dir = OUT / name
    (run_dir / "output").mkdir(parents=True, exist_ok=True)
    _restraint_pdb(SRC / "B_tube.pdb", run_dir / "restraints_initial.pdb")

    common = {
        "name": name,
        "psf": SRC / "B_tube.psf",
        "pdb": SRC / "B_tube.pdb",
        "ff": SRC / "forcefield",
        "temp": temp,
        "damping": damping,
        "timestep": timestep,
        "constraint_scaling": constraint_scaling,
        "energy_freq": 100,
        "dcd_freq": 100,
        "restart_freq": max(100, min(5000, steps or 5000)),
    }

    if minimize_only:
        text = MIN_ONLY.format(**common)
    else:
        if restart_from is None:
            raise ValueError("restart_from required for dynamics stages")
        prev = OUT / restart_from / "output" / restart_from
        text = RESTART.format(
            **common,
            restart_coor=f"{prev}.restart.coor",
            restart_xsc=f"{prev}.restart.xsc",
            velocity_block=(
                f"reinitvels         {reinit_temp}"
                if reinit_temp is not None
                else f"binVelocities      {prev}.restart.vel"
            ),
            steps=steps,
        )
    (run_dir / f"{name}.conf").write_text(text)


def main() -> None:
    _write_stage(
        "F001_min_only_5k",
        temp=50,
        damping=10,
        timestep=0.5,
        constraint_scaling=5.0,
        steps=0,
        restart_from=None,
        minimize_only=True,
    )
    _write_stage(
        "F002_cold_10ps_k5",
        temp=50,
        damping=10,
        timestep=0.5,
        constraint_scaling=5.0,
        steps=20_000,
        restart_from="F001_min_only_5k",
        reinit_temp=50,
    )
    _write_stage(
        "F003_warm_20ps_k2",
        temp=150,
        damping=5,
        timestep=0.5,
        constraint_scaling=2.0,
        steps=40_000,
        restart_from="F002_cold_10ps_k5",
    )
    _write_stage(
        "F004_prod_20ps_k1",
        temp=310,
        damping=2,
        timestep=1.0,
        constraint_scaling=1.0,
        steps=20_000,
        restart_from="F003_warm_20ps_k2",
    )
    print(f"Wrote full-origami probe configs under {OUT}")


if __name__ == "__main__":
    main()
