"""Execute frozen relaxed ring-torsion pilot; no parameter fitting."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import psi4
from optking.tors import Tors

root = Path.cwd()
plan_path = root / "plan.json"
plan = json.loads(plan_path.read_text())
assert (
    hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == plan["worker"]["sha256"]
)
assert psi4.__version__ == "1.11"
psi4.set_num_threads(4)
psi4.set_memory("4 GiB")
torsion = Tors(*plan["indices_zero_based"])
for case in plan["cases"]:
    folder = root / case["id"]
    folder.mkdir(exist_ok=False)
    (folder / "scratch").mkdir()
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.core.clean_variables()
    psi4.core.IOManager.shared_object().set_default_path(str(folder / "scratch"))
    psi4.set_output_file(str(folder / "output.dat"), False)
    mol = psi4.geometry(plan["molecule"])
    initial_angle = float(np.degrees(torsion.q(np.asarray(mol.geometry()))))
    assert abs(initial_angle - plan["reference_dihedral_degrees"]) < 1e-6
    psi4.set_options(
        {
            "basis": "6-31G(d)",
            "reference": "rhf",
            "scf_type": "df",
            "mp2_type": "df",
            "freeze_core": True,
            "e_convergence": 1e-10,
            "d_convergence": 1e-10,
            "maxiter": 300,
        }
    )
    target = case["target_degrees"]
    constraint = (
        " ".join(str(i + 1) for i in plan["indices_zero_based"])
        + f" {target - 0.0001:.8f} {target + 0.0001:.8f}"
    )
    start = time.time()
    (root / "progress.json").write_text(
        json.dumps(
            {
                "state": "running",
                "case_id": case["id"],
                "started_epoch": start,
                "simulation_ready": False,
            }
        )
        + "\n"
    )
    energy, wfn = psi4.optimize(
        "mp2",
        molecule=mol,
        return_wfn=True,
        optimizer_keywords={
            "ranged_dihedral": constraint,
            "geom_maxiter": 40,
            "g_convergence": "gau_tight",
        },
    )
    xyz = np.asarray(wfn.molecule().geometry()) * psi4.constants.bohr2angstroms
    angle = float(np.degrees(torsion.q(xyz)))
    if abs(angle - target) > 0.001:
        raise ValueError("Final dihedral outside pilot range")
    if not np.isfinite(xyz).all() or not np.isfinite(energy):
        raise ValueError("Nonfinite final state")
    result = {
        "case_id": case["id"],
        "energy_hartree": float(energy),
        "geometry_angstrom": xyz.tolist(),
        "final_dihedral_degrees": angle,
        "elapsed_seconds": time.time() - start,
        "psi4_version": psi4.__version__,
        "simulation_ready": False,
        "gate_effect": "none",
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "status": "completed_unreviewed",
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    psi4.core.clean()
(root / "progress.json").write_text(
    json.dumps(
        {
            "state": "completed",
            "completed_cases": len(plan["cases"]),
            "simulation_ready": False,
        }
    )
    + "\n"
)
