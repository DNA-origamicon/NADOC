"""Resolve minimum-gradient incompatibility into methyl motion diagnostics."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz


def main(stage, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    manifest_path = stage / "responses/minimum/linear_response_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    with np.load(checked(manifest["outputs"]["linear_response_arrays"])) as f:
        arrays = dict(f)
    params = json.loads((stage / "quantitative_fit_specification.json").read_text())[
        "parameters"
    ]
    names = [
        r["stable_atom_key"]
        for r in json.loads(checked(manifest["sources"]["stable_atom_map"]).read_text())
    ]
    idx = {n: i for i, n in enumerate(names)}
    xyz = np.array(
        [
            r[1:]
            for r in parse_xyz(
                checked(manifest["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )
    scales = np.array([p["scale"] for p in params])
    a = arrays["projected_design_gradient"] * scales
    b = arrays["projected_residual_gradient"]
    coeff = np.linalg.lstsq(a, b, rcond=1e-10)[0] * scales
    residual = (arrays["projected_design_gradient"] @ coeff - b) * np.repeat(
        np.sqrt(arrays["masses_amu"]), 3
    )
    residual = residual.reshape(-1, 3)
    records = []
    for endpoint in (1, 2):
        for parent, carbon, hydrogens in [
            ("N1", "CM", ["HCM1", "HCM2", "HCM3"]),
            ("C5", "C7", ["H51", "H52", "H53"]),
        ]:
            pi, ci = idx[f"{endpoint}:{parent}"], idx[f"{endpoint}:{carbon}"]
            his = [idx[f"{endpoint}:{h}"] for h in hydrogens]
            axis = xyz[ci] - xyz[pi]
            axis /= np.linalg.norm(axis)
            direction = np.zeros_like(xyz)
            radial, transverse = [], []
            for hi in his:
                arm = xyz[hi] - xyz[ci]
                direction[hi] = np.cross(axis, arm)
                bond_unit = arm / np.linalg.norm(arm)
                projection = float(residual[hi] @ bond_unit)
                radial.append(projection)
                transverse.append(
                    float(np.linalg.norm(residual[hi] - projection * bond_unit))
                )
            q = direction.ravel()
            responses = arrays["parameter_gradient_response"] @ q
            torque = float(residual.ravel() @ q)
            contributions = []
            for group in sorted({p["group_id"] for p in params}):
                indices = [i for i, p in enumerate(params) if p["group_id"] == group]
                strength = float(np.linalg.norm((responses * scales)[indices]))
                if strength > 1e-8:
                    contributions.append(
                        {"group": group, "scaled_directional_response_norm": strength}
                    )
            records.append(
                {
                    "endpoint": endpoint,
                    "methyl_carbon": carbon,
                    "irreducible_residual_hydrogen_radial_components_kcal_mol_angstrom": radial,
                    "irreducible_residual_hydrogen_transverse_norms_kcal_mol_angstrom": transverse,
                    "irreducible_residual_rigid_methyl_rotation_derivative_kcal_mol_radian": torque,
                    "reference_fixed_rotation_derivative_kcal_mol_radian": float(
                        arrays["base_gradient_kcal_mol_angstrom"] @ q
                    ),
                    "active_parameter_groups_for_rotation": contributions,
                }
            )
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Training minimum, unbounded least-squares residual. Rigid methyl rotation holds its carbon and all other nuclei fixed; radial/transverse decomposition uses each C-H direction. No fitted candidate or chemistry-dependent symmetry breaking.",
        "sources": [
            source(p)
            for p in (
                manifest_path,
                stage / "quantitative_fit_specification.json",
                root / "source_snapshot.py",
            )
        ],
        "records": records,
    }
    write(root / "assessment.json", report)
    for r in records:
        print(
            r["endpoint"],
            r["methyl_carbon"],
            "rotation residual",
            r["irreducible_residual_rigid_methyl_rotation_derivative_kcal_mol_radian"],
            "active_groups",
            len(r["active_parameter_groups_for_rotation"]),
            "radial",
            r["irreducible_residual_hydrogen_radial_components_kcal_mol_angstrom"],
            "transverse",
            r["irreducible_residual_hydrogen_transverse_norms_kcal_mol_angstrom"],
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    main(a.stage.resolve(), a.root.resolve())
