"""Promote selected transferable CHARMM terms into a coupled refit basis.

The initial photoproduct workflow fitted only parameter signatures absent from the
pinned CHARMM/CGenFF bundle.  That is useful for a first engine smoke, but it leaves a
generic cyclobutane ring block untouched.  This module makes replacement explicit and
hash-auditable: selected covered terms are removed from the transfer list and become
null-valued fit groups.  It assigns no parameter value and advances no release gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_REFIT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_bonded_refit_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _canonical_types(types: list[str]) -> tuple[str, ...]:
    forward = tuple(types)
    reverse = tuple(reversed(types))
    return min(forward, reverse)


def _variables(category: str) -> dict[str, Any]:
    if category == "bonds":
        return {"k_kcal_mol_a2": None, "r0_angstrom": None}
    if category == "angles":
        return {
            "k_kcal_mol_rad2": None,
            "theta0_degrees": None,
            "urey_bradley_k_kcal_mol_a2": None,
            "urey_bradley_s0_angstrom": None,
        }
    if category == "dihedrals":
        return {"fourier_terms": None}
    raise ValueError(f"unsupported promoted category: {category!r}")


def promote_bonded_fit_terms(
    *,
    fit_plan_path: Path,
    output_path: Path,
    policy_path: Path = DEFAULT_REFIT_POLICY_PATH,
) -> dict[str, Any]:
    """Create a gate-neutral fit plan in which the complete ring block is fitted.

    Selection is based on stable atom identities, never transient atom indices or type
    names.  The policy's expected counts make a changed graph or incomplete promotion
    fail before an OpenMM basis can be generated.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite promoted fit plan: {output_path}")
    fit_plan = json.loads(fit_plan_path.read_text())
    policy = json.loads(policy_path.read_text())
    if (
        fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or fit_plan.get("gate_effect") != "none"
    ):
        raise ValueError("input is not a gate-neutral bonded fit plan")
    schema = policy.get("schema")
    if schema == "nadoc.photoproduct-bonded-refit-policy.v1":
        identity_allowed = policy.get("product_id") == fit_plan.get("product_id")
    elif schema == "nadoc.photoproduct-bonded-refit-policy.v2":
        allowed = policy.get("allowed_product_ids") or []
        identity_allowed = (
            fit_plan.get("product_id") in allowed
            and len(allowed) == 8
            and len(set(allowed)) == len(allowed)
        )
    else:
        identity_allowed = False
    if policy.get("status") != "workflow_policy" or not identity_allowed:
        raise ValueError("bonded refit policy and fit-plan identity differ")

    selection = policy.get("selection") or {}
    ring_atoms = selection.get("stable_ring_atoms") or []
    categories = selection.get("categories") or []
    expected_counts = selection.get("expected_occurrence_counts") or {}
    if (
        len(ring_atoms) != 4
        or len(set(ring_atoms)) != 4
        or set(categories) != {"bonds", "angles", "dihedrals"}
        or set(expected_counts) != set(categories)
        or any(
            isinstance(expected_counts[category], bool)
            or not isinstance(expected_counts[category], int)
            or expected_counts[category] < 1
            for category in categories
        )
        or selection.get("allow_partial_ring_promotion") is not False
    ):
        raise ValueError("bonded refit selection policy is incomplete")
    ring_atom_set = set(ring_atoms)

    selected: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    for record in fit_plan.get("transfer_candidates") or []:
        atoms = record.get("atoms") or []
        if record.get("category") in categories and atoms and set(atoms) <= ring_atom_set:
            selected.append(record)
        else:
            retained.append(record)
    observed_counts = {
        category: sum(record["category"] == category for record in selected)
        for category in categories
    }
    if observed_counts != expected_counts:
        raise ValueError(
            "complete ring-block promotion count differs from policy: "
            f"observed={observed_counts}, expected={expected_counts}"
        )

    grouped: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for record in selected:
        occurrence = {
            "atoms": record["atoms"],
            "observed_coordinate": record["observed_coordinate"],
            "coordinate_unit": record["coordinate_unit"],
            "promoted_from_coverage": record["coverage"],
            "replaced_parameter_matches": record["matches"],
        }
        for name in (
            "central_bond",
            "central_bond_order",
            "central_bond_in_cycle",
            "target_class",
        ):
            if name in record:
                occurrence[name] = record[name]
        key = (record["category"], _canonical_types(record["types"]))
        grouped.setdefault(key, []).append(occurrence)

    existing_ids = {
        group.get("id") for group in fit_plan.get("uncovered_parameter_groups") or []
    }
    promoted_groups = []
    for (category, types), occurrences in sorted(grouped.items()):
        group_id = f"refit:{category}:{'-'.join(types)}"
        if group_id in existing_ids:
            raise ValueError(f"promoted fit group collides with existing group: {group_id}")
        promoted_groups.append(
            {
                "id": group_id,
                "category": category,
                "canonical_types": list(types),
                "occurrences": occurrences,
                "variables": _variables(category),
                "status": "unassigned_refit_required",
                "parameter_origin": "promoted_pinned_transfer",
                "additional_target_requirement": (
                    "coupled_ring_hessians_multiple_conformers_and_mm_minimum"
                ),
            }
        )

    result = dict(fit_plan)
    result["transfer_candidates"] = retained
    result["uncovered_parameter_groups"] = [
        *(fit_plan.get("uncovered_parameter_groups") or []),
        *promoted_groups,
    ]
    result["promoted_transfer_candidates"] = selected
    result["bonded_refit"] = {
        "schema": "nadoc.photoproduct-bonded-refit.v1",
        "status": "complete_ring_block_promoted_unassigned",
        "variant_family": policy["variant_family"],
        "selection_rule": selection["rule"],
        "stable_ring_atoms": ring_atoms,
        "occurrence_counts": observed_counts,
        "group_count": len(promoted_groups),
        "generic_values_retained_as_fit_values": False,
        "generic_values_retained_as_provenance_only": True,
    }
    result["sources"] = {
        **(fit_plan.get("sources") or {}),
        "parent_fit_plan": _source(fit_plan_path),
        "bonded_refit_policy": _source(policy_path),
    }
    result["release_blockers"] = [
        *(fit_plan.get("release_blockers") or []),
        "fit and validate the promoted complete cyclobutane ring block",
        "compare the corrected MM minimum and dynamics with QM, 1N4E, and the Ma/van der Vaart benchmark",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result
