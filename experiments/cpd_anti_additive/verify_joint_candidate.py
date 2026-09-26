"""Independent MM stationarity, two-step curvature and CHARMM export checks."""

import argparse
import json
from pathlib import Path
import sys
import warnings
import numpy as np
import openmm as mm
from openmm import app, unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import source, write

art = Path(".development-artifacts").resolve()
parser = argparse.ArgumentParser()
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
candidate = args.candidate.resolve()
root = args.root.resolve()
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    params = app.CharmmParameterSet(str(candidate / "comparator_last.prm"))
records = []
for label in ["core", "endpoint-1", "endpoint-2"]:
    folder = candidate / label
    x = np.loadtxt(folder / "minimum_A.txt")
    s = mm.XmlSerializer.deserialize((folder / "system.xml").read_text())
    psf = app.CharmmPsfFile(str(folder / "fragment.psf"))
    exported = psf.createSystem(
        params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
    )
    integrators = [mm.VerletIntegrator(0.001) for _ in range(2)]
    contexts = [
        mm.Context(sys, it, mm.Platform.getPlatformByName("Reference"))
        for sys, it in zip([s, exported], integrators)
    ]

    def evaluate(ctx, pos):
        ctx.setPositions(pos * u.angstrom)
        st = ctx.getState(getEnergy=True, getForces=True)
        return st.getPotentialEnergy().value_in_unit(
            u.kilocalorie_per_mole
        ), -np.asarray(
            st.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        ).ravel()

    e, g = evaluate(contexts[0], x)
    ee, gg = evaluate(contexts[1], x)
    centered = x - x.mean(axis=0)
    rigid = np.column_stack(
        [np.tile(v, (len(x), 1)).ravel() for v in np.eye(3)]
        + [np.cross(np.tile(v, (len(x), 1)), centered).ravel() for v in np.eye(3)]
    )
    basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
    curv = []
    for step in [1e-4, 5e-5]:
        h = np.empty((x.size, x.size))
        for i in range(x.size):
            a = x.ravel().copy()
            b = a.copy()
            a[i] += step
            b[i] -= step
            h[:, i] = (
                evaluate(contexts[0], a.reshape(-1, 3))[1]
                - evaluate(contexts[0], b.reshape(-1, 3))[1]
            ) / (2 * step)
        eig = np.linalg.eigvalsh(basis.T @ ((h + h.T) / 2) @ basis)
        curv.append(
            dict(
                step_A=step,
                minimum_internal_curvature=float(eig[0]),
                negative_mode_count=int((eig < 0).sum()),
            )
        )
    record = dict(
        model=label,
        max_force_kcal_mol_A=float(abs(g).max()),
        export_energy_error_kcal_mol=abs(e - ee),
        export_force_error_kcal_mol_A=float(abs(g - gg).max()),
        curvatures=curv,
        stationary=bool(abs(g).max() < 0.001),
        positive_curvature=bool(all(c["minimum_internal_curvature"] > 0 for c in curv)),
        export_equivalent=bool(abs(e - ee) < 1e-7 and abs(g - gg).max() < 1e-7),
        sources=[
            source(folder / f) for f in ["minimum_A.txt", "system.xml", "fragment.psf"]
        ],
    )
    records.append(record)
    del contexts, integrators
write(
    root / "assessment.json",
    dict(
        records=records,
        parameter_source=source(candidate / "comparator_last.prm"),
        simulation_ready=False,
        scope="MM numerical stability and export checks on failed geometry training candidate; not geometry acceptance, electrostatic or DNA validation",
    ),
)
print(json.dumps(records, indent=2))
