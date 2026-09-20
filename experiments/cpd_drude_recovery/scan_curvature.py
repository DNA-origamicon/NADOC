"""Independent scan shape diagnostics; no refitting or target exclusion."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(root, assessment):
    root.mkdir(exist_ok=False)
    data = json.loads(assessment.read_text())
    for record in data["sources"]:
        checked(record)
    # Keep the exact partial/complete assessment consumed even if collection continues.
    snapshot = root / "input_assessment.json"
    snapshot.write_text(assessment.read_text())
    records = []
    for model in data["models"]:
        lookup = {(r["endpoint"], r["displacement_angstrom"]): r for r in model["rows"]}
        for endpoint in (1, 2):
            for delta in (0.01, 0.02, 0.04):
                if (endpoint, delta) not in lookup or (endpoint, -delta) not in lookup:
                    continue
                plus, minus = lookup[endpoint, delta], lookup[endpoint, -delta]
                qm_curvature = (
                    plus["qm_projected_gradient_kcal_mol_angstrom"]
                    - minus["qm_projected_gradient_kcal_mol_angstrom"]
                ) / (2 * delta)
                harmonic_curvature = (
                    plus["harmonic_reference_projected_gradient_kcal_mol_angstrom"]
                    - minus["harmonic_reference_projected_gradient_kcal_mol_angstrom"]
                ) / (2 * delta)
                mm_curvature = qm_curvature + (
                    plus["projected_gradient_error_kcal_mol_angstrom"]
                    - minus["projected_gradient_error_kcal_mol_angstrom"]
                ) / (2 * delta)
                records.append(
                    {
                        "fit": model["fit"],
                        "endpoint": endpoint,
                        "half_width_angstrom": delta,
                        "qm_gradient_secant_curvature_kcal_mol_angstrom2": qm_curvature,
                        "qm_energy_secant_curvature_kcal_mol_angstrom2": (
                            plus["qm_relative_energy_kcal_mol"]
                            + minus["qm_relative_energy_kcal_mol"]
                        )
                        / delta**2,
                        "original_qm_hessian_curvature_kcal_mol_angstrom2": harmonic_curvature,
                        "mm_gradient_secant_curvature_kcal_mol_angstrom2": mm_curvature,
                        "mm_to_qm_curvature_ratio": mm_curvature / qm_curvature,
                        "qm_compression_to_extension_energy_ratio": minus[
                            "qm_relative_energy_kcal_mol"
                        ]
                        / plus["qm_relative_energy_kcal_mol"],
                    }
                )
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Central secants of independent fixed-nucleus C6-H6 scans; descriptive shape diagnosis, not relaxed modes or an acceptance criterion.",
            "input_assessment": source(snapshot),
            "script": source(Path(__file__)),
            "full_scan_complete": data["complete_qm_coverage"],
            "records": records,
        },
    )
    for r in records:
        if r["half_width_angstrom"] == 0.01:
            print(
                Path(r["fit"]["path"]).parent.name,
                "endpoint",
                r["endpoint"],
                "QM curvature",
                r["qm_gradient_secant_curvature_kcal_mol_angstrom2"],
                "MM curvature",
                r["mm_gradient_secant_curvature_kcal_mol_angstrom2"],
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--assessment", type=Path, required=True)
    a = p.parse_args()
    main(a.root.resolve(), a.assessment.resolve())
