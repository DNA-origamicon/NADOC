"""Pure validation and design-intent operations for manual TT-CPDs.

Geometry reported here describes the current *reactant* coordinates.  It is an
input to eventual product placement, never a stability filter and never proof
that a covalent product topology exists.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.core.base_keys import (
    ResolvedBase,
    atom_distance_nm,
    distance_nm,
    resolve_base_keys,
)
from backend.core.cpd_forcefield import cpd_capability
from backend.core.models import Design, PhotoproductJunction
from backend.core.photoproduct_registry import photoproduct_capability

PRODUCT = "TT-CPD"
DEFAULT_STEREOCHEMISTRY = "cis-syn"


def _error(code: str, message: str, *, key: str | None = None) -> dict[str, str]:
    out = {"code": code, "message": message}
    if key is not None:
        out["key"] = key
    return out


def _relationship(a: ResolvedBase, b: ResolvedBase) -> dict[str, Any]:
    same_strand = bool(a.strand_id and a.strand_id == b.strand_id)
    classes = [a.source_class, b.source_class]
    extra = [a.is_extra, b.is_extra]
    if all(extra):
        extra_pairing = "extra-extra"
    elif any(extra):
        extra_pairing = "extra-native"
    else:
        extra_pairing = "native-native"
    adjacent = False
    if same_strand and not any(extra):
        pa, pb = a.parsed, b.parsed
        adjacent = (
            pa.helix_id == pb.helix_id
            and pa.direction == pb.direction
            and pa.bp_index is not None
            and pb.bp_index is not None
            and abs(pa.bp_index - pb.bp_index) == 1
            and pa.copy == pb.copy == 0
        )
    return {
        "strand_relationship": "intrastrand" if same_strand else "interstrand",
        "same_strand": same_strand,
        "adjacent": adjacent,
        "extra_pairing": extra_pairing,
        "source_classes": classes,
    }


def preflight_photoproduct(
    design: Design,
    base_keys: list[str],
    *,
    stereochemistry: str = DEFAULT_STEREOCHEMISTRY,
    atomistic_model=None,
) -> dict[str, Any]:
    """Revalidate a proposed lesion against live design and atom provenance."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if len(base_keys) != 2:
        errors.append(
            _error("selection_count", "Exactly two nucleotide base keys are required.")
        )
    if len(base_keys) == 2 and base_keys[0] == base_keys[1]:
        errors.append(
            _error("duplicate_endpoint", "The two CPD endpoints must be distinct.")
        )
    try:
        registry_capability = photoproduct_capability(PRODUCT, stereochemistry)
    except KeyError:
        registry_capability = None
        errors.append(
            _error(
                "unsupported_stereochemistry",
                f"{stereochemistry!r} is not a registered TT-CPD stereoisomer.",
            )
        )

    candidate_keys = list(base_keys[:2]) if len(base_keys) >= 2 else list(base_keys)
    if (
        candidate_keys
        and registry_capability
        and registry_capability["simulation_ready"]
        and atomistic_model is None
    ):
        from backend.core.atomistic import build_atomistic_model

        atomistic_model = build_atomistic_model(design)
    resolved, resolve_errors = ([], [])
    if candidate_keys:
        resolved, resolve_errors = resolve_base_keys(
            design, candidate_keys, atomistic_model=atomistic_model, require_atoms=True
        )
    errors.extend(resolve_errors)
    resolved_by_key = {item.key: item for item in resolved}
    ordered_resolved = [
        resolved_by_key[key] for key in candidate_keys if key in resolved_by_key
    ]
    for endpoint in ordered_resolved:
        if endpoint.base != "T":
            errors.append(
                _error(
                    "endpoint_not_thymine",
                    f"Endpoint resolves to {endpoint.base or 'unknown'}, not thymine.",
                    key=endpoint.key,
                )
            )
        if not endpoint.has_cpd_atoms:
            errors.append(
                _error(
                    "missing_c5_c6",
                    "The production atomistic residue does not provide both C5 and C6.",
                    key=endpoint.key,
                )
            )

    consumed = {
        key: lesion.id
        for lesion in design.photoproduct_junctions
        for key in (lesion.base_key_1, lesion.base_key_2)
        if key
    }
    for key in candidate_keys:
        if key in consumed:
            errors.append(
                _error(
                    "endpoint_already_used",
                    f"Endpoint is already used by photoproduct {consumed[key]}.",
                    key=key,
                )
            )

    # Without a validated directional lesion template, do not pretend a geometry
    # score selected an assignment. Canonical ordering is explicit and deterministic,
    # but such intent must be recreated after a template is released before simulation.
    ordered_keys = (
        sorted(candidate_keys) if len(candidate_keys) == 2 else candidate_keys
    )
    if len(ordered_keys) == 2 and len(ordered_resolved) == 2:
        ordered_resolved = [resolved_by_key[key] for key in ordered_keys]
    orientation = {
        "base_key_1": ordered_keys[0] if len(ordered_keys) > 0 else None,
        "base_key_2": ordered_keys[1] if len(ordered_keys) > 1 else None,
        "patch_order": "base-key-1-first",
        "method": "canonical-key-order:parameters-unavailable",
        "template_evaluated": False,
    }
    relationship = (
        _relationship(*ordered_resolved) if len(ordered_resolved) == 2 else None
    )
    placement_report = None
    if (
        not errors
        and registry_capability
        and registry_capability["simulation_ready"]
        and atomistic_model is not None
        and len(ordered_resolved) == 2
    ):
        from backend.core.cpd_product import (
            ProductPlacementError,
            select_product_template_assignment,
        )
        from backend.core.photoproduct_chemistry import load_chemical_definition
        from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry

        entry = next(
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == registry_capability["id"]
        )
        template_record = entry["assets"]["coordinate_template"]
        template_path = (REGISTRY_PATH.parent / template_record["path"]).resolve()
        if (
            not template_path.is_file()
            or hashlib.sha256(template_path.read_bytes()).hexdigest()
            != template_record["sha256"]
        ):
            errors.append(
                _error(
                    "coordinate_template_changed",
                    "The released product coordinate template is missing or hash-mismatched.",
                )
            )
        else:
            try:
                selected, _preview, placement_report = (
                    select_product_template_assignment(
                        atomistic_model=atomistic_model,
                        endpoints=ordered_resolved,
                        template=json.loads(template_path.read_text()),
                        chemical_definition=load_chemical_definition(
                            PRODUCT, stereochemistry
                        ),
                        expected_parameter_sha256=entry["assets"]["parameters"][
                            "sha256"
                        ],
                    )
                )
            except ProductPlacementError as exc:
                placement_report = exc.report
                errors.append(
                    _error(
                        "product_placement_rejected",
                        "Neither directional product-template assignment passes the "
                        f"placement safety audit: {exc}",
                    )
                )
            else:
                ordered_resolved = selected
                ordered_keys = [item.key for item in selected]
                orientation = {
                    "base_key_1": ordered_keys[0],
                    "base_key_2": ordered_keys[1],
                    "patch_order": "base-key-1-first",
                    "method": "released-template-assignment-v1",
                    "template_evaluated": True,
                }
    geometry = None
    if len(ordered_resolved) == 2:
        candidate_bonds = []
        for pair in (registry_capability or {}).get("graph_delta", {}).get(
            "bonds_added", []
        ):
            first, second = pair.split("--", 1)
            first_endpoint, first_atom = first.split(":", 1)
            second_endpoint, second_atom = second.split(":", 1)
            endpoint_by_number = {"1": ordered_resolved[0], "2": ordered_resolved[1]}
            candidate_bonds.append(
                {
                    "atom_1": first,
                    "atom_2": second,
                    "distance_nm": atom_distance_nm(
                        endpoint_by_number[first_endpoint],
                        first_atom,
                        endpoint_by_number[second_endpoint],
                        second_atom,
                    ),
                }
            )
        geometry = {
            "state": "reactant",
            "interpretation": "placement input only; not a stability filter",
            "c5_c5_distance_nm": distance_nm(
                ordered_resolved[0], ordered_resolved[1], "C5"
            ),
            "c6_c6_distance_nm": distance_nm(
                ordered_resolved[0], ordered_resolved[1], "C6"
            ),
            "candidate_product_bond_distances": candidate_bonds,
        }

    legacy_capability = cpd_capability()
    simulation_ready = bool(
        not errors
        and registry_capability
        and registry_capability["simulation_ready"]
        and legacy_capability["available"]
    )
    if not simulation_ready:
        warnings.append(
            _error(
                "parameters_unavailable",
                f"The {stereochemistry} product intent can be saved, but coordinate conversion and every NAMD/export path are disabled until its complete validated CHARMM36 asset set passes every registry gate.",
            )
        )
    from backend.core.cpd_product import unavailable_placement_report

    if placement_report is None:
        placement_report = unavailable_placement_report(
            ordered_keys, geometry, stereochemistry=stereochemistry
        )

    return {
        "schema": "nadoc.photoproduct-preflight.v1",
        "eligible": not errors,
        "simulation_ready": simulation_ready,
        "product": PRODUCT,
        "stereochemistry": stereochemistry,
        "formation": "manual",
        "endpoints": [item.to_dict() for item in ordered_resolved],
        "relationship": relationship,
        "reactant_geometry": geometry,
        "placement_report": placement_report,
        "orientation": orientation,
        "errors": errors,
        "warnings": warnings,
        "chemistry_capability": registry_capability or legacy_capability,
    }


def create_photoproduct_from_preflight(
    design: Design, report: dict[str, Any]
) -> tuple[Design, PhotoproductJunction]:
    if not report.get("eligible"):
        messages = "; ".join(item["message"] for item in report.get("errors") or [])
        raise ValueError(messages or "Photoproduct preflight failed.")
    orientation = report["orientation"]
    lesion = PhotoproductJunction(
        base_key_1=orientation["base_key_1"],
        base_key_2=orientation["base_key_2"],
        product=PRODUCT,
        stereochemistry=report["stereochemistry"],
        formation="manual",
        patch_order=orientation["patch_order"],
        orientation_method=orientation["method"],
        photoproduct_id=PRODUCT,
    )
    return design.copy_with(
        photoproduct_junctions=[*design.photoproduct_junctions, lesion]
    ), lesion


def stale_photoproduct_ids(design: Design) -> list[str]:
    """Cheap dependency guard used after topology/sequence edits.

    Legacy scadnano-only records remain losslessly readable and are not silently
    deleted. Canonical records are stale if ownership disappears or either base
    ceases to be T. Atom availability is rechecked during preflight/simulation.
    """
    keys = [
        key
        for lesion in design.photoproduct_junctions
        for key in (lesion.base_key_1, lesion.base_key_2)
        if key
    ]
    resolved, errors = resolve_base_keys(design, keys, require_atoms=False)
    bad_keys = {item.get("key") for item in errors}
    bad_keys.update(item.key for item in resolved if item.base != "T")
    return [
        lesion.id
        for lesion in design.photoproduct_junctions
        if lesion.base_key_1 in bad_keys or lesion.base_key_2 in bad_keys
    ]
