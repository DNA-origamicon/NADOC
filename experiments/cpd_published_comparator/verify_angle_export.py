"""Matched-coordinate NAMD/OpenMM checks of the exported angle refinement."""

import argparse, json, struct, subprocess, warnings
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import app, unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import FF, write, source

parser = argparse.ArgumentParser()
parser.add_argument(
    "--root", type=Path, default=Path(".development-artifacts/cpd-angle-native-v1")
)
parser.add_argument(
    "--fit", type=Path, default=Path(".development-artifacts/cpd-angle-refinement-v2")
)
parser.add_argument(
    "--psf",
    type=Path,
    default=Path(
        ".development-artifacts/cpd-published-local-benchmarks-no-c5-planarity-v1/core.psf"
    ),
)
args = parser.parse_args()
root = args.root.resolve()
base = Path(
    ".development-artifacts/cpd-published-local-benchmarks-no-c5-planarity-v1"
).resolve()
fit = args.fit.resolve()
assert not (root / "engine_agreement.json").exists(), (
    "Do not overwrite frozen engine checks"
)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    params = app.CharmmParameterSet(
        str(base / "core.rtf"),
        str(FF / "par_all36_cgenff.prm"),
        str(root / "comparator_last.prm"),
    )
psf = app.CharmmPsfFile(str(args.psf.resolve()))
exported = psf.createSystem(
    params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
)
original = mm.XmlSerializer.deserialize((fit / "candidate.xml").read_text())
(root / "core_exported.xml").write_text(mm.XmlSerializer.serialize(exported))
contexts = []
for s in [original, exported]:
    it = mm.VerletIntegrator(0.001)
    contexts.append((mm.Context(s, it, mm.Platform.getPlatformByName("Reference")), it))
x = np.loadtxt(fit / "minimum_A.txt")
records = []
for k in range(3):
    pos = x.copy()
    if k:
        pos += (1 if k == 1 else -1) * np.random.default_rng(712).normal(
            0, 0.01, x.shape
        )
    energies = []
    forces = []
    for ctx, it in contexts:
        ctx.setPositions(pos * u.angstrom)
        st = ctx.getState(getEnergy=True, getForces=True)
        energies.append(st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))
        forces.append(
            np.asarray(
                st.getForces(asNumpy=True).value_in_unit(
                    u.kilocalorie_per_mole / u.angstrom
                )
            )
        )
    assert (
        abs(energies[0] - energies[1]) < 1e-7
        and np.max(np.abs(forces[0] - forces[1])) < 1e-7
    )
    label = f"core_check_{k}"
    (root / f"{label}.coor").write_bytes(
        struct.pack("i", 36) + pos.astype(np.float64).tobytes()
    )
    conf = f"""structure {args.psf.resolve()}
coordinates {base}/core.pdb
binCoordinates {root}/{label}.coor
paraTypeCharmm on
parameters {FF}/par_all36_cgenff.prm
parameters {root}/comparator_last.prm
exclude scaled1-4
oneFourScaling 1
cutoff 100
switching off
pairlistdist 102
margin 2
outputName {root}/{label}
temperature 0
rigidBonds none
timestep 1
stepspercycle 1
run 0
output onlyforces {root}/{label}
"""
    (root / f"{label}.conf").write_text(conf)
    p = subprocess.run(
        ["namd3", "+p1", str(root / f"{label}.conf")], capture_output=True, text=True
    )
    log = p.stdout + p.stderr
    (root / f"{label}.log").write_text(log)
    rows = [l.split() for l in log.splitlines() if l.startswith("ENERGY:")]
    assert p.returncode == 0 and rows and "FATAL ERROR" not in log
    data = (root / f"{label}.force").read_bytes()
    assert struct.unpack("i", data[:4])[0] == 36
    nf = np.frombuffer(data[4:], dtype=np.float64).reshape(36, 3)
    de = float(rows[-1][11]) - energies[1]
    df = float(np.max(np.abs(nf - forces[1])))
    records.append(
        {
            "case": k,
            "energy_error_kcal_mol": de,
            "max_force_error_kcal_mol_A": df,
            "passed": abs(de) < 0.001 and df < 0.001,
            "export_energy_error": energies[1] - energies[0],
        }
    )
write(
    root / "engine_agreement.json",
    {
        "scope": "Capped cis-syn minimum and two fixed random distortions; implementation verification only",
        "criteria": {"energy_abs_kcal_mol": 0.001, "force_max_kcal_mol_A": 0.001},
        "records": records,
        "all_passed": all(r["passed"] for r in records),
        "sources": [source(Path(__file__)), source(root / "comparator_last.prm")],
    },
)
print(json.dumps(records, indent=2))
