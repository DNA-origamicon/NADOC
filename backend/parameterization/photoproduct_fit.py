"""Generate and audit fail-closed CHARMM photoproduct parameter workbooks.

The workbook is an explicit bridge between QM evidence and a releasable topology. It
starts with null final values and therefore cannot be mistaken for a force field. A
separate reviewer must populate sources, fit results, uncertainty, and validation before
the audit can pass.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from backend.core.photoproduct_chemistry import (
    chemical_definition_asset,
    load_chemical_definition,
    load_patch_charge_scope,
)
from backend.parameterization.photoproduct_terms import build_term_inventory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atom_sort_key(key: str) -> tuple[int, str]:
    endpoint, separator, name = key.partition(":")
    if separator and endpoint.isdigit():
        return int(endpoint), name
    return 99, key


_PATCH_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
_TYPE_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
_FF_DIR = Path(__file__).parents[1] / "data" / "forcefield"


def _standard_charmm_atom_types() -> set[str]:
    atom_types: set[str] = set()
    for path in (_FF_DIR / "top_all36_na.rtf", _FF_DIR / "top_all36_prot.rtf"):
        for raw in path.read_text(errors="replace").splitlines():
            fields = raw.split("!", 1)[0].split()
            if len(fields) >= 4 and fields[0].upper() == "MASS":
                atom_types.add(fields[2])
    return atom_types


def build_parameter_workbook(
    *,
    product: str,
    stereochemistry: str,
    output_path: Path,
    initial_charge_guess_path: Path | None = None,
) -> dict[str, Any]:
    """Write an unassigned, topology-complete fitting workbook.

    Existing CGenFF types/charges may be recorded as *initial guesses* only. Every final
    field remains null, and ``release_status`` is fixed to ``unassigned``.
    """

    definition = load_chemical_definition(product, stereochemistry)
    definition_asset = chemical_definition_asset(product, stereochemistry)
    inventory = build_term_inventory(product, stereochemistry)
    initial: dict[str, dict[str, Any]] = {}
    initial_record = None
    if initial_charge_guess_path is not None:
        payload = json.loads(initial_charge_guess_path.read_text())
        if (
            payload.get("schema") != "nadoc.photoproduct-initial-charge-guess.v1"
            or payload.get("product_id") != definition["id"]
        ):
            raise ValueError("initial charge guess does not match the photoproduct")
        initial = {item["model_atom"]: item for item in payload.get("atoms") or []}
        initial_record = {
            "path": str(initial_charge_guess_path.resolve()),
            "sha256": _sha256(initial_charge_guess_path),
        }

    # The patch changes the two bases, not their sugars.  C1' is retained in the
    # local connectivity so glycosidic bonded terms are audited, but including its
    # existing +0.16e charge in the product-base sum would make a neutral two-base
    # charge fit appear to require +0.32e.  The reviewed endpoint aliases define the
    # exact atom-conserving patch charge scope; neutral N-methyl caps are fitting-only.
    charge_scope = load_patch_charge_scope(product, stereochemistry)
    atoms = sorted(charge_scope["atoms_with_charges_replaced"], key=_atom_sort_key)
    local_atoms = {
        atom
        for bond in definition["precursor_local_connectivity"]["bonds"]
        for atom in bond
    }
    unchanged_boundary_atoms = sorted(
        charge_scope["unchanged_boundary_atoms"], key=_atom_sort_key
    )
    if set(atoms) | set(unchanged_boundary_atoms) != local_atoms:
        raise ValueError("patch charge scope does not partition the reviewed local graph")
    workbook = {
        "schema": "nadoc.photoproduct-parameter-workbook.v1",
        "product_id": definition["id"],
        "product": definition["product"],
        "stereochemistry": definition["stereochemistry"],
        "release_status": "unassigned",
        "gate_effect": "none",
        "forcefield_target": "CHARMM36 additive nucleic acid plus reviewed compatible lesion terms",
        "charge_constraints": definition["model_compounds"]["charge_model"].get(
            "charge_constraints", []
        ),
        "expected_model_charge": charge_scope["expected_pair_charge"],
        "charge_scope": {
            "patched_atoms": atoms,
            "unchanged_boundary_atoms": unchanged_boundary_atoms,
            "model_caps": charge_scope["model_caps"],
        },
        "charmm_patch": {
            "patch_name": None,
            "custom_atom_types": [],
            "boundary_atom_types": {
                atom: "CN7B" if atom.endswith(":C1'") else None
                for atom in unchanged_boundary_atoms
            },
            "improper_removal_review": {
                "status": "pending",
                "source": None,
            },
            "note": (
                "Declare every non-CHARMM36 atom type with mass, element, and "
                "Lennard-Jones values. Improper removals require explicit review of "
                "the precursor residue topology."
            ),
        },
        "initial_charge_guess": initial_record,
        "atoms": [
            {
                "atom": atom,
                "initial_source_type": initial.get(atom, {}).get("source_atom_type"),
                "initial_charge": initial.get(atom, {}).get("initial_charge"),
                "final_type": None,
                "final_charge": None,
                "charge_fit_source": None,
                "lj_source_or_fit": None,
            }
            for atom in atoms
        ],
        "bonded_terms": {
            "bonds": [
                {
                    "atoms": path,
                    "types": None,
                    "source": None,
                    "fit_targets": [],
                    "emit_parameter": None,
                    "k_kcal_mol_a2": None,
                    "r0_angstrom": None,
                }
                for path in inventory["all_local_terms_requiring_type_or_parameter_audit"][
                    "bonds"
                ]
            ],
            "angles": [
                {
                    "atoms": path,
                    "types": None,
                    "source": None,
                    "fit_targets": [],
                    "emit_parameter": None,
                    "k_kcal_mol_rad2": None,
                    "theta0_degrees": None,
                    "urey_bradley_k_kcal_mol_a2": None,
                    "urey_bradley_s0_angstrom": None,
                }
                for path in inventory["all_local_terms_requiring_type_or_parameter_audit"][
                    "angles"
                ]
            ],
            "dihedrals": [
                {
                    "atoms": path,
                    "types": None,
                    "source": None,
                    "fit_targets": [],
                    "emit_parameter": None,
                    "fourier_terms": [],
                }
                for path in inventory["all_local_terms_requiring_type_or_parameter_audit"][
                    "dihedrals"
                ]
            ],
            "impropers_added": [
                {
                    "stereocenter": center["atom"],
                    "expected_signed_volume": center["expected_signed_volume"],
                    "ordered_atoms_candidate": [
                        center["atom"],
                        *center["signed_volume_reference_atoms"],
                    ],
                    "ordering_candidate_source": definition_asset,
                    "ordering_candidate_status": "requires_product_specific_review",
                    "ordered_atoms": None,
                    "types": None,
                    "source": None,
                    "emit_parameter": None,
                    "k_kcal_mol_rad2": None,
                    "psi0_degrees": None,
                }
                for center in definition["product_stereocenters"]
            ],
            "impropers_removed": [],
        },
        "required_qm_targets": {
            "optimized_minima_and_frequencies": [],
            "dipole": [],
            "water_interactions": [],
            "hessian_or_internal_coordinate_response": [],
            "relaxed_torsion_surfaces": [],
            "independent_conformer_test_set": [],
        },
        "fit_metadata": {
            "optimizer": None,
            "optimizer_version": None,
            "objective_definition": None,
            "train_test_split": None,
            "regularization": None,
            "convergence_report": None,
        },
        "inventory_summary": {
            "changed_bond_orders": inventory["changed_bond_orders"],
            "newly_generated_counts": {
                key: len(value)
                for key, value in inventory["newly_generated_terms"].items()
            },
        },
        "release_rule": (
            "All final values, sources, QM targets, fit metadata, and stereochemical "
            "impropers must be populated and independently audited; this scaffold is not "
            "a simulation parameter set."
        ),
    }
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite parameter workbook: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(workbook, indent=2) + "\n")
    return workbook


def audit_parameter_workbook(workbook_path: Path) -> dict[str, Any]:
    """Check that a populated workbook is numerically and topologically complete.

    Passing this audit means only that the declared fit bundle is internally complete;
    it does not pass the parameter-fit or validation registry gates.
    """

    workbook = json.loads(workbook_path.read_text())
    if workbook.get("schema") != "nadoc.photoproduct-parameter-workbook.v1":
        raise ValueError("unsupported parameter workbook schema")
    errors: list[str] = []
    atoms = workbook.get("atoms") or []
    atom_keys = [item.get("atom") for item in atoms]
    if not atoms or len(atom_keys) != len(set(atom_keys)):
        errors.append("atom table is empty or contains duplicate stable atom keys")
    for atom in atoms:
        if not atom.get("final_type"):
            errors.append(f"{atom.get('atom')}: final atom type is missing")
        charge = atom.get("final_charge")
        if not isinstance(charge, (int, float)) or not math.isfinite(float(charge)):
            errors.append(f"{atom.get('atom')}: finite final charge is missing")
        if not atom.get("charge_fit_source"):
            errors.append(f"{atom.get('atom')}: charge fit source is missing")
        if not atom.get("lj_source_or_fit"):
            errors.append(f"{atom.get('atom')}: Lennard-Jones source/fit is missing")
    numeric_charges = [
        float(item["final_charge"])
        for item in atoms
        if isinstance(item.get("final_charge"), (int, float))
        and math.isfinite(float(item["final_charge"]))
    ]
    if len(numeric_charges) == len(atoms) and not math.isclose(
        sum(numeric_charges),
        float(workbook.get("expected_model_charge", 0.0)),
        abs_tol=1e-8,
    ):
        errors.append("final model charges do not sum to the required integer charge")

    patch = workbook.get("charmm_patch") or {}
    patch_name = patch.get("patch_name")
    if not isinstance(patch_name, str) or not _PATCH_NAME_RE.fullmatch(patch_name):
        errors.append("CHARMM patch name must be 1-8 uppercase alphanumeric characters")
    removal_review = patch.get("improper_removal_review") or {}
    if (
        removal_review.get("status") != "reviewed"
        or not removal_review.get("source")
    ):
        errors.append("precursor improper removals have not been explicitly reviewed")

    standard_types = _standard_charmm_atom_types()
    custom_records = patch.get("custom_atom_types") or []
    custom_by_name: dict[str, dict[str, Any]] = {}
    for record in custom_records:
        name = record.get("name") if isinstance(record, dict) else None
        if not isinstance(name, str) or not _TYPE_NAME_RE.fullmatch(name):
            errors.append(f"invalid custom CHARMM atom type name: {name!r}")
            continue
        if name in custom_by_name:
            errors.append(f"duplicate custom CHARMM atom type: {name}")
            continue
        custom_by_name[name] = record
        if name in standard_types:
            errors.append(f"custom atom type {name} collides with bundled CHARMM36")
        for field in ("mass_amu", "epsilon_kcal_mol", "rmin_half_angstrom"):
            value = record.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                errors.append(f"custom atom type {name}: {field} is missing")
        if isinstance(record.get("mass_amu"), (int, float)) and record["mass_amu"] <= 0:
            errors.append(f"custom atom type {name}: mass_amu must be positive")
        if (
            isinstance(record.get("epsilon_kcal_mol"), (int, float))
            and record["epsilon_kcal_mol"] > 0
        ):
            errors.append(f"custom atom type {name}: CHARMM epsilon must be non-positive")
        if (
            isinstance(record.get("rmin_half_angstrom"), (int, float))
            and record["rmin_half_angstrom"] <= 0
        ):
            errors.append(f"custom atom type {name}: Rmin/2 must be positive")
        if not record.get("element") or not record.get("source"):
            errors.append(f"custom atom type {name}: element/source is missing")
        epsilon_14 = record.get("epsilon_14_kcal_mol")
        rmin_14 = record.get("rmin_half_14_angstrom")
        if (epsilon_14 is None) != (rmin_14 is None):
            errors.append(f"custom atom type {name}: both 1-4 LJ values are required together")

    used_types = {item.get("final_type") for item in atoms if item.get("final_type")}
    missing_type_definitions = sorted(used_types - standard_types - set(custom_by_name))
    if missing_type_definitions:
        errors.append(
            "non-CHARMM36 atom types lack mass/LJ definitions: "
            + ", ".join(missing_type_definitions)
        )
    unused_custom_types = sorted(set(custom_by_name) - used_types)
    if unused_custom_types:
        errors.append("unused custom atom types: " + ", ".join(unused_custom_types))

    atom_by_key = {item.get("atom"): item for item in atoms}
    for endpoint in (1, 2):
        for atom_name, precursor_type in (("C5", "CN3T"), ("C6", "CN3")):
            key = f"{endpoint}:{atom_name}"
            if atom_by_key.get(key, {}).get("final_type") == precursor_type:
                errors.append(f"{key}: saturated product center retains reactant THY type")

    boundary_types = patch.get("boundary_atom_types")
    expected_boundary_atoms = set(workbook.get("charge_scope", {}).get("unchanged_boundary_atoms") or [])
    if not isinstance(boundary_types, dict) or set(boundary_types) != expected_boundary_atoms:
        errors.append("CHARMM boundary atom types do not exactly cover the unchanged boundary")
        boundary_types = {}
    elif any(not isinstance(value, str) or not value for value in boundary_types.values()):
        errors.append("one or more CHARMM boundary atom types are unassigned")

    def expected_types(record: dict[str, Any]) -> list[str | None]:
        return [
            atom_by_key.get(atom, {}).get("final_type") or boundary_types.get(atom)
            for atom in record.get("atoms") or record.get("ordered_atoms") or []
        ]

    def check_record_types(category: str, record: dict[str, Any]) -> None:
        declared = record.get("types")
        expected = expected_types(record)
        label = "-".join(record.get("atoms") or record.get("ordered_atoms") or [])
        if expected and (None in expected or declared != expected):
            errors.append(f"{category} {label}: types do not match atom/boundary assignments")

    bonded = workbook.get("bonded_terms") or {}
    required_fields = {
        "bonds": ("k_kcal_mol_a2", "r0_angstrom"),
        "angles": ("k_kcal_mol_rad2", "theta0_degrees"),
    }
    for category, fields in required_fields.items():
        records = bonded.get(category) or []
        if not records:
            errors.append(f"{category} table is empty")
        for record in records:
            label = "-".join(record.get("atoms") or [])
            if not record.get("types") or not record.get("source"):
                errors.append(f"{category} {label}: types/source are missing")
            if not isinstance(record.get("emit_parameter"), bool):
                errors.append(f"{category} {label}: emit_parameter review is missing")
            check_record_types(category, record)
            for field in fields:
                value = record.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    errors.append(f"{category} {label}: {field} is missing")
    for record in bonded.get("dihedrals") or []:
        label = "-".join(record.get("atoms") or [])
        if not record.get("types") or not record.get("source"):
            errors.append(f"dihedral {label}: types/source are missing")
        if not isinstance(record.get("emit_parameter"), bool):
            errors.append(f"dihedral {label}: emit_parameter review is missing")
        check_record_types("dihedral", record)
        terms = record.get("fourier_terms") or []
        if not terms:
            errors.append(f"dihedral {label}: Fourier terms are missing")
        for term in terms:
            for field in ("k_kcal_mol", "multiplicity", "delta_degrees"):
                value = term.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    errors.append(f"dihedral {label}: {field} is missing")
    impropers = bonded.get("impropers_added") or []
    if len(impropers) < 4:
        errors.append("fewer than four stereochemical impropers are declared")
    for record in impropers:
        label = record.get("stereocenter")
        if (
            not isinstance(record.get("ordered_atoms"), list)
            or len(record["ordered_atoms"]) != 4
            or not record.get("types")
            or not record.get("source")
        ):
            errors.append(f"improper {label}: ordered atoms/types/source are incomplete")
        if not isinstance(record.get("emit_parameter"), bool):
            errors.append(f"improper {label}: emit_parameter review is missing")
        check_record_types("improper", record)
        for field in ("k_kcal_mol_rad2", "psi0_degrees"):
            value = record.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                errors.append(f"improper {label}: {field} is missing")
    removed_impropers = bonded.get("impropers_removed")
    if not isinstance(removed_impropers, list):
        errors.append("impropers_removed must be an explicitly reviewed list")
    else:
        for record in removed_impropers:
            ordered = record.get("ordered_atoms") if isinstance(record, dict) else None
            if (
                not isinstance(ordered, list)
                or len(ordered) != 4
                or len(set(ordered)) != 4
                or not record.get("source")
            ):
                errors.append("removed improper atom order/source is incomplete")

    targets = workbook.get("required_qm_targets") or {}
    for category in (
        "optimized_minima_and_frequencies",
        "dipole",
        "water_interactions",
        "hessian_or_internal_coordinate_response",
        "relaxed_torsion_surfaces",
        "independent_conformer_test_set",
    ):
        if not targets.get(category):
            errors.append(f"required QM target set is empty: {category}")
    fit_metadata = workbook.get("fit_metadata") or {}
    for field in (
        "optimizer",
        "optimizer_version",
        "objective_definition",
        "train_test_split",
        "regularization",
        "convergence_report",
    ):
        if not fit_metadata.get(field):
            errors.append(f"fit metadata is missing: {field}")
    report = {
        "schema": "nadoc.photoproduct-parameter-workbook-audit.v1",
        "status": "complete_candidate" if not errors else "incomplete",
        "passed": not errors,
        "gate_effect": "none",
        "product_id": workbook.get("product_id"),
        "workbook_sha256": _sha256(workbook_path),
        "atom_count": len(atoms),
        "total_charge": sum(numeric_charges) if numeric_charges else None,
        "errors": errors,
        "release_note": (
            "An internally complete candidate still requires independent fit review, "
            "topology generation, real psfgen/NAMD tests, and solution validation."
        ),
    }
    report_path = workbook_path.with_name(workbook_path.stem + "_audit.json")
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite parameter audit: {report_path}")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
