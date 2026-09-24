"""Native startup and ordinary-DNA invariance for an isolated typed CPD candidate."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.refine_cis_syn import PARENT
from experiments.cpd_published_comparator.reconstruct import BASE, FF, write, source


def main(root, typed):
    assert not (root / "reference_build_assessment.json").exists()
    (root / "verify_typed_startup.executed.py").write_text(Path(__file__).read_text())
    records = []
    for kind in ["dimer", "duplex", "undamaged_control"]:
        out = root / kind
        out.mkdir(exist_ok=False)
        shutil.copy2(typed / kind / "fragment.psf", out / "system.psf")
        for name in ["system.pdb", "fixed_heavy.pdb"]:
            shutil.copy2(PARENT / kind / name, out / name)
        psf = app.CharmmPsfFile(str(out / "system.psf"))
        prefix = out / "startup"
        config = f"""structure {out}/system.psf
coordinates {out}/system.pdb
paraTypeCharmm on
parameters {BASE}/par_all36_na.prm
parameters {FF}/par_all36_cgenff.prm
parameters {root}/comparator_last.prm
exclude scaled1-4
oneFourScaling 1
cutoff 100
switching off
pairlistdist 102
margin 2
outputName {prefix}
temperature 0
rigidBonds none
timestep 1
stepspercycle 1
outputEnergies 1
fixedAtoms on
fixedAtomsForces on
fixedAtomsFile {out}/fixed_heavy.pdb
fixedAtomsCol B
run 0
minimize 500
"""
        prefix.with_suffix(".conf").write_text(config)
        p = subprocess.run(
            ["namd3", "+p1", str(prefix.with_suffix(".conf"))],
            capture_output=True,
            text=True,
        )
        log = p.stdout + p.stderr
        prefix.with_suffix(".log").write_text(log)
        rows = [l.split() for l in log.splitlines() if l.startswith("ENERGY:")]
        assert (
            p.returncode == 0
            and rows
            and "FATAL ERROR" not in log
            and int(rows[-1][1]) == 500
        )
        records.append(
            dict(
                fixture=kind,
                particles=len(psf.atom_list),
                native_load="passed",
                hydrogen_relaxation_steps=500,
                net_charge_e=sum(a.charge for a in psf.atom_list),
                final_energy=float(rows[-1][11]),
            )
        )
    control = root / "undamaged_control"
    psf = app.CharmmPsfFile(str(control / "system.psf"))
    pdb = app.PDBFile(str(control / "system.pdb"))
    evaluations = []
    for overlay in (False, True):
        files = [
            str(BASE / "top_all36_na.rtf"),
            str(BASE / "par_all36_na.prm"),
            str(FF / "top_all36_cgenff.rtf"),
            str(FF / "par_all36_cgenff.prm"),
        ]
        if overlay:
            files.append(str(root / "comparator_last.prm"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            params = app.CharmmParameterSet(*files)
        s = psf.createSystem(
            params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
        )
        it = mm.VerletIntegrator(0.001)
        ctx = mm.Context(s, it, mm.Platform.getPlatformByName("Reference"))
        ctx.setPositions(pdb.positions)
        state = ctx.getState(getEnergy=True, getForces=True)
        evaluations.append(
            (
                state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                np.asarray(
                    state.getForces(asNumpy=True).value_in_unit(
                        u.kilocalorie_per_mole / u.angstrom
                    )
                ),
            )
        )
        del ctx, it
    de = abs(evaluations[0][0] - evaluations[1][0])
    df = float(np.max(abs(evaluations[0][1] - evaluations[1][1])))
    write(
        root / "reference_build_assessment.json",
        dict(
            simulation_ready=False,
            fixtures=records,
            control_invariance=dict(
                energy_error=de, force_error=df, passed=de < 1e-7 and df < 1e-7
            ),
            scope="Native startup only, not solution validation",
            sources=[
                source(root / "comparator_last.prm"),
                source(typed / "assessment.json"),
                source(Path(__file__)),
            ],
        ),
    )
    print(
        json.dumps(
            dict(fixtures=records, control_energy_error=de, control_force_error=df),
            indent=2,
        )
    )
    assert de < 1e-7 and df < 1e-7, "CPD terms must not alter ordinary DNA"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--typed-input", required=True, type=Path)
    a = p.parse_args()
    main(a.root.resolve(), a.typed_input.resolve())
