"""Minimum curvature and native force checks for the two sugar-boundary probes."""

import argparse, json, struct, subprocess, sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import app, unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import BASE, FF, source, write
from experiments.cpd_published_comparator.local_benchmarks import checked

parser = argparse.ArgumentParser()
parser.add_argument(
    "--root",
    type=Path,
    default=Path(".development-artifacts/cpd-sugar-boundary-validation-v2"),
)
parser.add_argument(
    "--candidate", type=Path, default=Path(".development-artifacts/cpd-angle-native-v1")
)
args = parser.parse_args()
root = args.root.resolve()
candidate = args.candidate.resolve()
assert not (root / "minimum_and_engine_checks.json").exists(), (
    "Preserve frozen assessments; choose a fresh root"
)
records = []
for endpoint in [1, 2]:
    out = root / f"endpoint-{endpoint}"
    report = json.loads((out / "assessment.json").read_text())
    xp = checked(report["sources"][0])
    xyz = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in xp.read_text().splitlines()[2:]
            if l.strip()
        ]
    )
    x = np.loadtxt(out / "minimum_A.txt")
    s = mm.XmlSerializer.deserialize((out / "system.xml").read_text())
    it = mm.VerletIntegrator(0.001)
    ctx = mm.Context(s, it, mm.Platform.getPlatformByName("Reference"))

    def evaluate(pos, ctx=ctx):
        ctx.setPositions(pos * u.angstrom)
        st = ctx.getState(getEnergy=True, getForces=True)
        return st.getPotentialEnergy().value_in_unit(
            u.kilocalorie_per_mole
        ), np.asarray(
            st.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        )

    eigen = []
    for step in [1e-4, 5e-5]:
        h = np.empty((147, 147))
        for i in range(147):
            a = x.ravel().copy()
            b = a.copy()
            a[i] += step
            b[i] -= step
            h[:, i] = -(
                evaluate(a.reshape(49, 3))[1] - evaluate(b.reshape(49, 3))[1]
            ).ravel() / (2 * step)
        c = x - x.mean(axis=0)
        rigid = np.column_stack(
            [np.tile(v, (49, 1)).ravel() for v in np.eye(3)]
            + [np.cross(np.tile(v, (49, 1)), c).ravel() for v in np.eye(3)]
        )
        basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
        eigen.append(float(np.linalg.eigvalsh(basis.T @ ((h + h.T) / 2) @ basis).min()))
    psf = app.CharmmPsfFile(str(out / "fragment.psf"))
    pdb = []
    for i, (atom, pos) in enumerate(zip(psf.atom_list, x), 1):
        pdb.append(
            f"ATOM  {i:5d} {atom.name:4s} CPD B   1    {pos[0]:8.3f}{pos[1]:8.3f}{pos[2]:8.3f}  1.00  0.00      B"
        )
    (out / "engine.pdb").write_text("\n".join(pdb) + "\nEND\n")
    checks = []
    for label, pos in [("qm", xyz), ("minimum", x)]:
        e, f = evaluate(pos)
        prefix = out / f"engine_{label}"
        prefix.with_suffix(".coor").write_bytes(
            struct.pack("i", 49) + pos.astype(np.float64).tobytes()
        )
        config = f"""structure {out}/fragment.psf
coordinates {out}/engine.pdb
binCoordinates {prefix}.coor
paraTypeCharmm on
parameters {BASE}/par_all36_na.prm
parameters {FF}/par_all36_cgenff.prm
parameters {candidate}/comparator_last.prm
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
run 0
output onlyforces {prefix}
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
        assert p.returncode == 0 and rows and "FATAL ERROR" not in log
        data = prefix.with_suffix(".force").read_bytes()
        assert struct.unpack("i", data[:4])[0] == 49
        nf = np.frombuffer(data[4:], dtype=np.float64).reshape(49, 3)
        de = float(rows[-1][11]) - e
        df = float(np.max(abs(nf - f)))
        checks.append(
            {
                "geometry": label,
                "energy_error_kcal_mol": de,
                "max_force_error_kcal_mol_A": df,
                "passed": abs(de) < 0.001 and df < 0.001,
            }
        )
    records.append(
        {
            "endpoint": endpoint,
            "smallest_internal_curvatures_step_halving": eigen,
            "minimum_passed": all(v > 0 for v in eigen),
            "native_checks": checks,
        }
    )
    del ctx, it
write(
    root / "minimum_and_engine_checks.json",
    {
        "simulation_ready": False,
        "records": records,
        "source": source(Path(__file__)),
        "parameters": source(candidate / "comparator_last.prm"),
    },
)
print(json.dumps(records, indent=2))
