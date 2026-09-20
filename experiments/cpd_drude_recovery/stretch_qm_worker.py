"""Execute frozen C6-H6 scan points; no fitting or scientific release."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import psi4

root = Path.cwd()
plan = json.loads((root / "plan.json").read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


assert psi4.__version__ == "1.11"
assert digest(__file__) == plan["worker"]["sha256"]
reference_path = Path(plan["reference"]["path"])
assert digest(reference_path) == plan["reference"]["sha256"]
reference = json.loads(reference_path.read_text())["properties"]
psi4.set_memory("4 GiB")
psi4.set_num_threads(4)
for case in plan["cases"]:
    folder = root / case["id"]
    folder.mkdir(exist_ok=False)
    (folder / "scratch").mkdir()
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.core.clean_variables()
    psi4.core.IOManager.shared_object().set_default_path(str(folder / "scratch"))
    psi4.set_output_file(str(folder / "output.dat"), False)
    molecule = psi4.geometry(case["molecule"])
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
    started = time.time()
    (root / "progress.json").write_text(
        json.dumps(
            {
                "state": "running",
                "case_id": case["id"],
                "started_epoch": started,
                "simulation_ready": False,
            }
        )
        + "\n"
    )
    gradient, wfn = psi4.gradient("mp2", molecule=molecule, return_wfn=True)
    g = np.asarray(gradient)
    energy = float(psi4.variable("CURRENT ENERGY"))
    if g.shape != (36, 3) or not np.isfinite(g).all() or not np.isfinite(energy):
        raise ValueError("Invalid QM result")
    if case["id"] == "reference":
        de = abs(energy - reference["return_energy"])
        dg = float(
            abs(g - np.asarray(reference["return_gradient"]).reshape(36, 3)).max()
        )
        passed = (
            de <= plan["reference_energy_tolerance_hartree"]
            and dg <= plan["reference_gradient_tolerance_hartree_bohr"]
        )
        (root / "portability.json").write_text(
            json.dumps(
                {
                    "passed": passed,
                    "energy_difference_hartree": de,
                    "gradient_max_abs_difference_hartree_bohr": dg,
                    "simulation_ready": False,
                },
                indent=2,
            )
            + "\n"
        )
        if not passed:
            raise ValueError("Reference comparison failed; scan not run")
    result = {
        "case_id": case["id"],
        "energy_hartree": energy,
        "gradient_hartree_bohr": g.tolist(),
        "elapsed_seconds": time.time() - started,
        "psi4_version": psi4.__version__,
        "plan_sha256": digest(root / "plan.json"),
        "worker_sha256": digest(__file__),
        "status": "completed_unreviewed",
        "simulation_ready": False,
        "gate_effect": "none",
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    psi4.core.clean()
    print("Completed", case["id"], flush=True)
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
