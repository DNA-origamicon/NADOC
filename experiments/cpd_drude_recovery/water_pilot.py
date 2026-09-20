"""Materialize one bounded, gate-neutral correlated CPD/water feasibility pilot."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-job", type=Path, required=True)
    p.add_argument("--reference-response", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    root = args.output.resolve()
    root.mkdir(exist_ok=False)
    (root / "generator_snapshot.py").write_text(Path(__file__).read_text())
    job = json.loads(args.source_job.read_text())
    response = json.loads(args.reference_response.read_text())
    solute = parse_xyz(checked(job["source_xyz"]).read_text())[0]
    water = parse_xyz(checked(job["water_xyz"]).read_text())[0]
    reference = parse_xyz(checked(response["sources"]["target_geometry"]).read_text())[
        0
    ]
    if len(solute) != 36 or len(water) != 3 or len(reference) != 36:
        raise ValueError("Unexpected pilot atom counts")
    if [a[0] for a in solute] != [a[0] for a in reference] or not np.allclose(
        np.array([a[1:] for a in solute]),
        np.array([a[1:] for a in reference]),
        rtol=0,
        atol=1e-8,
    ):
        raise ValueError("Water source solute differs from current audited QM minimum")
    if (job["product_id"], job["probe_id"]) != (
        "tt-cpd-cis-anti-i",
        "endpoint1-o4-acceptor",
    ) or abs(job["target_probe_distance_angstrom"] - 1.8) > 1e-8:
        raise ValueError("Pilot selection changed")

    def coordinates(atoms):
        return "\n".join(
            f"{element} {x:.12f} {y:.12f} {z:.12f}" for element, x, y, z in atoms
        )

    molecule = (
        "0 1\n"
        + coordinates(solute)
        + "\n--\n0 1\n"
        + coordinates(water)
        + "\nunits angstrom\nno_com\nno_reorient\nsymmetry c1\n"
    )
    write(
        root / "policy.json",
        {
            "schema": "nadoc.cpd-water-correlated-pilot.v1",
            "status": "frozen_before_calculation",
            "simulation_ready": False,
            "gate_effect": "none",
            "role": "Single feasibility/training pilot, never independent validation or parameter-fit acceptance.",
            "product_id": job["product_id"],
            "model_id": job["model_id"],
            "method": "DF-MP2",
            "basis": "cc-pVQZ",
            "freeze_core": True,
            "scf_type": "df",
            "bsse_type": "cp",
            "energy_scale": 1.0,
            "distance_offset_angstrom": 0.0,
            "geometry": "Rigid archived audited gas-phase CPD minimum and unchanged 0.9572 A/104.52 degree water; no dimer optimization. Pilot does not establish MP2 geometry protocol equivalence.",
            "probe_id": job["probe_id"],
            "target_probe_distance_angstrom": job["target_probe_distance_angstrom"],
            "resources": {
                "threads": 8,
                "psi4_memory_gib": 48,
                "slurm_memory_gib": 64,
                "walltime_hours": 2,
            },
            "sources": {
                "source_job": source(args.source_job),
                "source_input": source(checked(job["input"])),
                "solute": source(checked(job["source_xyz"])),
                "water": source(checked(job["water_xyz"])),
                "current_qm_response": source(args.reference_response),
                "generator": source(root / "generator_snapshot.py"),
            },
            "references": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC5484419/",
                "https://psicode.org/psi4manual/master/psithoninput.html",
            ],
            "next": "Audit CP components, convergence, memory and timing before freezing a complete correlated training/validation campaign; no automatic NBFIX fit.",
        },
    )
    program = """import hashlib
import json
import time
from pathlib import Path
import psi4

started = time.time()
psi4.set_output_file("output.dat", False)
psi4.set_memory("48 GiB")
psi4.set_num_threads(8)
mol = psi4.geometry(MOLECULE)
psi4.set_options({"basis": "cc-pVQZ", "scf_type": "df", "mp2_type": "df", "reference": "rhf", "freeze_core": True, "e_convergence": 1e-9, "d_convergence": 1e-9, "maxiter": 200})
energy = psi4.energy("mp2", molecule=mol, bsse_type="cp")
variables = {key: float(value) for key, value in psi4.core.variables().items() if isinstance(value, (float, int))}
result = {"schema": "nadoc.cpd-water-pilot-result.v1", "status": "completed_unreviewed", "simulation_ready": False, "gate_effect": "none", "psi4_version": psi4.__version__, "cp_interaction_hartree": float(energy), "cp_interaction_kcal_mol": float(energy) * 627.5094740631, "elapsed_seconds": time.time() - started, "variables": variables, "input_sha256": hashlib.sha256(Path("pilot.py").read_bytes()).hexdigest(), "policy_sha256": hashlib.sha256(Path("policy.json").read_bytes()).hexdigest()}
Path("result.json").write_text(json.dumps(result, indent=2) + "\\n")
psi4.core.print_out("NADOC_CORRELATED_WATER_PILOT_COMPLETE\\n")
psi4.core.clean()
""".replace("MOLECULE", repr(molecule))
    compile(program, "pilot.py", "exec")
    (root / "pilot.py").write_text(program)
    write(
        root / "input_manifest.json",
        {
            "files": [source(root / "policy.json"), source(root / "pilot.py")],
            "gate_effect": "none",
            "simulation_ready": False,
        },
    )
    print(root)


if __name__ == "__main__":
    main()
