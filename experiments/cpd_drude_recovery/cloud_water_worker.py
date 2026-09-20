"""Sequential rigid-monomer CP energy worker for the frozen small cloud batch."""

import hashlib
import json
import os
from pathlib import Path
import time

import psi4

root = Path.cwd()
plan_path = root / "batch.json"
plan = json.loads(plan_path.read_text())
assert psi4.__version__ == "1.11"
psi4.set_memory("48 GiB")
psi4.set_num_threads(8)
for case in plan["cases"]:
    target = root / "results" / case["id"]
    target.mkdir(parents=True, exist_ok=False)
    scratch = target / "scratch"
    scratch.mkdir()
    os.environ["PSI_SCRATCH"] = str(scratch)
    psi4.core.IOManager.shared_object().set_default_path(str(scratch))
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.core.clean_variables()
    psi4.set_output_file(str(target / "output.dat"), False)
    molecule = psi4.geometry(case["molecule"])
    psi4.set_options(
        {
            "basis": "cc-pVQZ",
            "scf_type": "df",
            "mp2_type": "df",
            "reference": "rhf",
            "freeze_core": True,
            "e_convergence": 1e-9,
            "d_convergence": 1e-9,
            "maxiter": 200,
        }
    )
    started = time.time()
    energy = float(psi4.energy("mp2", molecule=molecule, bsse_type="cp"))
    reported = float(psi4.variable("CP-CORRECTED INTERACTION ENERGY"))
    if abs(energy - reported) > 1e-12:
        raise ValueError("CP energy variable disagrees with returned energy")
    result = {
        "case_id": case["id"],
        "status": "completed_unreviewed",
        "simulation_ready": False,
        "gate_effect": "none",
        "cp_interaction_hartree": energy,
        "cp_interaction_kcal_mol": energy * 627.5094740631,
        "elapsed_seconds": time.time() - started,
        "psi4_version": psi4.__version__,
        "batch_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "variables": {
            k: float(v)
            for k, v in psi4.core.variables().items()
            if isinstance(v, (float, int))
        },
    }
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    psi4.core.clean()
    print("Completed", case["id"], flush=True)
    if (
        case.get("reference_kcal_mol") is not None
        and abs(result["cp_interaction_kcal_mol"] - case["reference_kcal_mol"]) > 1e-5
    ):
        raise ValueError(
            "Cloud portability reference differs by more than 1e-5 kcal/mol"
        )
