"""Chemical-definition loading and stereochemistry audits for photoproducts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validated_definition(
    raw: object,
    *,
    expected_id: str,
    expected_product: str,
    expected_stereochemistry: str,
) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != "nadoc.photoproduct-chemical-definition.v1"
    ):
        raise ValueError("unsupported photoproduct chemical-definition schema")
    if (
        raw.get("id") != expected_id
        or raw.get("product") != expected_product
        or raw.get("stereochemistry") != expected_stereochemistry
    ):
        raise ValueError("chemical-definition product identity does not match registry")
    endpoints = raw.get("ordered_endpoints")
    if not isinstance(endpoints, list) or [item.get("index") for item in endpoints] != [1, 2]:
        raise ValueError("chemical definition requires ordered endpoints 1 and 2")
    for endpoint in endpoints:
        aliases = endpoint.get("ccd_atom_aliases")
        if not isinstance(aliases, dict) or not {"N1", "C5", "C6"}.issubset(aliases):
            raise ValueError("each endpoint requires N1/C5/C6 atom aliases")
        if len(aliases.values()) != len(set(aliases.values())):
            raise ValueError("endpoint CCD atom aliases must be unique")
    graph = raw.get("graph_delta")
    if not isinstance(graph, dict):
        raise ValueError("chemical definition requires a graph_delta")
    if (
        not isinstance(graph.get("atoms_added"), list)
        or not isinstance(graph.get("atoms_removed"), list)
        or not isinstance(graph.get("formal_charge_change"), int)
    ):
        raise ValueError(
            "graph_delta requires atom-add/remove lists and an integer charge change"
        )
    for name in ("bonds_added", "bonds_retained"):
        if not isinstance(graph.get(name), list) or not graph[name]:
            raise ValueError(f"graph_delta requires non-empty {name}")
        for bond in graph[name]:
            if not all(isinstance(bond.get(key), str) for key in ("atom_1", "atom_2")):
                raise ValueError(f"malformed graph bond in {name}")
            if bond["atom_1"] == bond["atom_2"]:
                raise ValueError(f"self bond in graph_delta {name}")
        identities = [
            frozenset((bond["atom_1"], bond["atom_2"])) for bond in graph[name]
        ]
        if len(identities) != len(set(identities)):
            raise ValueError(f"duplicate graph bond in {name}")
    coordinates = raw.get("source_ring_coordinates_angstrom")
    centers = raw.get("product_stereocenters")
    if not isinstance(coordinates, dict) or not isinstance(centers, list) or not centers:
        raise ValueError("definition requires source coordinates and stereocenters")
    for center in centers:
        keys = [center.get("atom"), *(center.get("signed_volume_reference_atoms") or [])]
        if len(keys) != 4 or any(key not in coordinates for key in keys):
            raise ValueError("stereocenter signed-volume atoms are missing coordinates")
        if center.get("expected_signed_volume") not in {"positive", "negative"}:
            raise ValueError("stereocenter expected sign must be positive or negative")
    assets = raw.get("source_assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("chemical definition requires immutable source_assets")
    asset_ids = [asset.get("id") for asset in assets]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("source asset IDs must be unique")
    for asset in assets:
        if (
            not all(asset.get(key) for key in ("id", "url", "filename", "license"))
            or not _SHA256_RE.fullmatch(str(asset.get("sha256") or ""))
        ):
            raise ValueError("source asset provenance is incomplete")
    return raw


def validate_chemical_definition_document(
    raw: object,
    *,
    expected_id: str,
    expected_product: str,
    expected_stereochemistry: str,
) -> dict[str, Any]:
    """Validate an unattached released chemical-definition document.

    This is intentionally separate from :func:`load_chemical_definition`: human-review
    ingestion has to validate a proposed, hash-pinned release before it is copied into
    the force-field tree or attached to the registry.
    """

    return _validated_definition(
        raw,
        expected_id=expected_id,
        expected_product=expected_product,
        expected_stereochemistry=expected_stereochemistry,
    )


def chemical_definition_asset(
    product: str, stereochemistry: str, *, registry_path: Path = REGISTRY_PATH
) -> dict[str, str]:
    registry = photoproduct_registry(registry_path)
    entry = next(
        (
            item
            for item in registry["products"]
            if item["product"] == product
            and item["stereochemistry"] == stereochemistry
        ),
        None,
    )
    if entry is None:
        raise KeyError(f"unregistered photoproduct: {product}/{stereochemistry}")
    record = (entry.get("assets") or {}).get("chemical_definition")
    if not isinstance(record, dict) or not record.get("path"):
        raise FileNotFoundError(
            f"chemical definition is not available for {product}/{stereochemistry}"
        )
    path = (registry_path.parent / record["path"]).resolve()
    path.relative_to(registry_path.parent.resolve())
    if not path.is_file():
        raise FileNotFoundError(f"chemical definition asset is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != record.get("sha256"):
        raise ValueError(
            f"chemical definition hash mismatch for {product}/{stereochemistry}"
        )
    return {"path": str(path), "sha256": actual}


def load_chemical_definition(
    product: str, stereochemistry: str, *, registry_path: Path = REGISTRY_PATH
) -> dict[str, Any]:
    asset = chemical_definition_asset(
        product, stereochemistry, registry_path=registry_path
    )
    path = Path(asset["path"])
    registry = photoproduct_registry(registry_path)
    entry = next(
        item
        for item in registry["products"]
        if item["product"] == product
        and item["stereochemistry"] == stereochemistry
    )
    return _validated_definition(
        json.loads(path.read_text()),
        expected_id=entry["id"],
        expected_product=product,
        expected_stereochemistry=stereochemistry,
    )


def chemical_definition_registry_graph(
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the compact, ordered graph identity stored in the registry."""

    graph = definition["graph_delta"]
    return {
        "atoms_added": len(graph["atoms_added"]),
        "atoms_removed": len(graph["atoms_removed"]),
        "formal_charge_change": graph["formal_charge_change"],
        "bonds_added": [
            f"{bond['atom_1']}--{bond['atom_2']}" for bond in graph["bonds_added"]
        ],
        "bonds_retained": [
            f"{bond['atom_1']}--{bond['atom_2']}" for bond in graph["bonds_retained"]
        ],
    }


def load_patch_charge_scope(
    product: str, stereochemistry: str, *, registry_path: Path = REGISTRY_PATH
) -> dict[str, Any]:
    """Load the immutable charge/type replacement boundary for one product patch."""

    registry = photoproduct_registry(registry_path)
    entry = next(
        (
            item
            for item in registry["products"]
            if item["product"] == product
            and item["stereochemistry"] == stereochemistry
        ),
        None,
    )
    if entry is None:
        raise KeyError(f"unregistered photoproduct: {product}/{stereochemistry}")
    record = (entry.get("assets") or {}).get("patch_charge_scope")
    if not isinstance(record, dict) or not record.get("path"):
        raise FileNotFoundError(
            f"patch charge scope is unavailable for {product}/{stereochemistry}"
        )
    path = (registry_path.parent / record["path"]).resolve()
    path.relative_to(registry_path.parent.resolve())
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.get(
        "sha256"
    ):
        raise ValueError("patch charge-scope asset is missing or hash-mismatched")
    scope = json.loads(path.read_text())
    definition_asset = chemical_definition_asset(
        product, stereochemistry, registry_path=registry_path
    )
    definition = load_chemical_definition(
        product, stereochemistry, registry_path=registry_path
    )
    patched = scope.get("atoms_with_charges_replaced")
    boundaries = scope.get("unchanged_boundary_atoms")
    local_atoms = {
        atom
        for bond in definition["precursor_local_connectivity"]["bonds"]
        for atom in bond
    }
    scope_schema = scope.get("schema")
    if scope_schema == "nadoc.photoproduct-patch-charge-scope.v1":
        identity_matches = (
            scope.get("product_id") == definition["id"]
            and scope.get("chemical_definition_sha256") == definition_asset["sha256"]
        )
    elif scope_schema == "nadoc.photoproduct-patch-charge-scope.v2":
        definitions = scope.get("chemical_definitions")
        identity_matches = (
            isinstance(definitions, dict)
            and set(definitions) == {
                item["id"]
                for item in registry["products"]
                if item["product"] == "TT-CPD"
            }
            and definitions.get(definition["id"]) == definition_asset["sha256"]
        )
    else:
        identity_matches = False
    if (
        not identity_matches
        or not isinstance(patched, list)
        or not patched
        or len(patched) != len(set(patched))
        or not isinstance(boundaries, list)
        or len(boundaries) != len(set(boundaries))
        or set(patched) & set(boundaries)
        or set(patched) | set(boundaries) != local_atoms
        or not isinstance(scope.get("expected_pair_charge"), int)
        or not scope.get("model_caps")
    ):
        raise ValueError("patch charge scope is incomplete or does not partition the definition")
    normalized = dict(scope)
    normalized["product_id"] = definition["id"]
    normalized["chemical_definition_sha256"] = definition_asset["sha256"]
    normalized["source"] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return normalized


def signed_tetrahedron_volume(
    coordinates: Mapping[str, Sequence[float]], center: str, references: Sequence[str]
) -> float:
    if len(references) != 3:
        raise ValueError("a signed-volume audit requires exactly three reference atoms")
    origin = np.asarray(coordinates[center], dtype=float)
    vectors = np.stack(
        [np.asarray(coordinates[name], dtype=float) - origin for name in references]
    )
    return float(np.linalg.det(vectors))


def audit_product_chirality(
    definition: Mapping[str, Any], coordinates: Mapping[str, Sequence[float]]
) -> dict[str, Any]:
    centers = []
    for record in definition.get("product_stereocenters") or []:
        value = signed_tetrahedron_volume(
            coordinates,
            record["atom"],
            record["signed_volume_reference_atoms"],
        )
        expected = record["expected_signed_volume"]
        passed = value > 0 if expected == "positive" else value < 0
        centers.append(
            {
                "atom": record["atom"],
                "ccd_configuration": record.get("ccd_configuration"),
                "signed_volume": value,
                "expected_sign": expected,
                "passed": passed,
            }
        )
    return {
        "schema": "nadoc.photoproduct-chirality-audit.v1",
        "product_id": definition.get("id"),
        "passed": bool(centers) and all(item["passed"] for item in centers),
        "centers": centers,
    }
