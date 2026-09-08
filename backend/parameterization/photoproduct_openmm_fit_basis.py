"""Build a gate-neutral linear OpenMM basis for photoproduct bonded fitting."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np

from backend.parameterization.photoproduct_bonded_fit_plan import DIHEDRAL_CONVENTION


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_source(record: dict[str, Any], label: str) -> Path:
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path


def _parameter_prefix(position: int, group_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", group_id).strip("_").lower()
    return f"nadoc_fit_{position:03d}_{slug}"


def enumerate_linear_fit_parameters(
    fit_plan: dict[str, Any],
    *,
    torsion_periodicities: Iterable[int] = range(1, 7),
    improper_equilibrium_mode: str = "fit_offset",
    angle_urey_bradley_mode: str = "fit",
) -> list[dict[str, Any]]:
    """Enumerate a force/Hessian-linear basis without assigning physical parameters."""

    periodicities = tuple(int(value) for value in torsion_periodicities)
    if not periodicities or len(set(periodicities)) != len(periodicities):
        raise ValueError("torsion periodicities must be a nonempty unique sequence")
    if any(value < 1 or value > 6 for value in periodicities):
        raise ValueError(
            "candidate CHARMM torsion periodicities must be between 1 and 6"
        )
    if improper_equilibrium_mode not in {"fit_offset", "fixed_qm_reference"}:
        raise ValueError("unsupported improper equilibrium mode")
    if angle_urey_bradley_mode not in {"fit", "omit"}:
        raise ValueError("unsupported angle Urey-Bradley mode")
    records: list[dict[str, Any]] = []
    groups = fit_plan.get("uncovered_parameter_groups") or []
    for position, group in enumerate(groups):
        variables = group.get("variables") or {}
        if not variables or any(value is not None for value in variables.values()):
            raise ValueError(
                "fit plan contains assigned or malformed missing-term values"
            )
        prefix = _parameter_prefix(position, str(group.get("id") or ""))
        category = group.get("category")
        common = {
            "group_id": group["id"],
            "category": category,
            "occurrence_count": len(group.get("occurrences") or []),
        }
        if category == "bonds":
            for suffix, basis, units in (
                ("r2", "r^2", "kcal/mol/angstrom^2"),
                ("r", "r", "kcal/mol/angstrom"),
            ):
                records.append(
                    {
                        **common,
                        "name": f"{prefix}_{suffix}",
                        "basis": basis,
                        "coefficient_units": units,
                        "default": 0.0,
                    }
                )
        elif category == "angles":
            coordinates = [
                ("theta2", "theta^2", "kcal/mol/rad^2"),
                ("theta", "theta", "kcal/mol/rad"),
            ]
            if angle_urey_bradley_mode == "fit":
                coordinates.extend(
                    [
                        ("r13_2", "r13^2", "kcal/mol/angstrom^2"),
                        ("r13", "r13", "kcal/mol/angstrom"),
                    ]
                )
            for suffix, basis, units in coordinates:
                records.append(
                    {
                        **common,
                        "name": f"{prefix}_{suffix}",
                        "basis": basis,
                        "coefficient_units": units,
                        "default": 0.0,
                    }
                )
        elif category == "dihedrals":
            for periodicity in periodicities:
                records.append(
                    {
                        **common,
                        "name": f"{prefix}_cos_n{periodicity}",
                        "basis": f"cos({periodicity}*phi)",
                        "coefficient_units": "kcal/mol",
                        "periodicity": periodicity,
                        "default": 0.0,
                    }
                )
        else:
            raise ValueError(f"unsupported uncovered category: {category!r}")
    offset = len(groups)
    for position, improper in enumerate(fit_plan.get("stereochemical_impropers") or []):
        atoms = improper.get("ordered_atoms_candidate") or []
        if len(atoms) != 4 or improper.get("status") != (
            "ordering_and_parameters_require_product_review"
        ):
            raise ValueError("stereochemical improper candidate is malformed")
        reference = float(improper["observed_improper_degrees"])
        common = {
            "group_id": f"improper:{improper['stereocenter']}",
            "category": "impropers",
            "occurrence_count": 1,
            "ordered_atoms_candidate": atoms,
            "reference_degrees": reference,
            # Older diagnostic fit plans predate the explicit signed-volume
            # annotation.  Preserve their ability to reproduce the historical
            # fit; policies that require basin validation reject a missing
            # value during candidate selection.
            "expected_signed_volume": improper.get("expected_signed_volume"),
        }
        prefix = _parameter_prefix(offset + position, common["group_id"])
        records.append(
            {
                **common,
                "name": f"{prefix}_delta2",
                "basis": "wrapped_delta^2",
                "coefficient_units": "kcal/mol/rad^2",
                "default": 0.0,
            }
        )
        if improper_equilibrium_mode == "fit_offset":
            records.append(
                {
                    **common,
                    "name": f"{prefix}_delta",
                    "basis": "wrapped_delta",
                    "coefficient_units": "kcal/mol/rad",
                    "default": 0.0,
                }
            )
    names = [record["name"] for record in records]
    if len(names) != len(set(names)):
        raise ValueError("linear fit parameter names are not unique")
    return records


def _evaluate_system(
    system: Any,
    positions: Any,
    openmm: Any,
    unit: Any,
    *,
    parameter_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system, integrator, openmm.Platform.getPlatformByName("Reference")
    )
    context.setPositions(positions)
    for name, value in (parameter_values or {}).items():
        context.setParameter(name, value)
    state = context.getState(getEnergy=True, getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
    forces = state.getForces(asNumpy=True).value_in_unit(
        unit.kilocalorie_per_mole / unit.angstrom
    )
    context_parameters = dict(context.getParameters())
    del context, integrator
    return {
        "energy": float(energy),
        "forces": np.asarray(forces, dtype=float),
        "parameters": context_parameters,
    }


def build_openmm_linear_fit_basis(
    *,
    skeleton_manifest_path: Path,
    fit_plan_path: Path,
    output_dir: Path,
    torsion_periodicities: Iterable[int] = range(1, 7),
    improper_equilibrium_mode: str = "fit_offset",
    angle_urey_bradley_mode: str = "fit",
) -> dict[str, Any]:
    """Add zero-valued linear fit coordinates to an incomplete OpenMM skeleton.

    The result is an optimization representation, never a molecular-dynamics system.
    Its default state must reproduce the input skeleton exactly.
    """

    try:
        import openmm
        from openmm import app, unit
    except ImportError as exc:
        raise RuntimeError(
            "OpenMM is required in the photoproduct QM environment"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite OpenMM fit basis: {output_dir}")
    skeleton = json.loads(skeleton_manifest_path.read_text())
    fit_plan = json.loads(fit_plan_path.read_text())
    if (
        skeleton.get("schema") != "nadoc.photoproduct-openmm-candidate-skeleton.v1"
        or skeleton.get("status") != "candidate_incomplete_missing_bonded_terms"
        or skeleton.get("simulation_ready") is not False
        or skeleton.get("gate_effect") != "none"
    ):
        raise ValueError("input is not a gate-neutral incomplete OpenMM skeleton")
    if (
        fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or fit_plan.get("gate_effect") != "none"
        or fit_plan.get("dihedral_convention") != DIHEDRAL_CONVENTION
    ):
        raise ValueError("input is not an unassigned gate-neutral bonded fit plan")
    if any(
        skeleton.get(key) != fit_plan.get(key)
        for key in ("product_id", "model_id", "hypothesis_id")
    ):
        raise ValueError("skeleton and fit plan identities differ")
    skeleton_sources = skeleton.get("sources") or {}
    if (skeleton_sources.get("fit_plan") or {}).get("sha256") != _sha256(fit_plan_path):
        raise ValueError("skeleton is not hash-linked to the selected fit plan")
    outputs = skeleton.get("outputs") or {}
    system_path = _checked_source(outputs.get("system_xml") or {}, "candidate system")
    pdb_path = _checked_source(outputs.get("model_pdb") or {}, "candidate coordinates")
    map_path = _checked_source(outputs.get("stable_atom_map") or {}, "stable atom map")
    atom_map = json.loads(map_path.read_text())
    if [record.get("index") for record in atom_map] != list(range(len(atom_map))):
        raise ValueError("stable atom map indices are not contiguous and ordered")
    stable_indices = {record["stable_atom_key"]: record["index"] for record in atom_map}
    if len(stable_indices) != len(atom_map):
        raise ValueError("stable atom map keys are not unique")

    base_system = openmm.XmlSerializer.deserialize(system_path.read_text())
    fit_system = openmm.XmlSerializer.deserialize(system_path.read_text())
    parameters = enumerate_linear_fit_parameters(
        fit_plan,
        torsion_periodicities=torsion_periodicities,
        improper_equilibrium_mode=improper_equilibrium_mode,
        angle_urey_bradley_mode=angle_urey_bradley_mode,
    )
    parameters_by_group: dict[str, list[dict[str, Any]]] = {}
    for record in parameters:
        parameters_by_group.setdefault(record["group_id"], []).append(record)

    for group in fit_plan.get("uncovered_parameter_groups") or []:
        records = parameters_by_group[group["id"]]
        if group["category"] == "bonds":
            by_basis = {record["basis"]: record for record in records}
            expression = (
                f"4.184*({by_basis['r^2']['name']}*ra^2+"
                f"{by_basis['r']['name']}*ra);ra=10*r"
            )
            force = openmm.CustomBondForce(expression)
            for basis in ("r^2", "r"):
                force.addGlobalParameter(by_basis[basis]["name"], 0.0)
            for occurrence in group.get("occurrences") or []:
                try:
                    indices = [stable_indices[key] for key in occurrence["atoms"]]
                except KeyError as exc:
                    raise ValueError(
                        f"fit-plan atom is absent from stable map: {exc}"
                    ) from exc
                force.addBond(*indices, [])
            fit_system.addForce(force)
            continue
        if group["category"] == "angles":
            by_basis = {record["basis"]: record for record in records}
            expression = (
                f"4.184*({by_basis['theta^2']['name']}*theta^2+"
                f"{by_basis['theta']['name']}*theta"
            )
            if angle_urey_bradley_mode == "fit":
                expression += (
                    f"+{by_basis['r13^2']['name']}*r13a^2+"
                    f"{by_basis['r13']['name']}*r13a);"
                    "theta=angle(p1,p2,p3);r13a=10*distance(p1,p3)"
                )
            else:
                expression += ");theta=angle(p1,p2,p3)"
            force = openmm.CustomCompoundBondForce(3, expression)
            for basis in by_basis:
                force.addGlobalParameter(by_basis[basis]["name"], 0.0)
            for occurrence in group.get("occurrences") or []:
                try:
                    indices = [stable_indices[key] for key in occurrence["atoms"]]
                except KeyError as exc:
                    raise ValueError(
                        f"fit-plan atom is absent from stable map: {exc}"
                    ) from exc
                force.addBond(indices, [])
            fit_system.addForce(force)
            continue
        records = sorted(records, key=lambda record: record["periodicity"])
        expression = (
            "4.184*("
            + "+".join(
                f"{record['name']}*cos({record['periodicity']}*theta)"
                for record in records
            )
            + ")"
        )
        force = openmm.CustomTorsionForce(expression)
        for record in records:
            force.addGlobalParameter(record["name"], 0.0)
        for occurrence in group.get("occurrences") or []:
            try:
                indices = [stable_indices[key] for key in occurrence["atoms"]]
            except KeyError as exc:
                raise ValueError(
                    f"fit-plan atom is absent from stable map: {exc}"
                ) from exc
            force.addTorsion(*indices, [])
        fit_system.addForce(force)

    for improper in fit_plan.get("stereochemical_impropers") or []:
        group_id = f"improper:{improper['stereocenter']}"
        records = parameters_by_group[group_id]
        by_basis = {record["basis"]: record for record in records}
        reference = math.radians(float(improper["observed_improper_degrees"]))
        energy = f"{by_basis['wrapped_delta^2']['name']}*delta^2"
        if "wrapped_delta" in by_basis:
            energy += f"+{by_basis['wrapped_delta']['name']}*delta"
        expression = (
            f"4.184*({energy});"
            f"delta=atan2(sin(theta-({reference:.17g})),cos(theta-({reference:.17g})))"
        )
        force = openmm.CustomTorsionForce(expression)
        for record in records:
            force.addGlobalParameter(record["name"], 0.0)
        try:
            indices = [
                stable_indices[key] for key in improper["ordered_atoms_candidate"]
            ]
        except KeyError as exc:
            raise ValueError(f"improper atom is absent from stable map: {exc}") from exc
        force.addTorsion(*indices, [])
        fit_system.addForce(force)

    pdb = app.PDBFile(str(pdb_path))
    if pdb.topology.getNumAtoms() != len(atom_map):
        raise ValueError("candidate coordinate atom count differs from stable atom map")
    base_evaluation = _evaluate_system(base_system, pdb.positions, openmm, unit)
    fit_evaluation = _evaluate_system(fit_system, pdb.positions, openmm, unit)
    energy_error = abs(base_evaluation["energy"] - fit_evaluation["energy"])
    force_error = float(
        np.max(np.abs(base_evaluation["forces"] - fit_evaluation["forces"]))
    )
    if energy_error > 1e-10 or force_error > 1e-10:
        raise ValueError("zero-valued linear fit basis changes the candidate skeleton")
    parameter_names = {record["name"] for record in parameters}
    if set(fit_evaluation["parameters"]) != parameter_names:
        raise ValueError(
            "serialized fitting system does not expose the exact parameter map"
        )
    unit_response_checks = {}
    for category in ("bonds", "angles", "dihedrals", "impropers"):
        candidates = [record for record in parameters if record["category"] == category]
        if category == "impropers":
            candidates = [
                record for record in candidates if record["basis"] == "wrapped_delta"
            ]
            if not candidates:
                candidates = [
                    record
                    for record in parameters
                    if record["category"] == category
                    and record["basis"] == "wrapped_delta^2"
                ]
        if not candidates:
            continue
        name = candidates[0]["name"]
        response = _evaluate_system(
            fit_system, pdb.positions, openmm, unit, parameter_values={name: 1.0}
        )
        delta_energy = response["energy"] - fit_evaluation["energy"]
        delta_force = float(
            np.max(np.abs(response["forces"] - fit_evaluation["forces"]))
        )
        if (
            not math.isfinite(delta_energy)
            or not math.isfinite(delta_force)
            or (abs(delta_energy) <= 1e-12 and delta_force <= 1e-12)
        ):
            raise ValueError(
                f"{category} fitting coordinate has no finite unit response"
            )
        unit_response_checks[category] = {
            "parameter": name,
            "energy_delta_kcal_mol": delta_energy,
            "maximum_force_delta_kcal_mol_angstrom": delta_force,
            "passed": True,
        }

    output_dir.mkdir(parents=True)
    xml_path = output_dir / "linear_fit_system.xml"
    parameter_map_path = output_dir / "linear_parameter_map.json"
    xml_path.write_text(openmm.XmlSerializer.serialize(fit_system))
    parameter_map_path.write_text(json.dumps(parameters, indent=2) + "\n")
    periodicities = sorted(
        {
            int(record["periodicity"])
            for record in parameters
            if record["category"] == "dihedrals"
        }
    )
    category_counts = {
        category: sum(record["category"] == category for record in parameters)
        for category in ("bonds", "angles", "dihedrals", "impropers")
    }
    manifest = {
        "schema": "nadoc.photoproduct-openmm-linear-fit-basis.v1",
        "status": "candidate_basis_unfitted_not_releasable",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": fit_plan["product_id"],
        "model_id": fit_plan["model_id"],
        "hypothesis_id": fit_plan["hypothesis_id"],
        "software": {
            "openmm": openmm.version.version,
            "numpy": np.__version__,
        },
        "parameter_count": len(parameters),
        "parameter_counts_by_category": category_counts,
        "torsion_periodicities_to_test": periodicities,
        "improper_equilibrium_mode": improper_equilibrium_mode,
        "angle_urey_bradley_mode": angle_urey_bradley_mode,
        "zero_basis_equivalence": {
            "platform": "Reference",
            "energy_absolute_error_kcal_mol": energy_error,
            "maximum_force_absolute_error_kcal_mol_angstrom": force_error,
            "passed": True,
        },
        "representative_unit_response_checks": unit_response_checks,
        "physical_transform": {
            "harmonic": (
                "For a*x^2+b*x with a>0, CHARMM K=a and x0=-b/(2*a); "
                "reject nonpositive a or out-of-domain x0."
            ),
            "improper": (
                "For fixed_qm_reference, fit only positive curvature around the "
                "ordered QM reference; for fit_offset, transform the fitted linear "
                "offset only when the result remains physical."
            ),
            "proper": (
                "A positive cos(n*phi) coefficient maps to K=coefficient, delta=0; "
                "a negative coefficient maps to K=abs(coefficient), delta=180 degrees."
            ),
        },
        "outputs": {
            "linear_fit_system": {
                "path": str(xml_path.resolve()),
                "sha256": _sha256(xml_path),
            },
            "linear_parameter_map": {
                "path": str(parameter_map_path.resolve()),
                "sha256": _sha256(parameter_map_path),
            },
        },
        "sources": {
            "skeleton_manifest": {
                "path": str(skeleton_manifest_path.resolve()),
                "sha256": _sha256(skeleton_manifest_path),
            },
            "fit_plan": {
                "path": str(fit_plan_path.resolve()),
                "sha256": _sha256(fit_plan_path),
            },
            "candidate_system": outputs["system_xml"],
            "candidate_coordinates": outputs["model_pdb"],
            "stable_atom_map": outputs["stable_atom_map"],
        },
        "fit_requirements": [
            "fit forces and the full coupled Cartesian Hessian, not diagonal projections",
            "use regularization and independently audited train/holdout stereoisomers",
            "select proper periodicities from held-out performance rather than one minimum",
            "reject nonphysical harmonic transforms and validate an MM minimum",
            "review ordered stereochemical impropers before CHARMM export",
        ],
        "release_blockers": [
            "all coefficients are zero and unfitted",
            "torsion periodicities have not been selected",
            "stereochemical improper ordering remains candidate-only",
            "no CHARMM topology/parameter assets have been emitted or reviewed",
        ],
        "warning": (
            "This XML is a linear-response fitting representation with deliberately "
            "missing product physics. It must never be minimized or simulated as a product."
        ),
    }
    manifest_path = output_dir / "linear_fit_basis_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
