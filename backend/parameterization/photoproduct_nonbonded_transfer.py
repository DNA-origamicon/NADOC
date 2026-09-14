"""Audit transfer of one TT-CPD nonbonded model across ordered products."""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
import re
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_nonbonded_fit import (
    _AU_DIPOLE_TO_DEBYE,
    _E_ANGSTROM_TO_DEBYE,
    _constraint_matrix,
    _interaction_row,
    _quadratic_grid_minimum,
    parse_charmm_nonbonded,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _pinned_nonbonded(
    cgenff_parameters_path: Path, nucleic_parameters_path: Path
) -> dict[str, dict[str, float]]:
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "data/forcefield/photoproduct_reference_forcefields.json"
    )
    manifest = json.loads(manifest_path.read_text())
    if (
        _sha256(cgenff_parameters_path)
        != manifest["cgenff_reference_library"]["parameters_sha256"]
        or _sha256(nucleic_parameters_path)
        != manifest["base_forcefield"]["parameters"]["sha256"]
    ):
        raise ValueError("nonbonded transfer requires the pinned CHARMM reference files")
    nonbonded = parse_charmm_nonbonded(cgenff_parameters_path)
    nucleic = parse_charmm_nonbonded(nucleic_parameters_path)
    conflicts = {
        key for key in set(nonbonded) & set(nucleic) if nonbonded[key] != nucleic[key]
    }
    if conflicts:
        raise ValueError("CGenFF and nucleic nonbonded records conflict")
    nonbonded.update(nucleic)
    return nonbonded


def summarize_transfer_metrics(
    records: Sequence[dict[str, float]],
    *,
    energy_target: float = 0.2,
    distance_target: float = 0.1,
) -> dict[str, Any]:
    if not records:
        raise ValueError("nonbonded transfer audit has no water sites")
    energy = np.asarray([float(item["energy_error_kcal_mol"]) for item in records])
    distance = np.asarray([float(item["distance_error_angstrom"]) for item in records])
    if not np.all(np.isfinite(energy)) or not np.all(np.isfinite(distance)):
        raise ValueError("nonbonded transfer metrics are non-finite")
    energy_rmse = float(np.sqrt(np.mean(energy**2)))
    distance_rmse = float(np.sqrt(np.mean(distance**2)))
    checks = {
        "water_interaction_energy_rmse": energy_rmse <= float(energy_target),
        "water_interaction_distance_rmse": distance_rmse <= float(distance_target),
    }
    return {
        "site_count": len(records),
        "energy_rmse_kcal_mol": energy_rmse,
        "distance_rmse_angstrom": distance_rmse,
        "maximum_absolute_energy_error_kcal_mol": float(np.max(np.abs(energy))),
        "maximum_absolute_distance_error_angstrom": float(np.max(np.abs(distance))),
        "targets": {
            "energy_rmse_kcal_mol": float(energy_target),
            "distance_rmse_angstrom": float(distance_target),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _evaluate_charge_model_against_collection(
    *,
    collection: dict[str, Any],
    atom_types: dict[str, str],
    charges_by_atom: dict[str, float],
    nonbonded: dict[str, dict[str, float]],
    objective: dict[str, Any],
    selected_product_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate an immutable charge/LJ model without fitting validation evidence."""

    missing_types = sorted(set(atom_types.values()) - set(nonbonded))
    if missing_types:
        raise ValueError("nonbonded types are absent: " + ", ".join(missing_types))
    selected = set(selected_product_ids or ())
    available = {
        str(item.get("product_id")) for item in collection.get("products") or []
    }
    if selected and not selected <= available:
        raise ValueError("requested validation product is absent from water collection")

    product_reports = []
    all_sites = []
    for product in collection.get("products") or []:
        product_id = str(product.get("product_id"))
        if selected and product_id not in selected:
            continue
        site_records = []
        for source_record in product.get("site_audits") or []:
            audit_path = Path(str(source_record.get("path") or ""))
            if not audit_path.is_file() or _sha256(audit_path) != source_record.get(
                "sha256"
            ):
                raise ValueError("water series audit is missing or hash-mismatched")
            audit = json.loads(audit_path.read_text())
            identity = audit.get("identity") or {}
            if (
                audit.get("schema")
                != "nadoc.photoproduct-water-interaction-series-audit.v1"
                or audit.get("passed") is not True
                or identity.get("product_id") != product_id
            ):
                raise ValueError("water series audit has stale identity")
            computed = []
            atom_map = None
            model_coordinates = None
            for point in audit.get("points") or []:
                job_dir = Path(str(point.get("job_dir") or ""))
                manifest_path = job_dir / "job_manifest.json"
                if not manifest_path.is_file() or _sha256(manifest_path) != point.get(
                    "job_manifest_sha256"
                ):
                    raise ValueError("water job manifest is missing or changed")
                job = json.loads(manifest_path.read_text())
                source_xyz = Path(job["source_xyz"]["path"])
                water_xyz = Path(job["water_xyz"]["path"])
                if (
                    _sha256(source_xyz) != job["source_xyz"]["sha256"]
                    or _sha256(water_xyz) != job["water_xyz"]["sha256"]
                ):
                    raise ValueError("water job coordinates are hash-mismatched")
                current_map = job["atom_map"]
                if set(current_map) != set(atom_types) or len(current_map) != len(
                    atom_types
                ):
                    raise ValueError("water atom map differs from the charge model")
                if atom_map is None:
                    atom_map = current_map
                elif atom_map != current_map:
                    raise ValueError("water series atom order changed")
                source_atoms, _ = parse_xyz(source_xyz.read_text())
                water_atoms, _ = parse_xyz(water_xyz.read_text())
                current_coordinates = np.asarray([item[1:] for item in source_atoms])
                if model_coordinates is None:
                    model_coordinates = current_coordinates
                elif not np.allclose(
                    model_coordinates, current_coordinates, atol=1.0e-10
                ):
                    raise ValueError("water series solute geometry changed")
                model_lj = [nonbonded[atom_types[key]] for key in atom_map]
                row, lj = _interaction_row(
                    current_coordinates,
                    model_lj,
                    np.asarray([item[1:] for item in water_atoms]),
                    nonbonded,
                )
                charges = np.asarray([float(charges_by_atom[key]) for key in atom_map])
                computed.append(
                    {
                        "distance_angstrom": float(point["distance_angstrom"]),
                        "mm_energy_kcal_mol": float(row @ charges + lj),
                    }
                )
            if len(computed) < 3:
                raise ValueError("water series lacks enough points for interpolation")
            distances = np.asarray([item["distance_angstrom"] for item in computed])
            energies = np.asarray([item["mm_energy_kcal_mol"] for item in computed])
            mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
            minimum_index = int(audit["minimum_point_index"])
            qm_minimum = audit["points"][minimum_index]
            target_distance = float(qm_minimum["distance_angstrom"]) + float(
                objective["water_distance_target_offset_angstrom"]
            )
            site = {
                "product_id": product_id,
                "site_id": identity["probe_id"],
                "qm_scaled_minimum_energy_kcal_mol": float(
                    qm_minimum["scaled_target_kcal_mol"]
                ),
                "mm_interpolated_minimum_energy_kcal_mol": mm_energy,
                "energy_error_kcal_mol": mm_energy
                - float(qm_minimum["scaled_target_kcal_mol"]),
                "target_offset_distance_angstrom": target_distance,
                "mm_interpolated_minimum_distance_angstrom": mm_distance,
                "distance_error_angstrom": mm_distance - target_distance,
                "source": _source(audit_path),
            }
            site_records.append(site)
            all_sites.append(site)
        if len(site_records) != 6:
            raise ValueError(f"{product_id}: expected six water sites")
        product_reports.append(
            {
                "product_id": product_id,
                "metrics": summarize_transfer_metrics(site_records),
                "sites": site_records,
            }
        )
    expected_count = len(selected) if selected else int(collection.get("product_count", -1))
    if len(product_reports) != expected_count or not product_reports:
        raise ValueError("water collection product inventory differs")
    return product_reports, summarize_transfer_metrics(all_sites)


def audit_nonbonded_transfer(
    *,
    source_fit_path: Path,
    water_collection_path: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
    hypothesis_id: str,
    output_path: Path,
) -> dict[str, Any]:
    """Evaluate an immutable charge/LJ hypothesis against independent product curves."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite nonbonded transfer audit: {output_path}")
    source_fit = json.loads(source_fit_path.read_text())
    collection = json.loads(water_collection_path.read_text())
    if (
        source_fit.get("schema")
        != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"
        or collection.get("schema")
        != "nadoc.photoproduct-alpine-water-collection.v1"
        or collection.get("status") != "passed_import_and_curve_audits"
        or collection.get("gate_effect") != "none"
    ):
        raise ValueError("nonbonded fit or water collection is invalid")
    hypothesis = next(
        (
            item
            for item in source_fit.get("results") or []
            if item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )
    if hypothesis is None:
        raise ValueError(f"nonbonded hypothesis is absent: {hypothesis_id}")
    atom_types = hypothesis["atom_types"]
    charges_by_atom = hypothesis["charges_e"]
    nonbonded = _pinned_nonbonded(cgenff_parameters_path, nucleic_parameters_path)
    objective = source_fit["objective"]
    product_reports, aggregate = _evaluate_charge_model_against_collection(
        collection=collection,
        atom_types=atom_types,
        charges_by_atom=charges_by_atom,
        nonbonded=nonbonded,
        objective=objective,
    )
    report = {
        "schema": "nadoc.photoproduct-nonbonded-transfer-audit.v1",
        "status": (
            "passed_shared_nonbonded_transfer_targets"
            if aggregate["passed"] and all(item["metrics"]["passed"] for item in product_reports)
            else "failed_shared_nonbonded_transfer_targets"
        ),
        "passed": aggregate["passed"]
        and all(item["metrics"]["passed"] for item in product_reports),
        "simulation_ready": False,
        "gate_effect": "none",
        "source_product_id": source_fit["product_id"],
        "hypothesis_id": hypothesis_id,
        "aggregate_metrics": aggregate,
        "products": product_reports,
        "sources": {
            "source_fit": _source(source_fit_path),
            "water_collection": _source(water_collection_path),
            "cgenff_parameters": _source(cgenff_parameters_path),
            "nucleic_parameters": _source(nucleic_parameters_path),
        },
        "interpretation": (
            "Independent fixed-geometry water-curve transfer test. Failure requires a "
            "new or joint nonbonded fit; passing does not release a force field."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_joint_nonbonded_candidate(
    *,
    candidate_path: Path,
    validation_collection_path: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Audit a fitted joint candidate on a strictly independent water collection."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite independent nonbonded validation: {output_path}"
        )
    candidate = json.loads(candidate_path.read_text())
    collection = json.loads(validation_collection_path.read_text())
    if (
        candidate.get("schema") != "nadoc.photoproduct-joint-nonbonded-fit.v1"
        or candidate.get("simulation_ready") is not False
        or candidate.get("gate_effect") != "none"
        or collection.get("schema")
        != "nadoc.photoproduct-alpine-water-collection.v1"
        or collection.get("status") != "passed_import_and_curve_audits"
        or collection.get("gate_effect") != "none"
    ):
        raise ValueError("candidate or independent water collection is invalid")

    candidate_sources = candidate.get("sources") or {}
    training_sources = candidate_sources.get("water_collections") or [
        candidate_sources.get("water_collection") or {}
    ]
    if not all(
        isinstance(item, dict)
        and item.get("sha256")
        and Path(str(item.get("path") or "")).is_file()
        and _sha256(Path(str(item["path"]))) == item["sha256"]
        for item in training_sources
    ):
        raise ValueError("candidate training water evidence is absent or hash-mismatched")
    validation_hash = _sha256(validation_collection_path)
    if validation_hash in {item["sha256"] for item in training_sources}:
        raise ValueError(
            "validation collection is identical to candidate training evidence"
        )
    source_fit_record = (candidate.get("sources") or {}).get("source_fit") or {}
    source_fit_path = Path(str(source_fit_record.get("path") or ""))
    if (
        not source_fit_path.is_file()
        or _sha256(source_fit_path) != source_fit_record.get("sha256")
    ):
        raise ValueError("candidate source fit is absent or hash-mismatched")
    source_fit = json.loads(source_fit_path.read_text())
    if source_fit.get("schema") != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1":
        raise ValueError("candidate source fit has an unsupported schema")

    atom_types = candidate.get("atom_types") or {}
    charges_by_atom = candidate.get("charges_e") or {}
    if not atom_types or set(atom_types) != set(charges_by_atom):
        raise ValueError("candidate charge/type atom identity is incomplete")
    selected_product_ids = set(candidate.get("product_ids") or [])
    if not selected_product_ids:
        raise ValueError("candidate has no selected product identities")
    nonbonded = _pinned_nonbonded(cgenff_parameters_path, nucleic_parameters_path)
    product_reports, aggregate = _evaluate_charge_model_against_collection(
        collection=collection,
        atom_types=atom_types,
        charges_by_atom=charges_by_atom,
        nonbonded=nonbonded,
        objective=source_fit["objective"],
        selected_product_ids=selected_product_ids,
    )
    passed = aggregate["passed"] and all(
        item["metrics"]["passed"] for item in product_reports
    )
    report = {
        "schema": "nadoc.photoproduct-independent-nonbonded-validation.v1",
        "status": (
            "candidate_passed_independent_water_targets"
            if passed
            else "candidate_failed_independent_water_targets"
        ),
        "passed": passed,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_ids": sorted(selected_product_ids),
        "candidate_training_status": candidate.get("status"),
        "aggregate_metrics": aggregate,
        "products": product_reports,
        "sources": {
            "candidate": _source(candidate_path),
            "candidate_training_collection": training_sources[0],
            "candidate_training_collections": training_sources,
            "validation_collection": _source(validation_collection_path),
            "source_fit": _source(source_fit_path),
            "cgenff_parameters": _source(cgenff_parameters_path),
            "nucleic_parameters": _source(nucleic_parameters_path),
        },
        "limitations": [
            "validation water curves were never included in this candidate fit",
            "Lennard-Jones types and values remain fixed to the pinned CHARMM references",
            "passing is necessary but does not release parameters or prove DNA transferability",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def fit_joint_nonbonded_transfer(
    *,
    source_fit_path: Path,
    water_collection_path: Path,
    frequency_root: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
    hypothesis_id: str,
    output_path: Path,
    product_ids: Sequence[str] | None = None,
    family_policy_path: Path | None = None,
    family_id: str | None = None,
    additional_water_collection_paths: Sequence[Path] | None = None,
    fit_all_water_sites: bool = False,
) -> dict[str, Any]:
    """Fit one charge vector to all new products, retaining independent endpoints.

    Endpoint-1 curves are training observations and endpoint-2 curves are held out,
    matching the preregistered cis-syn fitting policy.  All product dipoles contribute
    to the fit.  The result is a comparison candidate, never a released parameter set.
    """

    from scipy import __version__ as scipy_version
    from scipy.linalg import null_space
    from scipy.optimize import least_squares

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite joint nonbonded fit: {output_path}")
    source_fit = json.loads(source_fit_path.read_text())
    collection_paths = [
        water_collection_path.resolve(),
        *(path.resolve() for path in (additional_water_collection_paths or [])),
    ]
    if len({_sha256(path) for path in collection_paths}) != len(collection_paths):
        raise ValueError("joint-fit water collections must be hash-distinct")
    collections = [json.loads(path.read_text()) for path in collection_paths]
    if fit_all_water_sites and len(collections) < 2:
        raise ValueError(
            "fit-all-water-sites requires at least two training orientations"
        )
    collection = copy.deepcopy(collections[0])
    hypothesis = next(
        (
            item
            for item in source_fit.get("results") or []
            if item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )
    if (
        source_fit.get("schema")
        != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"
        or any(
            item.get("schema")
            != "nadoc.photoproduct-alpine-water-collection.v1"
            or item.get("status") != "passed_import_and_curve_audits"
            or item.get("gate_effect") != "none"
            for item in collections
        )
        or hypothesis is None
    ):
        raise ValueError("joint nonbonded inputs are invalid")
    product_sets = [
        {str(item.get("product_id")) for item in current.get("products") or []}
        for current in collections
    ]
    if any(current != product_sets[0] for current in product_sets[1:]):
        raise ValueError("joint-fit water collection product inventories differ")
    merged_products = {
        str(item["product_id"]): item for item in collection.get("products") or []
    }
    for current in collections[1:]:
        for product in current.get("products") or []:
            merged_products[str(product["product_id"])]["site_audits"].extend(
                copy.deepcopy(product.get("site_audits") or [])
            )
    charge_source = (source_fit.get("source_records") or {}).get("charge_targets") or {}
    charge_path = Path(str(charge_source.get("path") or ""))
    if not charge_path.is_file() or _sha256(charge_path) != charge_source.get("sha256"):
        raise ValueError("source charge-target bundle is absent or hash-mismatched")
    charge_bundle = json.loads(charge_path.read_text())
    atom_map = charge_bundle["atom_map"]
    initial_by_atom = {
        item["model_atom"]: float(item["initial_charge"])
        for item in charge_bundle["initial_charges"]
    }
    initial = np.asarray([initial_by_atom[key] for key in atom_map])
    source_charges = np.asarray([float(hypothesis["charges_e"][key]) for key in atom_map])
    fit_constraints = copy.deepcopy(charge_bundle["constraints"])
    training_suffixes = None
    heldout_suffixes = None
    family_policy_source = None
    endpoint_charge_symmetry = "endpoint_exchange_equivalent"
    if (family_policy_path is None) != (family_id is None):
        raise ValueError("family policy and family id must be supplied together")
    if family_policy_path is not None:
        family_policy = json.loads(family_policy_path.read_text())
        family = (family_policy.get("families") or {}).get(str(family_id))
        if (
            family_policy.get("schema")
            != "nadoc.photoproduct-nonbonded-family-fit-policy.v1"
            or family_policy.get("status") != "workflow_policy"
            or family_policy.get("gate_effect") != "none"
            or not isinstance(family, dict)
            or set(family.get("product_ids") or []) != set(product_ids or [])
        ):
            raise ValueError("nonbonded family policy or selected identity is invalid")
        endpoint_charge_symmetry = family.get("endpoint_charge_symmetry")
        if endpoint_charge_symmetry != "ordered_distinct":
            raise ValueError("unsupported endpoint charge-symmetry policy")
        training_suffixes = set(family.get("training_site_suffixes") or [])
        heldout_suffixes = set(family.get("held_out_site_suffixes") or [])
        if not training_suffixes or not heldout_suffixes or training_suffixes & heldout_suffixes:
            raise ValueError("nonbonded family site split is invalid")
        fit_constraints["equal_charge_groups"] = [
            group
            for group in fit_constraints["equal_charge_groups"]
            if len({str(atom).split(":", 1)[0] for atom in group}) == 1
        ]
        family_policy_source = _source(family_policy_path)
    constraints, constraint_values = _constraint_matrix(atom_map, fit_constraints)
    particular, *_ = np.linalg.lstsq(constraints, constraint_values, rcond=None)
    null = null_space(constraints)
    start, *_ = np.linalg.lstsq(null, source_charges - particular, rcond=None)

    nonbonded = _pinned_nonbonded(cgenff_parameters_path, nucleic_parameters_path)
    model_lj = [nonbonded[hypothesis["atom_types"][key]] for key in atom_map]
    objective = source_fit["objective"]
    energy_sigma = float(objective["water_energy_sigma_kcal_mol"])
    dipole_sigma = float(objective["dipole_component_sigma_debye"])
    charge_sigma = float(objective["initial_charge_restraint_sigma_e"])
    distance_sigma = 0.2

    selected_ids = set(product_ids or [])
    available_ids = {
        str(item.get("product_id")) for item in collection.get("products") or []
    }
    if selected_ids and not selected_ids <= available_ids:
        raise ValueError("requested joint-fit product is absent from water collection")
    products = []
    for product in collection.get("products") or []:
        product_id = product["product_id"]
        if selected_ids and product_id not in selected_ids:
            continue
        curve_records = []
        model_coordinates = None
        for source_record in product.get("site_audits") or []:
            audit_path = Path(source_record["path"])
            if _sha256(audit_path) != source_record["sha256"]:
                raise ValueError("joint-fit water audit hash differs")
            audit = json.loads(audit_path.read_text())
            identity = audit["identity"]
            points = []
            for point in audit["points"]:
                job_path = Path(point["job_dir"]) / "job_manifest.json"
                if _sha256(job_path) != point["job_manifest_sha256"]:
                    raise ValueError("joint-fit water job hash differs")
                job = json.loads(job_path.read_text())
                if job["atom_map"] != atom_map:
                    raise ValueError("joint-fit water atom order differs")
                source_xyz = Path(job["source_xyz"]["path"])
                water_xyz = Path(job["water_xyz"]["path"])
                if (
                    _sha256(source_xyz) != job["source_xyz"]["sha256"]
                    or _sha256(water_xyz) != job["water_xyz"]["sha256"]
                ):
                    raise ValueError("joint-fit water geometry hash differs")
                source_atoms, _ = parse_xyz(source_xyz.read_text())
                water_atoms, _ = parse_xyz(water_xyz.read_text())
                coordinates = np.asarray([item[1:] for item in source_atoms])
                if model_coordinates is None:
                    model_coordinates = coordinates
                elif not np.allclose(model_coordinates, coordinates, atol=1.0e-10):
                    raise ValueError("joint-fit product geometry changed between curves")
                row, lj = _interaction_row(
                    coordinates,
                    model_lj,
                    np.asarray([item[1:] for item in water_atoms]),
                    nonbonded,
                )
                points.append(
                    {
                        "distance_angstrom": float(point["distance_angstrom"]),
                        "charge_row": row,
                        "lj_kcal_mol": lj,
                    }
                )
            minimum = audit["points"][int(audit["minimum_point_index"])]
            probe_id = identity["probe_id"]
            if fit_all_water_sites:
                split = "training"
            elif training_suffixes is None:
                split = "training" if probe_id.startswith("endpoint1-") else "held_out"
            else:
                base_probe_id = re.sub(
                    r"-(?:alt-plane|azimuth-[+-]\d+)$", "", probe_id
                )
                matching_training = [
                    suffix
                    for suffix in training_suffixes
                    if base_probe_id.endswith(suffix)
                ]
                matching_heldout = [
                    suffix
                    for suffix in heldout_suffixes
                    if base_probe_id.endswith(suffix)
                ]
                if (len(matching_training), len(matching_heldout)) not in {(1, 0), (0, 1)}:
                    raise ValueError(f"{probe_id}: family site split is incomplete or ambiguous")
                split = "training" if matching_training else "held_out"
            curve_records.append(
                {
                    "site_id": probe_id,
                    "split": split,
                    "points": points,
                    "qm_energy_kcal_mol": float(minimum["scaled_target_kcal_mol"]),
                    "target_distance_angstrom": float(minimum["distance_angstrom"])
                    + float(objective["water_distance_target_offset_angstrom"]),
                    "source": _source(audit_path),
                }
            )
        if model_coordinates is None or len(curve_records) != 6 * len(collections):
            raise ValueError(f"{product_id}: joint-fit product evidence is incomplete")
        frequency_dir = frequency_root / product_id
        run_path = frequency_dir / "run_manifest.json"
        result_path = frequency_dir / "distributed_qcschema_result.json"
        run = json.loads(run_path.read_text())
        expected_result = (run.get("outputs") or {}).get(
            "distributed_qcschema_result.json"
        ) or {}
        if not result_path.is_file() or _sha256(result_path) != expected_result.get("sha256"):
            raise ValueError(f"{product_id}: frequency result is absent or hash-mismatched")
        frequency = json.loads(result_path.read_text())
        dipole = (((frequency.get("extras") or {}).get("findif_record") or {}).get("reference") or {}).get("dipole")
        if not isinstance(dipole, list) or len(dipole) != 3:
            raise ValueError(f"{product_id}: reference QM dipole is absent")
        products.append(
            {
                "product_id": product_id,
                "coordinates": model_coordinates,
                "qm_dipole_au": np.asarray(dipole, dtype=float),
                "curves": curve_records,
                "frequency_result": _source(result_path),
            }
        )
    expected_count = len(selected_ids) if selected_ids else 6
    if len(products) != expected_count or not products:
        raise ValueError("joint fit product inventory is incomplete")

    def residual(reduced: np.ndarray) -> np.ndarray:
        charges = particular + null @ reduced
        values = []
        for product in products:
            for curve in product["curves"]:
                if curve["split"] != "training":
                    continue
                distances = np.asarray(
                    [item["distance_angstrom"] for item in curve["points"]]
                )
                energies = np.asarray(
                    [
                        float(item["charge_row"] @ charges + item["lj_kcal_mol"])
                        for item in curve["points"]
                    ]
                )
                mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
                values.extend(
                    [
                        (mm_energy - curve["qm_energy_kcal_mol"]) / energy_sigma,
                        (mm_distance - curve["target_distance_angstrom"])
                        / distance_sigma,
                    ]
                )
            mm_dipole = (
                charges @ product["coordinates"] * _E_ANGSTROM_TO_DEBYE
            )
            qm_dipole = (
                product["qm_dipole_au"]
                * _AU_DIPOLE_TO_DEBYE
                * float(objective["qm_dipole_scale"])
            )
            values.extend(((mm_dipole - qm_dipole) / dipole_sigma).tolist())
        values.extend(((charges - initial) / charge_sigma).tolist())
        return np.asarray(values)

    optimized = least_squares(
        residual,
        start,
        method="trf",
        xtol=1.0e-12,
        ftol=1.0e-12,
        gtol=1.0e-12,
        max_nfev=5000,
    )
    charges = particular + null @ optimized.x
    product_reports = []
    all_training = []
    all_held_out = []
    dipole_errors = []
    for product in products:
        sites = []
        for curve in product["curves"]:
            distances = np.asarray(
                [item["distance_angstrom"] for item in curve["points"]]
            )
            energies = np.asarray(
                [
                    float(item["charge_row"] @ charges + item["lj_kcal_mol"])
                    for item in curve["points"]
                ]
            )
            mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
            site = {
                "site_id": curve["site_id"],
                "split": curve["split"],
                "energy_error_kcal_mol": mm_energy - curve["qm_energy_kcal_mol"],
                "distance_error_angstrom": mm_distance
                - curve["target_distance_angstrom"],
                "source": curve["source"],
            }
            sites.append(site)
            (all_training if site["split"] == "training" else all_held_out).append(
                site
            )
        mm_dipole = charges @ product["coordinates"] * _E_ANGSTROM_TO_DEBYE
        qm_dipole = (
            product["qm_dipole_au"]
            * _AU_DIPOLE_TO_DEBYE
            * float(objective["qm_dipole_scale"])
        )
        dipole_error = float(np.linalg.norm(mm_dipole - qm_dipole))
        dipole_errors.append(dipole_error)
        product_reports.append(
            {
                "product_id": product["product_id"],
                "training_metrics": summarize_transfer_metrics(
                    [item for item in sites if item["split"] == "training"]
                ),
                "held_out_metrics": (
                    summarize_transfer_metrics(
                        [item for item in sites if item["split"] == "held_out"]
                    )
                    if not fit_all_water_sites
                    else None
                ),
                "dipole_vector_error_debye": dipole_error,
                "sites": sites,
                "frequency_result": product["frequency_result"],
            }
        )
    training_metrics = summarize_transfer_metrics(all_training)
    heldout_metrics = (
        summarize_transfer_metrics(all_held_out) if not fit_all_water_sites else None
    )
    training_fit_passed = training_metrics["passed"] and all(
        item["training_metrics"]["passed"] for item in product_reports
    )
    passed = bool(
        heldout_metrics
        and heldout_metrics["passed"]
        and all(item["held_out_metrics"]["passed"] for item in product_reports)
    )
    report = {
        "schema": "nadoc.photoproduct-joint-nonbonded-fit.v1",
        "status": (
            "candidate_pending_independent_water_validation"
            if fit_all_water_sites and training_fit_passed
            else (
                "candidate_failed_multi_orientation_training_targets"
                if fit_all_water_sites
                else (
                    "candidate_passed_heldout_water_targets"
                    if passed
                    else "candidate_failed_heldout_water_targets"
                )
            )
        ),
        "passed": passed,
        "fit_completed": bool(optimized.success) and training_fit_passed,
        "fit_all_water_sites": fit_all_water_sites,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_ids": [item["product_id"] for item in products],
        "hypothesis_id": hypothesis_id,
        "family_id": family_id,
        "endpoint_charge_symmetry": endpoint_charge_symmetry,
        "atom_types": hypothesis["atom_types"],
        "charges_e": dict(zip(atom_map, charges.tolist(), strict=True)),
        "maximum_constraint_error_e": float(
            np.max(np.abs(constraints @ charges - constraint_values))
        ),
        "maximum_charge_change_from_initial_e": float(
            np.max(np.abs(charges - initial))
        ),
        "maximum_charge_change_from_source_fit_e": float(
            np.max(np.abs(charges - source_charges))
        ),
        "training_metrics": training_metrics,
        "held_out_metrics": heldout_metrics,
        "maximum_dipole_vector_error_debye": max(dipole_errors),
        "products": product_reports,
        "solver": {
            "optimizer": "scipy.optimize.least_squares/trf",
            "scipy_version": scipy_version,
            "success": bool(optimized.success),
            "status": int(optimized.status),
            "message": str(optimized.message),
            "function_evaluations": int(optimized.nfev),
            "cost": float(optimized.cost),
            "optimality": float(optimized.optimality),
            "constraint_rank": int(np.linalg.matrix_rank(constraints)),
            "independent_charge_variables": int(null.shape[1]),
        },
        "sources": {
            "source_fit": _source(source_fit_path),
            "source_charge_targets": _source(charge_path),
            "water_collection": _source(water_collection_path),
            "water_collections": [_source(path) for path in collection_paths],
            "cgenff_parameters": _source(cgenff_parameters_path),
            "nucleic_parameters": _source(nucleic_parameters_path),
            "family_policy": family_policy_source,
        },
        "limitations": [
            "selected-product shared-charge comparison; excluded products remain external checks",
            (
                "all sites in the listed orientations enter training; only a hash-distinct collection can validate this candidate"
                if fit_all_water_sites
                else "endpoint-2 curves are held out across every training orientation but all product dipoles enter training"
            ),
            "a passing comparison does not release parameters",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
