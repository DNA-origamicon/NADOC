"""Audit a fitted OpenMM photoproduct model against fixed-geometry QM energies."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_geometry_refinement import _checked
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_response_fit import (
    transform_linear_coefficients_to_charmm,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def relative_energy_metrics(
    qm_relative: Sequence[float],
    mm_relative: Sequence[float],
    included: Sequence[bool],
    *,
    rmse_target: float = 1.0,
    maximum_error_target: float = 2.0,
) -> dict[str, Any]:
    """Return preregistered low-energy errors without changing the target set."""

    if not (len(qm_relative) == len(mm_relative) == len(included)):
        raise ValueError("relative-energy metric arrays differ in length")
    errors = np.asarray(
        [
            float(mm) - float(qm)
            for qm, mm, use in zip(qm_relative, mm_relative, included, strict=True)
            if use
        ],
        dtype=float,
    )
    if errors.size < 2 or not np.all(np.isfinite(errors)):
        raise ValueError("at least two finite low-energy comparison points are required")
    rmse = float(np.sqrt(np.mean(errors**2)))
    maximum = float(np.max(np.abs(errors)))
    return {
        "point_count": int(errors.size),
        "rmse_kcal_mol": rmse,
        "maximum_absolute_error_kcal_mol": maximum,
        "targets": {
            "rmse_kcal_mol": float(rmse_target),
            "maximum_absolute_error_kcal_mol": float(maximum_error_target),
        },
        "checks": {
            "rmse": rmse <= float(rmse_target),
            "maximum_absolute_error": maximum <= float(maximum_error_target),
        },
        "passed": rmse <= float(rmse_target)
        and maximum <= float(maximum_error_target),
    }


def audit_refined_relative_energies(
    *,
    refinement_report_path: Path,
    relative_energy_targets_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Evaluate one neutral fitted model at immutable QM validation geometries.

    This is a fixed-geometry validation.  It neither performs an MM minimization nor
    turns the interpolation paths into relaxed torsion scans.
    """

    try:
        import openmm
        from openmm import unit
    except ImportError as exc:  # pragma: no cover - pinned fitting environment
        raise RuntimeError("OpenMM is required for relative-energy audit") from exc
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite relative-energy audit: {output_path}")
    refinement = json.loads(refinement_report_path.read_text())
    targets = json.loads(relative_energy_targets_path.read_text())
    if (
        refinement.get("schema") != "nadoc.photoproduct-geometry-refinement.v1"
        or refinement.get("status")
        != "candidate_passed_geometry_curvature_checks"
        or refinement.get("simulation_ready") is not False
        or refinement.get("gate_effect") != "none"
        or targets.get("schema") != "nadoc.photoproduct-relative-energy-targets.v1"
        or targets.get("status") != "complete_unfitted_targets"
        or targets.get("simulation_ready") is not False
        or targets.get("gate_effect") != "none"
        or refinement.get("product_id") != targets.get("product_id")
        or refinement.get("model_id") != targets.get("model_id")
    ):
        raise ValueError("refinement and relative-energy targets have inconsistent identity")

    response_path = _checked(
        (refinement.get("sources") or {}).get("minimum_response_manifest"),
        "minimum response",
    )
    parameter_path = _checked(
        (refinement.get("outputs") or {}).get("refined_parameters"),
        "refined parameters",
    )
    response = json.loads(response_path.read_text())
    system_path = _checked(
        (response.get("sources") or {}).get("linear_fit_system"),
        "linear fit system",
    )
    atom_map_path = _checked(
        (response.get("sources") or {}).get("stable_atom_map"), "stable atom map"
    )
    parameters = json.loads(parameter_path.read_text())
    transform_linear_coefficients_to_charmm(parameters)
    stable_map = json.loads(atom_map_path.read_text())
    stable_keys = [item.get("stable_atom_key") for item in stable_map]
    if len(stable_keys) != len(set(stable_keys)) or any(not key for key in stable_keys):
        raise ValueError("stable atom map is not bijective")

    system = openmm.XmlSerializer.deserialize(system_path.read_text())
    if system.getNumParticles() != len(stable_map):
        raise ValueError("OpenMM particle count differs from stable atom map")
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system, integrator, openmm.Platform.getPlatformByName("Reference")
    )
    names = [str(item.get("name")) for item in parameters]
    if len(names) != len(set(names)) or set(context.getParameters()) != set(names):
        raise ValueError("refined parameter identity differs from OpenMM system")
    for item in parameters:
        context.setParameter(str(item["name"]), float(item["coefficient"]))

    points = []
    target_dir = relative_energy_targets_path.parent
    target_records = targets.get("points") or []
    if len(target_records) < 2 or sum(
        item.get("point_id") == "minimum" for item in target_records
    ) != 1:
        raise ValueError("relative-energy target inventory is incomplete")
    for target in target_records:
        point_id = str(target.get("point_id") or "")
        geometry_path = target_dir / "points" / point_id / "geometry.xyz"
        if (
            not geometry_path.is_file()
            or _sha256(geometry_path) != target.get("geometry_sha256")
        ):
            raise ValueError(f"{point_id}: validation geometry is missing or changed")
        atoms, _comment = parse_xyz(geometry_path.read_text())
        if len(atoms) != len(stable_map):
            raise ValueError(f"{point_id}: geometry atom count differs from stable map")
        expected_elements = [str(item["stable_atom_key"]).split(":", 1)[1][0] for item in stable_map]
        if [item[0].upper() for item in atoms] != [item.upper() for item in expected_elements]:
            raise ValueError(f"{point_id}: geometry element order differs from stable map")
        positions = np.asarray([atom[1:] for atom in atoms], dtype=float)
        if not np.all(np.isfinite(positions)):
            raise ValueError(f"{point_id}: geometry contains non-finite coordinates")
        context.setPositions(positions * unit.angstrom)
        state = context.getState(getEnergy=True, getForces=True)
        energy = float(
            state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
        )
        forces = np.asarray(
            state.getForces(asNumpy=True).value_in_unit(
                unit.kilocalorie_per_mole / unit.angstrom
            ),
            dtype=float,
        )
        if not math.isfinite(energy) or not np.all(np.isfinite(forces)):
            raise ValueError(f"{point_id}: OpenMM evaluation is non-finite")
        points.append(
            {
                "point_id": point_id,
                "qm_relative_energy_kcal_mol": float(
                    target["relative_energy_kcal_mol"]
                ),
                "in_preregistered_low_energy_region": bool(
                    target["in_preregistered_low_energy_region"]
                ),
                "mm_energy_kcal_mol": energy,
                "maximum_force_kcal_mol_angstrom": float(
                    np.max(np.linalg.norm(forces, axis=1))
                ),
                "geometry": _source(geometry_path),
            }
        )
    del context, integrator

    mm_baseline = next(
        item["mm_energy_kcal_mol"] for item in points if item["point_id"] == "minimum"
    )
    for item in points:
        item["mm_relative_energy_kcal_mol"] = (
            item["mm_energy_kcal_mol"] - mm_baseline
        )
        item["error_kcal_mol"] = (
            item["mm_relative_energy_kcal_mol"]
            - item["qm_relative_energy_kcal_mol"]
        )
    metrics = relative_energy_metrics(
        [item["qm_relative_energy_kcal_mol"] for item in points],
        [item["mm_relative_energy_kcal_mol"] for item in points],
        [item["in_preregistered_low_energy_region"] for item in points],
    )
    report = {
        "schema": "nadoc.photoproduct-relative-energy-audit.v1",
        "status": (
            "passed_preregistered_low_energy_targets"
            if metrics["passed"]
            else "failed_preregistered_low_energy_targets"
        ),
        "passed": metrics["passed"],
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": targets["product_id"],
        "model_id": targets["model_id"],
        "method": targets["method"],
        "basis": targets["basis"],
        "evaluation": "fixed_geometry_openmm_potential_energy",
        "metrics": metrics,
        "points": points,
        "sources": {
            "refinement": _source(refinement_report_path),
            "relative_energy_targets": _source(relative_energy_targets_path),
            "refined_parameters": _source(parameter_path),
            "linear_fit_system": _source(system_path),
            "stable_atom_map": _source(atom_map_path),
        },
        "limitations": [
            "interpolation points are validation structures, not relaxed torsion scans",
            "passing does not validate transfer to a DNA environment",
            "this neutral model audit cannot release a force field or simulation path",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
