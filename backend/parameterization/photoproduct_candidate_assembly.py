"""Assemble a traceable, non-releasing CHARMM photoproduct smoke candidate.

This module maps a quantitatively selected response fit and exact pinned CGenFF
records into the existing parameter workbook.  It deliberately distinguishes an
engine-runnable smoke candidate from a force-field release.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_fit import (
    _standard_charmm_atom_types,
    build_parameter_workbook,
)
from backend.parameterization.photoproduct_nonbonded_fit import parse_charmm_nonbonded
from backend.parameterization.photoproduct_openmm_skeleton import (
    assert_pinned_cgenff_inputs,
    parse_charmm_masses,
)


CANDIDATE_ASSEMBLY_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_candidate_assembly_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _canonical_path(atoms: list[str]) -> tuple[str, ...]:
    path = tuple(atoms)
    reverse = tuple(reversed(path))
    return min(path, reverse)


def _model_path(atoms: list[str], substitutions: dict[str, str]) -> list[str]:
    result = []
    for atom in atoms:
        endpoint, separator, local = atom.partition(":")
        if not separator:
            raise ValueError(f"invalid stable atom reference {atom!r}")
        result.append(f"{endpoint}:{substitutions.get(local, local)}")
    return result


def _endpoint_path(endpoint: int, local_atoms: list[str]) -> list[str]:
    return [f"{endpoint}:{atom}" for atom in local_atoms]


def _unique_match_values(record: dict[str, Any]) -> list[float]:
    values = {
        tuple(float(value) for value in item["values"]) for item in record["matches"]
    }
    if len(values) != 1:
        raise ValueError(
            f"{'-'.join(record['atoms'])}: bond/angle transfer values are ambiguous"
        )
    return list(next(iter(values)))


def _fourier_multiplicity(record: dict[str, Any]) -> int:
    """Normalize fitted ``periodicity`` to the workbook's CHARMM multiplicity."""

    value = record.get("multiplicity", record.get("periodicity"))
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Fourier term lacks a positive integer periodicity")
    return value


def _apply_transformed_angle(record: dict[str, Any], transformed: dict[str, Any]) -> None:
    """Copy the complete fitted CHARMM angle, including optional Urey-Bradley.

    The linear response represents angle and 1-3 distance coordinates together.  Dropping
    the latter here would make the exported NAMD model differ from the fitted OpenMM model.
    """

    record.update(
        k_kcal_mol_rad2=float(transformed["k_kcal_mol_rad2"]),
        theta0_degrees=float(transformed["theta0_degrees"]),
    )
    urey_bradley = transformed.get("urey_bradley")
    if urey_bradley is None:
        record.update(
            urey_bradley_k_kcal_mol_a2=None,
            urey_bradley_s0_angstrom=None,
        )
        return
    if not isinstance(urey_bradley, dict):
        raise ValueError("transformed angle has malformed Urey-Bradley data")
    k_value = urey_bradley.get("k_kcal_mol_angstrom2")
    s0_value = urey_bradley.get("s0_angstrom")
    if (
        not isinstance(k_value, (int, float))
        or isinstance(k_value, bool)
        or not math.isfinite(float(k_value))
        or float(k_value) <= 0.0
        or not isinstance(s0_value, (int, float))
        or isinstance(s0_value, bool)
        or not math.isfinite(float(s0_value))
        or float(s0_value) <= 0.0
    ):
        raise ValueError("transformed angle has nonphysical Urey-Bradley data")
    record.update(
        urey_bradley_k_kcal_mol_a2=float(k_value),
        urey_bradley_s0_angstrom=float(s0_value),
    )


def _nonbonded_metrics(
    hypothesis: dict[str, Any], limits: dict[str, Any]
) -> dict[str, Any]:
    held_out = [
        item
        for item in hypothesis.get("water_metrics") or []
        if item.get("split") == "held_out"
    ]
    if not held_out:
        raise ValueError("nonbonded candidate has no held-out water interactions")
    observed = {
        "maximum_charge_constraint_error_e": abs(
            float(hypothesis["maximum_constraint_error_e"])
        ),
        "maximum_charge_change_e": abs(float(hypothesis["maximum_charge_change_e"])),
        "maximum_esp_rmse_atomic_unit": abs(
            float((hypothesis.get("esp_validation") or {})["rmse_atomic_unit"])
        ),
        "maximum_dipole_vector_error_debye": abs(
            float(hypothesis["dipole_vector_error_debye"])
        ),
        "maximum_held_out_water_energy_error_kcal_mol": max(
            abs(float(item["energy_error_kcal_mol"])) for item in held_out
        ),
        "maximum_held_out_water_distance_error_angstrom": max(
            abs(float(item["distance_error_angstrom"])) for item in held_out
        ),
    }
    checks = {
        name: {
            "observed": value,
            "maximum": float(limits[name]),
            "passed": math.isfinite(value) and value <= float(limits[name]),
        }
        for name, value in observed.items()
    }
    if not all(item["passed"] for item in checks.values()):
        failed = ", ".join(name for name, item in checks.items() if not item["passed"])
        raise ValueError(f"nonbonded smoke-candidate limits failed: {failed}")
    return checks


def assemble_quantitative_parameter_workbook(
    *,
    fit_plan_path: Path,
    nonbonded_fit_path: Path,
    charmm_transform_path: Path,
    dna_boundary_model_path: Path,
    cgenff_topology_path: Path,
    cgenff_parameters_path: Path,
    output_path: Path,
    policy_path: Path = CANDIDATE_ASSEMBLY_POLICY_PATH,
) -> dict[str, Any]:
    """Build a complete candidate workbook without asserting scientific release."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite candidate workbook: {output_path}"
        )
    policy = json.loads(policy_path.read_text())
    fit_plan = json.loads(fit_plan_path.read_text())
    nonbonded_fit = json.loads(nonbonded_fit_path.read_text())
    transform = json.loads(charmm_transform_path.read_text())
    boundary = json.loads(dna_boundary_model_path.read_text())
    schema = policy.get("schema")
    scope = policy.get("scope") or {}
    if schema == "nadoc.photoproduct-candidate-assembly-policy.v1":
        product_id = scope.get("product_id")
        hypothesis_id = scope.get("nonbonded_hypothesis_id")
        patch_name = scope.get("patch_name")
    elif schema in {
        "nadoc.photoproduct-candidate-assembly-policy.v2",
        "nadoc.photoproduct-candidate-assembly-policy.v3",
    }:
        product_id = fit_plan.get("product_id")
        allowed = policy.get("allowed_product_ids") or []
        patch_names = policy.get("patch_names") or {}
        hypothesis_id = fit_plan.get("hypothesis_id")
        patch_name = patch_names.get(product_id)
        if (
            not isinstance(product_id, str)
            or product_id not in allowed
            or set(allowed) != set(patch_names)
            or len(allowed) != len(set(allowed))
        ):
            raise ValueError("family candidate policy has invalid product/patch scope")
        scope = {
            "product_id": product_id,
            "nonbonded_hypothesis_id": hypothesis_id,
            "patch_name": patch_name,
        }
    else:
        product_id = None
        hypothesis_id = None
        patch_name = None
    if (
        policy.get("status") != "workflow_policy"
        or fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or nonbonded_fit.get("schema")
        != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"
        or transform.get("schema")
        != "nadoc.photoproduct-charmm-bonded-transform-candidate.v1"
        or transform.get("status")
        != "algebraically_transformed_requires_term_mapping_and_validation"
        or boundary.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or boundary.get("status") != "quantitatively_screened_boundary"
        or fit_plan.get("product_id") != product_id
        or nonbonded_fit.get("product_id") != product_id
        or boundary.get("product_id") != product_id
        or fit_plan.get("hypothesis_id") != hypothesis_id
        or transform.get("hypothesis_id") != hypothesis_id
        or not isinstance(patch_name, str)
        or not patch_name
    ):
        raise ValueError(
            "candidate assembly inputs or policy have inconsistent identity"
        )
    assert_pinned_cgenff_inputs(cgenff_topology_path, cgenff_parameters_path)
    coverage_path = _checked(
        (fit_plan.get("sources") or {}).get("model_coverage"), "model coverage"
    )
    coverage = json.loads(coverage_path.read_text())
    if ((coverage.get("sources") or {}).get("nonbonded_fit") or {}).get(
        "sha256"
    ) != _sha256(nonbonded_fit_path) or (
        (coverage.get("sources") or {}).get("cgenff_parameters") or {}
    ).get("sha256") != _sha256(cgenff_parameters_path):
        raise ValueError(
            "fit plan is not hash-linked to the selected nonbonded/CGenFF inputs"
        )
    transform_sources = transform.get("sources") or {}
    selected_records = [
        record
        for record in (
            transform_sources.get("selected_response_fit_candidate"),
            transform_sources.get("geometry_refinement_candidate"),
        )
        if record is not None
    ]
    if len(selected_records) != 1:
        raise ValueError("transform must identify exactly one fit candidate")
    selected_path = _checked(selected_records[0], "selected bonded-fit candidate")
    hypothesis = next(
        (
            item
            for item in nonbonded_fit.get("results") or []
            if item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )
    if hypothesis is None:
        raise ValueError("selected nonbonded hypothesis is absent")
    nonbonded_checks = _nonbonded_metrics(
        hypothesis, policy["candidate_nonbonded_limits"]
    )

    boundary_transfer = policy["model_compound_boundary_transfer"]
    substitutions = boundary_transfer["stable_atom_substitutions"]
    transfer_by_path = {
        (item["category"], _canonical_path(item["atoms"])): item
        for item in fit_plan["transfer_candidates"]
    }
    group_by_path: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for group in fit_plan["uncovered_parameter_groups"]:
        for occurrence in group["occurrences"]:
            key = (group["category"], _canonical_path(occurrence["atoms"]))
            if key in group_by_path:
                raise ValueError(f"fit occurrence is ambiguous: {key}")
            group_by_path[key] = group
    transformed_by_group = {
        category: {
            item["group_id"]: item for item in transform["bonded_terms"][category]
        }
        for category in ("bonds", "angles", "dihedrals", "impropers")
    }

    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError(f"candidate product is not registered: {product_id}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="nadoc-cpd-workbook-", dir=output_path.parent
    ) as raw:
        scaffold_path = Path(raw) / "scaffold.json"
        workbook = build_parameter_workbook(
            product=registry_entry["product"],
            stereochemistry=registry_entry["stereochemistry"],
            output_path=scaffold_path,
        )
    types_by_atom = hypothesis["atom_types"]
    charges_by_atom = hypothesis["charges_e"]
    expected_atoms = {item["atom"] for item in workbook["atoms"]}
    patch_types = {
        key: value for key, value in types_by_atom.items() if key in expected_atoms
    }
    patch_charges = {
        key: value for key, value in charges_by_atom.items() if key in expected_atoms
    }
    if set(patch_types) != expected_atoms or set(patch_charges) != expected_atoms:
        raise ValueError("nonbonded fit does not exactly cover the patch charge scope")
    if not math.isclose(
        sum(float(value) for value in patch_charges.values()),
        float(workbook["expected_model_charge"]),
        abs_tol=1e-8,
    ):
        raise ValueError("selected patch charges do not conserve pair charge")
    nonbonded_source = json.dumps(_source(nonbonded_fit_path), sort_keys=True)
    cgenff_source = json.dumps(_source(cgenff_parameters_path), sort_keys=True)
    for atom in workbook["atoms"]:
        key = atom["atom"]
        atom.update(
            final_type=patch_types[key],
            final_charge=float(patch_charges[key]),
            charge_fit_source=nonbonded_source,
            lj_source_or_fit=cgenff_source,
        )
    actual_types = {
        item["atom"]: item["final_type"] for item in workbook["atoms"]
    } | workbook["charmm_patch"]["boundary_atom_types"]
    atom_records = {item["atom"]: item for item in workbook["atoms"]}
    standard_types = _standard_charmm_atom_types()
    alias_source_by_type: dict[str, str] = {}
    aliases = policy.get("bonded_identity_type_aliases") or {}
    for atom, alias in aliases.items():
        record = atom_records.get(atom)
        alias_name = alias.get("name") if isinstance(alias, dict) else None
        reason = alias.get("reason") if isinstance(alias, dict) else None
        if (
            record is None
            or not isinstance(alias_name, str)
            or not alias_name
            or len(alias_name) > 8
            or alias_name in standard_types
            or alias_name in alias_source_by_type
            or not isinstance(reason, str)
            or not reason
        ):
            raise ValueError(f"invalid bonded-identity type alias for {atom}")
        source_type = record["final_type"]
        alias_source_by_type[alias_name] = source_type
        record["final_type"] = alias_name
        record["lj_source_or_fit"] = json.dumps(
            {
                "kind": "bonded_identity_alias",
                "source_type": source_type,
                "nonbonded_source": _source(nonbonded_fit_path),
                "policy": _source(policy_path),
                "reason": reason,
            },
            sort_keys=True,
        )
        actual_types[atom] = alias_name

    additional_boundary_dihedrals = boundary_transfer.get(
        "additional_boundary_dihedrals"
    ) or []
    for definition in additional_boundary_dihedrals:
        product_local_atoms = definition.get("product_local_atoms") or []
        model_local_atoms = definition.get("model_local_atoms") or []
        boundary_types = definition.get("boundary_atom_types") or {}
        transfer_policy = boundary_transfer.get("policy")
        methyl_cap_transfer = transfer_policy == "n1-methyl-cap-to-dna-c1-prime-v1"
        full_boundary_transfer = transfer_policy == "full-dtpdt-direct-boundary-v1"
        expected_model_atoms = (
            ["C6", "N1", "CM", model_local_atoms[-1]]
            if methyl_cap_transfer
            else product_local_atoms
        )
        if (
            len(product_local_atoms) != 4
            or len(model_local_atoms) != 4
            or product_local_atoms[:3] != ["C6", "N1", "C1'"]
            or not (methyl_cap_transfer or full_boundary_transfer)
            or model_local_atoms != expected_model_atoms
            or set(boundary_types) != set(product_local_atoms) - {"C6", "N1"}
            or boundary_types.get("C1'") != "CN7B"
        ):
            raise ValueError("invalid additional glycosidic-boundary dihedral policy")
        for endpoint in (1, 2):
            for local, atom_type in boundary_types.items():
                atom = f"{endpoint}:{local}"
                existing = workbook["charmm_patch"]["boundary_atom_types"].get(atom)
                if existing is not None and existing != atom_type:
                    raise ValueError(f"conflicting boundary atom type for {atom}")
                workbook["charmm_patch"]["boundary_atom_types"][atom] = atom_type
                actual_types[atom] = atom_type
            product_atoms = _endpoint_path(endpoint, product_local_atoms)
            model_atoms = _endpoint_path(endpoint, model_local_atoms)
            workbook["bonded_terms"]["dihedrals"].append(
                {
                    "atoms": product_atoms,
                    "model_atoms": model_atoms,
                    "parameter_strategy": "qm_model_boundary_transfer",
                    "parameter_value_or_source": None,
                    "fit_targets": [],
                    "emit_parameter": None,
                    "source": None,
                    "fourier_terms": [],
                }
            )
    workbook["charge_scope"]["unchanged_boundary_atoms"] = sorted(
        workbook["charmm_patch"]["boundary_atom_types"], key=lambda atom: (
            int(atom.split(":", 1)[0]),
            atom.split(":", 1)[1],
        )
    )

    masses = parse_charmm_masses(cgenff_topology_path)
    nonbonded = parse_charmm_nonbonded(cgenff_parameters_path)
    custom_types = sorted(
        {item["final_type"] for item in workbook["atoms"]} - standard_types
    )
    for atom_type in custom_types:
        source_type = alias_source_by_type.get(atom_type, atom_type)
        if source_type not in masses or source_type not in nonbonded:
            raise ValueError(f"CGenFF mass/LJ record is missing for {source_type}")
        lj = nonbonded[source_type]
        workbook["charmm_patch"]["custom_atom_types"].append(
            {
                "name": atom_type,
                "element": masses[source_type]["element"],
                "mass_amu": masses[source_type]["mass_amu"],
                **lj,
                "source": (
                    json.dumps(
                        {
                            "kind": "bonded_identity_alias",
                            "source_type": source_type,
                            "cgenff_parameters": _source(cgenff_parameters_path),
                            "cgenff_topology": _source(cgenff_topology_path),
                            "policy": _source(policy_path),
                        },
                        sort_keys=True,
                    )
                    if atom_type in alias_source_by_type
                    else cgenff_source
                ),
            }
        )

    transform_source = json.dumps(_source(charmm_transform_path), sort_keys=True)

    def types_for(atoms: list[str]) -> list[str]:
        return [actual_types[atom] for atom in atoms]

    for category in ("bonds", "angles", "dihedrals"):
        for record in workbook["bonded_terms"][category]:
            model_atoms = record.get("model_atoms") or _model_path(
                record["atoms"], substitutions
            )
            key = (category, _canonical_path(model_atoms))
            transfer = transfer_by_path.get(key)
            group = group_by_path.get(key)
            if (transfer is None) == (group is None):
                raise ValueError(
                    f"{category} {'-'.join(record['atoms'])}: expected exactly one model mapping"
                )
            boundary_substitution = model_atoms != record["atoms"]
            if boundary_substitution and "C1'" not in [
                atom.split(":", 1)[1] for atom in record["atoms"]
            ]:
                raise ValueError("model boundary substitution escaped the C1' scope")
            record["types"] = types_for(record["atoms"])
            record["emit_parameter"] = True
            if transfer is not None:
                record["source"] = json.dumps(
                    {
                        "kind": (
                            "pinned_cgenff_model_boundary_transfer"
                            if boundary_substitution
                            else "pinned_cgenff_exact_or_wildcard_transfer"
                        ),
                        "fit_plan": _source(fit_plan_path),
                        "matches": transfer["matches"],
                        "boundary_policy": _source(policy_path)
                        if boundary_substitution
                        else None,
                    },
                    sort_keys=True,
                )
                if category == "bonds":
                    values = _unique_match_values(transfer)
                    record.update(k_kcal_mol_a2=values[0], r0_angstrom=values[1])
                elif category == "angles":
                    values = _unique_match_values(transfer)
                    record.update(k_kcal_mol_rad2=values[0], theta0_degrees=values[1])
                    if len(values) == 4:
                        record.update(
                            urey_bradley_k_kcal_mol_a2=values[2],
                            urey_bradley_s0_angstrom=values[3],
                        )
                else:
                    record["fourier_terms"] = [
                        {
                            "k_kcal_mol": float(match["values"][0]),
                            "multiplicity": int(match["values"][1]),
                            "delta_degrees": float(match["values"][2]),
                        }
                        for match in transfer["matches"]
                    ]
            else:
                transformed = transformed_by_group[category].get(group["id"])
                if transformed is None:
                    raise ValueError(
                        f"selected transform lacks fit group {group['id']}"
                    )
                record["source"] = json.dumps(
                    {
                        "kind": (
                            "qm_response_fit_with_model_boundary_transfer"
                            if boundary_substitution
                            else "qm_response_fit"
                        ),
                        "transform": _source(charmm_transform_path),
                        "boundary_policy": _source(policy_path)
                        if boundary_substitution
                        else None,
                    },
                    sort_keys=True,
                )
                record["fit_targets"] = [transform_source]
                if category == "bonds":
                    record.update(
                        k_kcal_mol_a2=float(transformed["k_kcal_mol_a2"]),
                        r0_angstrom=float(transformed["r0_angstrom"]),
                    )
                elif category == "angles":
                    _apply_transformed_angle(record, transformed)
                else:
                    record["fourier_terms"] = [
                        {
                            "k_kcal_mol": float(item["k_kcal_mol"]),
                            "multiplicity": _fourier_multiplicity(item),
                            "delta_degrees": float(item["delta_degrees"]),
                        }
                        for item in transformed["fourier_terms"]
                    ]

    improper_by_atoms = {
        tuple(item["ordered_atoms_candidate"]): item
        for item in transform["bonded_terms"]["impropers"]
    }
    for record in workbook["bonded_terms"]["impropers_added"]:
        fitted_order = record["ordered_atoms_candidate"]
        transformed = improper_by_atoms.get(tuple(fitted_order))
        if transformed is None:
            raise ValueError(
                f"selected transform lacks improper {record['stereocenter']}"
            )
        ordered = fitted_order
        psi0 = float(transformed["psi0_degrees"])
        orientation_transform = "identity_with_bonded_type_aliases"
        record.update(
            ordering_candidate_status="quantitatively_screened_definition_order",
            ordered_atoms=ordered,
            types=types_for(ordered),
            source=json.dumps(
                {
                    "transform": _source(charmm_transform_path),
                    "fitted_order": fitted_order,
                    "patch_orientation_transform": orientation_transform,
                },
                sort_keys=True,
            ),
            emit_parameter=True,
            k_kcal_mol_rad2=float(transformed["k_kcal_mol_rad2"]),
            psi0_degrees=psi0,
        )
    removal_source = json.dumps(
        {
            "kind": "exact_precursor_THY_improper_removal",
            "fit_plan": _source(fit_plan_path),
            "policy": _source(policy_path),
        },
        sort_keys=True,
    )
    workbook["bonded_terms"]["impropers_removed"] = [
        {"ordered_atoms": atoms, "source": removal_source}
        for atoms in fit_plan["precursor_improper_removal_candidates"]
    ]
    workbook["charmm_patch"].update(
        {
            "patch_name": patch_name,
            "improper_removal_review": {
                "status": "reviewed",
                "source": removal_source,
                "authority": "automated_exact_THY_topology_and_definition_match",
            },
        }
    )
    fit_targets = _source(
        _checked(
            (fit_plan.get("sources") or {}).get("hessian_targets"), "Hessian targets"
        )
    )
    boundary_source = _source(dna_boundary_model_path)
    selected_source = _source(selected_path)
    workbook["required_qm_targets"] = {
        "optimized_minima_and_frequencies": [fit_targets],
        "dipole": [_source(nonbonded_fit_path)],
        "water_interactions": [_source(nonbonded_fit_path)],
        "hessian_or_internal_coordinate_response": [
            selected_source,
            _source(charmm_transform_path),
        ],
        "relaxed_torsion_surfaces": [
            {
                "status": "multi_conformer_response_substitute_for_smoke_only",
                "source": selected_source,
                "release_blocker_retained": True,
            }
        ],
        "independent_conformer_test_set": [selected_source],
    }
    workbook["fit_metadata"] = {
        "optimizer": "NADOC bounded linear response fit",
        "optimizer_version": "photoproduct-response-fit.v1",
        "objective_definition": selected_source,
        "train_test_split": selected_source,
        "regularization": selected_source,
        "convergence_report": selected_source,
    }
    workbook.update(
        {
            "release_status": "quantitative_smoke_candidate_not_released",
            "gate_effect": "none",
            "quantitative_candidate_assembly": {
                "schema": "nadoc.photoproduct-quantitative-candidate-assembly.v1",
                "status": "candidate_complete_requires_engine_and_solution_validation",
                "simulation_ready": False,
                "policy": _source(policy_path),
                "resolved_scope": scope,
                "nonbonded_checks": nonbonded_checks,
                "dna_boundary_model": boundary_source,
                "model_boundary_transfer": boundary_transfer,
                "candidate_authorization": policy["candidate_authorization"],
                "release_blockers_retained": policy["release_blockers_retained"],
            },
        }
    )
    output_path.write_text(json.dumps(workbook, indent=2) + "\n")
    return workbook
