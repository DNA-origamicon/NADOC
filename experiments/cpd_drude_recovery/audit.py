"""Audit fitted force reconstruction and local stationarity without refitting."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    AdiabaticNonbonded,
    checked,
    source,
    write,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.stage.resolve()
    args.output.mkdir(exist_ok=False)
    (args.output / "audit_snapshot.py").write_text(Path(__file__).read_text())
    policy = json.loads((root / "policy.json").read_text())
    model = AdiabaticNonbonded(args.recovery, checked(policy["electrostatics"]))
    selected = json.loads((root / "selected_response_fit.json").read_text())
    coefficients = np.array([r["coefficient"] for r in selected["parameters"]])
    system = mm.XmlSerializer.deserialize(
        (root / "basis/linear_fit_system.xml").read_text()
    )
    integrator = mm.VerletIntegrator(0.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    for record in selected["parameters"]:
        context.setParameter(record["name"], record["coefficient"])

    def gradient(xyz):
        _, g = model.energy_gradient(xyz)
        context.setPositions(xyz * u.angstrom)
        state = context.getState(getForces=True)
        return g - np.asarray(
            state.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        ).reshape(-1)

    reports = []
    for directory in sorted((root / "responses").iterdir()):
        manifest_path = directory / "linear_response_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        xyz = np.array(
            [
                a[1:]
                for a in parse_xyz(
                    checked(manifest["sources"]["target_geometry"]).read_text()
                )[0]
            ]
        )
        arrays_path = checked(manifest["outputs"]["linear_response_arrays"])
        with np.load(arrays_path) as data:
            arrays = dict(data)
        reconstructed = (
            arrays["base_gradient_kcal_mol_angstrom"]
            + arrays["design_gradient"] @ coefficients
        )
        direct = gradient(xyz)
        inv = np.repeat(1 / np.sqrt(arrays["masses_amu"]), 3)
        proj = arrays["rigid_body_projector"]
        predicted_error = (
            arrays["projected_design_gradient"] @ coefficients
            - arrays["projected_residual_gradient"]
        )
        projected_error = proj @ (
            inv * (direct - arrays["qm_gradient_kcal_mol_angstrom"])
        )
        # Directional derivatives independently check parameter ordering and Hessian units.
        hessian = arrays["base_hessian_kcal_mol_angstrom2"] + np.einsum(
            "p,pij->ij", coefficients, arrays["parameter_hessian_response"]
        )
        rng = np.random.default_rng(271828)
        errors = []
        for _ in range(3):
            direction = rng.normal(size=xyz.size)
            direction /= np.linalg.norm(direction)
            step = 5e-5
            fd = (
                gradient(xyz + step * direction.reshape(-1, 3))
                - gradient(xyz - step * direction.reshape(-1, 3))
            ) / (2 * step)
            errors.append(
                float(np.linalg.norm(fd - hessian @ direction) / np.linalg.norm(fd))
            )
        report = {
            "dataset": directory.name,
            "manifest": source(manifest_path),
            "gradient_reconstruction_max_abs_kcal_mol_angstrom": float(
                np.max(abs(direct - reconstructed))
            ),
            "projected_residual_reconstruction_max_abs": float(
                np.max(abs(predicted_error - projected_error))
            ),
            "hessian_directional_relative_errors": errors,
            "qm_geometry_raw_gradient_rms_kcal_mol_angstrom": float(
                np.sqrt(np.mean(direct**2))
            ),
        }
        if directory.name == "minimum":
            # Unconstrained lower bound: can this basis make the QM minimum stationary at all?
            target = arrays["residual_gradient"]
            solution, _, rank, _ = np.linalg.lstsq(
                arrays["design_gradient"], target, rcond=1e-8
            )
            irreducible = arrays["design_gradient"] @ solution - target
            report["minimum_gradient_unconstrained_rank"] = int(rank)
            report["minimum_gradient_unconstrained_residual_rms"] = float(
                np.sqrt(np.mean(irreducible**2))
            )
            report["minimum_gradient_unconstrained_residual_max_abs"] = float(
                np.max(abs(irreducible))
            )
            report["irreducible_force_by_atom"] = [
                {"atom": name, "gradient_norm": float(np.linalg.norm(vector))}
                for name, vector in zip(model.d.ATOM_NAMES, irreducible.reshape(-1, 3))
            ]
            # Diagnostic freedom only: independent linear bond/angle coefficients.
            # This does not propose physical force constants or relax a release gate.
            neighbors = {i: set() for i in range(len(xyz))}
            terms = []
            for a, b in model.d._bonds():
                neighbors[a].add(b)
                neighbors[b].add(a)
                terms.append((a, b))
            for center, adjacent in neighbors.items():
                ordered = sorted(adjacent)
                terms.extend(
                    (a, center, b)
                    for j, a in enumerate(ordered)
                    for b in ordered[j + 1 :]
                )
            columns, hydrogen_columns = [], []
            for atoms in terms:

                def coordinate(x):
                    points = x[list(atoms)]
                    if len(atoms) == 2:
                        return np.linalg.norm(points[0] - points[1])
                    a, b = points[0] - points[1], points[2] - points[1]
                    return np.arccos(
                        np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)
                    )

                column = np.zeros(xyz.size)
                for atom in atoms:
                    for axis in range(3):
                        plus, minus = xyz.copy(), xyz.copy()
                        plus[atom, axis] += 1e-5
                        minus[atom, axis] -= 1e-5
                        column[3 * atom + axis] = (
                            coordinate(plus) - coordinate(minus)
                        ) / 2e-5
                columns.append(column)
                if any(
                    model.d.ATOM_NAMES[i].split(":")[1].startswith("H") for i in atoms
                ):
                    hydrogen_columns.append(column)
            report["stationarity_freedom_diagnostics"] = {}
            for label, extra in (
                ("independent_hydrogen_bonds_angles", hydrogen_columns),
                ("independent_all_bonds_angles", columns),
            ):
                design = np.column_stack([arrays["design_gradient"], *extra])
                trial, _, rank, _ = np.linalg.lstsq(design, target, rcond=1e-8)
                report["stationarity_freedom_diagnostics"][label] = {
                    "gradient_rank": int(rank),
                    "unconstrained_residual_rms": float(
                        np.sqrt(np.mean((design @ trial - target) ** 2))
                    ),
                    "added_columns": len(extra),
                }

        reports.append(report)
        print(json.dumps(report), flush=True)
    passed = all(
        r["gradient_reconstruction_max_abs_kcal_mol_angstrom"] < 1e-5
        and r["projected_residual_reconstruction_max_abs"] < 1e-5
        and max(r["hessian_directional_relative_errors"]) < 0.001
        for r in reports
    )
    write(
        args.output / "assessment.json",
        {
            "status": "reconstruction_passed" if passed else "reconstruction_failed",
            "simulation_ready": False,
            "gate_effect": "none",
            "selected_candidate": source(root / "selected_response_fit.json"),
            "code": source(args.output / "audit_snapshot.py"),
            "limits": {
                "gradient_max_abs": 1e-5,
                "projected_residual_max_abs": 1e-5,
                "hessian_directional_relative": 0.001,
            },
            "datasets": reports,
            "interpretation": "Numerical implementation audit only. Unconstrained stationarity residual is a basis lower bound, not a physical fitted candidate.",
        },
    )
    if not passed:
        raise ValueError("Fitted reconstruction audit failed")


if __name__ == "__main__":
    main()
