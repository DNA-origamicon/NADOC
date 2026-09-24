"""Frozen-candidate comparison to archived MP2/cc-pVTZ deformation energies."""

import argparse, json
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import ARCHIVE, source, write
from experiments.cpd_published_comparator.local_benchmarks import REF, checked

parser = argparse.ArgumentParser()
parser.add_argument(
    "--root",
    type=Path,
    default=Path(".development-artifacts/cpd-independent-energy-v1"),
)
parser.add_argument(
    "--candidate",
    type=Path,
    default=Path(".development-artifacts/cpd-angle-refinement-v2/candidate.xml"),
)
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
base = ARCHIVE / "alpine-qm-relative-energy-campaign-v1/bundle/cases/tt-cpd-cis-syn"
target_path = base / "relative_energy_targets.json"
targets = json.loads(target_path.read_text())
case = json.loads(checked(targets["sources"]["case_manifest"]).read_text())
m = json.loads(
    (
        REF / "minimum_response_fixed_improper_v1/linear_response_manifest.json"
    ).read_text()
)
assert case["atom_map"] == [
    r["stable_atom_key"]
    for r in json.loads(checked(m["sources"]["stable_atom_map"]).read_text())
]
write(
    root / "plan.json",
    {
        "candidate_frozen": source(args.candidate),
        "target": source(target_path),
        "low_energy_ceiling": 12,
        "rmse_limit": 1,
        "max_error_limit": 2,
        "reference_zero_excluded_from_error_statistics": True,
        "new_parameter_fitting": False,
    },
)
s = mm.XmlSerializer.deserialize(args.candidate.read_text())
it = mm.VerletIntegrator(0.001)
ctx = mm.Context(s, it, mm.Platform.getPlatformByName("Reference"))
rows = []
for p in targets["points"]:
    folder = base / "points" / p["point_id"]
    geo = folder / "geometry.xyz"
    output = folder / "output.dat"
    assert (
        source(geo)["sha256"] == p["geometry_sha256"]
        and source(output)["sha256"] == p["output_sha256"]
    )
    xyz = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in geo.read_text().splitlines()[2:]
            if l.strip()
        ]
    )
    assert xyz.shape == (36, 3)
    ctx.setPositions(xyz * u.angstrom)
    e = (
        ctx.getState(getEnergy=True)
        .getPotentialEnergy()
        .value_in_unit(u.kilocalorie_per_mole)
    )
    rows.append(
        {
            "point": p["point_id"],
            "qm_relative_kcal_mol": p["relative_energy_kcal_mol"],
            "mm_absolute_kcal_mol": e,
            "low_energy": p["in_preregistered_low_energy_region"],
            "geometry": source(geo),
        }
    )
e0 = next(r["mm_absolute_kcal_mol"] for r in rows if r["point"] == "minimum")
for r in rows:
    r["mm_relative_kcal_mol"] = r["mm_absolute_kcal_mol"] - e0
    r["error_kcal_mol"] = r["mm_relative_kcal_mol"] - r["qm_relative_kcal_mol"]
errors = [
    r["error_kcal_mol"] for r in rows if r["low_energy"] and r["point"] != "minimum"
]
rmse = float(np.sqrt(np.mean(np.square(errors))))
maximum = float(max(abs(e) for e in errors))
write(
    root / "assessment.json",
    {
        "simulation_ready": False,
        "scope": "Independent of this candidate angle fit, but historically used by earlier custom-forcefield campaigns. Fixed-geometry deformation energies, not relaxed torsional barriers.",
        "low_energy_nonreference_count": len(errors),
        "rmse_kcal_mol": rmse,
        "max_error_kcal_mol": maximum,
        "passed": rmse <= 1 and maximum <= 2,
        "records": rows,
    },
)
print("Independent low-energy RMSE", rmse, "max", maximum)
