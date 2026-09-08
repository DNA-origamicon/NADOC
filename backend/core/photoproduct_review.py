"""Hash-pinned, gate-neutral 3D review data for TT-CPD candidates.

This module deliberately records *visual identity* decisions only.  A reviewer can
confirm atom mapping, connectivity, endpoint order and stereochemistry, but cannot
release a force field or make a product simulation-ready through this interface.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from backend.core.photoproduct_storage import validate_photoproduct_storage_root


DEFAULT_STORAGE_ROOT = Path("/media/jojo/Archive/NADOC_archive")
DEFINITION_PACKET_RELATIVE = Path(
    "photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/"
    "definition_review_packet.json"
)
CONFORMER_INDEX_RELATIVE = Path(
    "photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/"
    "coupled-conformer-review-index-v2/coupled_conformer_review_index.json"
)
DECISIONS_RELATIVE = Path(
    "photoproduct_evidence/tt-cpd-human-visual-review-v1/"
    "visual_review_decisions.json"
)
BOUNDARY_MODEL_RELATIVES = (
    Path(
        "photoproduct_evidence/tt-cpd-work-v1/models/"
        "dtpdt-boundary-candidate-v2"
    ),
    Path(
        "photoproduct_evidence/tt-cpd-work-v1/models/"
        "dtpdt-boundary-candidate-chain-d-v2"
    ),
)


class PhotoproductReviewError(ValueError):
    """Review evidence is unavailable, stale, or malformed."""


def _storage_root() -> Path:
    return Path(
        os.environ.get("NADOC_PHOTOPRODUCT_STORAGE_ROOT", str(DEFAULT_STORAGE_ROOT))
    ).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checked_source(record: dict[str, Any], label: str) -> Path:
    path = Path(str(record.get("path") or ""))
    expected = str(record.get("sha256") or "")
    if not path.is_file():
        raise PhotoproductReviewError(f"{label} is missing: {path}")
    actual = _sha256(path)
    if not expected or actual != expected:
        raise PhotoproductReviewError(
            f"{label} hash changed (expected {expected or 'none'}, found {actual})"
        )
    return path


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PhotoproductReviewError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PhotoproductReviewError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PhotoproductReviewError(f"{label} must contain a JSON object")
    return payload


def _xyz(path: Path, keys: list[str]) -> tuple[list[str], list[list[float]]]:
    lines = path.read_text().splitlines()
    try:
        count = int(lines[0].strip())
    except (IndexError, ValueError) as exc:
        raise PhotoproductReviewError(f"invalid XYZ header: {path}") from exc
    rows = [line.split() for line in lines[2:] if line.strip()]
    if count != len(rows) or count != len(keys):
        raise PhotoproductReviewError(
            f"XYZ/atom-map count mismatch in {path}: {count}, {len(rows)}, {len(keys)}"
        )
    try:
        elements = [row[0] for row in rows]
        coordinates = [[float(row[1]), float(row[2]), float(row[3])] for row in rows]
    except (IndexError, ValueError) as exc:
        raise PhotoproductReviewError(f"invalid XYZ coordinate row: {path}") from exc
    return elements, coordinates


def _atom_keys(path: Path) -> list[str]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise PhotoproductReviewError(f"atom map is not a list: {path}")
    if payload and isinstance(payload[0], dict):
        keys = [str(item.get("stable_atom_key") or "") for item in payload]
    else:
        keys = [str(item) for item in payload]
    if not keys or "" in keys or len(keys) != len(set(keys)):
        raise PhotoproductReviewError(f"atom map has missing or duplicate keys: {path}")
    return keys


def _sdf_bonds(path: Path, keys: list[str]) -> list[dict[str, Any]]:
    """Read the V2000 connectivity only; coordinates continue to come from XYZ."""

    lines = path.read_text().splitlines()
    try:
        counts = lines[3].split()
        atom_count, bond_count = int(counts[0]), int(counts[1])
    except (IndexError, ValueError) as exc:
        raise PhotoproductReviewError(f"invalid V2000 SDF counts line: {path}") from exc
    if atom_count != len(keys):
        raise PhotoproductReviewError(f"SDF/atom-map count mismatch in {path}")
    bonds = []
    for line in lines[4 + atom_count : 4 + atom_count + bond_count]:
        fields = line.split()
        try:
            i, j, order = int(fields[0]) - 1, int(fields[1]) - 1, int(fields[2])
            bonds.append({"atoms": [keys[i], keys[j]], "order": order})
        except (IndexError, ValueError) as exc:
            raise PhotoproductReviewError(f"invalid V2000 SDF bond row: {path}") from exc
    if len(bonds) != bond_count:
        raise PhotoproductReviewError(f"truncated V2000 SDF bond table: {path}")
    return bonds


def _bond_kind(a: str, b: str) -> str:
    pair = frozenset((a, b))
    if pair in {
        frozenset(("1:O5'", "1:HO5'")),
        frozenset(("2:O3'", "2:HO3'")),
    }:
        return "terminal_cap"
    if pair in {
        frozenset(("2:P", "2:OP1")),
        frozenset(("2:P", "2:OP2")),
        frozenset(("2:P", "1:O3'")),
        frozenset(("2:P", "2:O5'")),
    }:
        return "phosphate_boundary"
    if pair in {
        frozenset(("1:C1'", "1:N1")),
        frozenset(("2:C1'", "2:N1")),
    }:
        return "glycosidic_boundary"
    if pair in {
        frozenset(("1:C5", "2:C5")),
        frozenset(("1:C6", "2:C6")),
        frozenset(("1:C5", "2:C6")),
        frozenset(("1:C6", "2:C5")),
    } and a.split(":", 1)[0] != b.split(":", 1)[0]:
        return "photoproduct_crosslink"
    if pair in {
        frozenset(("1:C5", "1:C6")),
        frozenset(("2:C5", "2:C6")),
    }:
        return "cyclobutane_ring"
    return "ordinary"


def _scene(
    *,
    product_id: str,
    model_id: str,
    geometry: dict[str, Any],
    atom_map: dict[str, Any],
    bonds: list[dict[str, Any]],
    stereocenters: list[dict[str, Any]],
    metadata: dict[str, Any],
    replace_dna_boundary_with_model_caps: bool = True,
) -> dict[str, Any]:
    geometry_path = _checked_source(geometry, f"{product_id} geometry")
    map_path = _checked_source(atom_map, f"{product_id} atom map")
    keys = _atom_keys(map_path)
    elements, coordinates = _xyz(geometry_path, keys)
    index = {key: i for i, key in enumerate(keys)}
    normalized_bonds = []
    seen: set[frozenset[str]] = set()
    for bond in bonds:
        atoms = bond.get("atoms") or [bond.get("atom_1"), bond.get("atom_2")]
        if not isinstance(atoms, list) or len(atoms) != 2:
            continue
        a, b = str(atoms[0]), str(atoms[1])
        # Conformer definition graphs name the DNA C1' boundary while their
        # N1-methyl model coordinates name CM. Full DNA-boundary models retain C1'.
        if replace_dna_boundary_with_model_caps:
            a = a.replace(":C1'", ":CM")
            b = b.replace(":C1'", ":CM")
        pair = frozenset((a, b))
        if a not in index or b not in index or a == b or pair in seen:
            continue
        seen.add(pair)
        normalized_bonds.append(
            {
                "atoms": [a, b],
                "indices": [index[a], index[b]],
                "order": bond.get("order", bond.get("product_order", 1)),
                "kind": _bond_kind(a, b),
            }
        )
    centers = []
    for center in stereocenters:
        atom = str(center.get("atom") or "")
        if atom not in index:
            raise PhotoproductReviewError(
                f"{product_id} stereocenter {atom!r} is absent from its atom map"
            )
        centers.append(
            {
                "atom": atom,
                "atom_index": index[atom],
                "configuration": center.get("ccd_configuration"),
                "expected_sign": center.get(
                    "expected_signed_volume", center.get("expected_sign")
                ),
                "reference_atoms": center.get(
                    "signed_volume_reference_atoms", center.get("reference_atoms")
                ),
                "signed_volume": center.get("signed_volume"),
                "passed": center.get("passed"),
            }
        )
    return {
        "product_id": product_id,
        "model_id": model_id,
        "atom_keys": keys,
        "elements": elements,
        "coordinates_angstrom": coordinates,
        "bonds": normalized_bonds,
        "stereocenters": centers,
        "source_geometry": geometry,
        "source_atom_map": atom_map,
        "metadata": metadata,
    }


def _definition_scene(
    *,
    product_id: str,
    definition_path: Path,
    definition_record: dict[str, Any],
    definition: dict[str, Any],
    center_audits: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Render and pin the exact local coordinates stored in a definition."""

    coordinates_by_key = definition.get("source_ring_coordinates_angstrom")
    if not isinstance(coordinates_by_key, dict) or not coordinates_by_key:
        raise PhotoproductReviewError(
            f"{product_id} definition has no source ring coordinates"
        )
    keys = list(coordinates_by_key)
    if len(keys) != len(set(keys)):
        raise PhotoproductReviewError(
            f"{product_id} definition has duplicate coordinate keys"
        )
    try:
        coordinates = [
            [float(value) for value in coordinates_by_key[key]] for key in keys
        ]
    except (TypeError, ValueError) as exc:
        raise PhotoproductReviewError(
            f"{product_id} definition coordinates are not numeric triples"
        ) from exc
    if any(len(value) != 3 for value in coordinates):
        raise PhotoproductReviewError(
            f"{product_id} definition coordinates are not three-dimensional"
        )
    elements = [key.rsplit(":", 1)[-1][0].upper() for key in keys]
    index = {key: i for i, key in enumerate(keys)}

    graph_delta = definition.get("graph_delta") or {}
    product_bonds: list[dict[str, Any]] = [
        {"atoms": list(pair), "order": 1}
        for pair in (
            (definition.get("precursor_local_connectivity") or {}).get("bonds") or []
        )
    ]
    product_bonds.extend(graph_delta.get("bonds_added") or [])
    retained = {
        frozenset((str(item.get("atom_1")), str(item.get("atom_2")))): item
        for item in graph_delta.get("bonds_retained") or []
    }
    normalized_bonds = []
    seen: set[frozenset[str]] = set()
    for bond in product_bonds:
        atoms = bond.get("atoms") or [bond.get("atom_1"), bond.get("atom_2")]
        if not isinstance(atoms, list) or len(atoms) != 2:
            continue
        a, b = str(atoms[0]), str(atoms[1])
        pair = frozenset((a, b))
        if a not in index or b not in index or a == b or pair in seen:
            continue
        seen.add(pair)
        retained_record = retained.get(pair) or {}
        normalized_bonds.append(
            {
                "atoms": [a, b],
                "indices": [index[a], index[b]],
                "order": retained_record.get(
                    "product_order", bond.get("order", bond.get("product_order", 1))
                ),
                "kind": _bond_kind(a, b),
            }
        )

    centers = []
    for center in definition.get("product_stereocenters") or []:
        atom = str(center.get("atom") or "")
        if atom not in index:
            raise PhotoproductReviewError(
                f"{product_id} stereocenter {atom!r} is absent from definition coordinates"
            )
        audit = center_audits.get(atom) or {}
        centers.append(
            {
                "atom": atom,
                "atom_index": index[atom],
                "configuration": center.get("ccd_configuration"),
                "expected_sign": center.get("expected_signed_volume"),
                "reference_atoms": center.get("signed_volume_reference_atoms"),
                "signed_volume": audit.get("signed_volume"),
                "passed": audit.get("passed"),
            }
        )

    return {
        "product_id": product_id,
        "model_id": str(
            (definition.get("model_compounds") or {}).get("charge_model", {}).get("id")
            or ""
        ),
        "atom_keys": keys,
        "elements": elements,
        "coordinates_angstrom": coordinates,
        "bonds": normalized_bonds,
        "stereocenters": centers,
        # The definition file contains the exact stable-key coordinate mapping being
        # rendered, so its hash is the visual decision's immutable geometry identity.
        "source_geometry": {
            "path": str(definition_path),
            "sha256": str(definition_record.get("sha256") or _sha256(definition_path)),
        },
        "source_atom_map": None,
        "metadata": {
            **metadata,
            "geometry_source": "exact_definition_local_coordinates",
            "rendered_atom_count": len(keys),
        },
    }


def _decision_for_scene(
    decision: dict[str, Any] | None, scene: dict[str, Any]
) -> dict[str, Any] | None:
    """Expose hash-mismatched decisions as stale, never as current approvals."""

    if decision is None:
        return None
    expected = str((scene.get("source_geometry") or {}).get("sha256") or "")
    observed = str(decision.get("source_geometry_sha256") or "")
    if expected and observed == expected:
        return decision
    return {
        **decision,
        "stale": True,
        "stale_reason": (
            "The rendered definition geometry changed or the prior decision reviewed "
            "a different source. Re-open this model and record a new decision."
        ),
        "current_source_geometry_sha256": expected,
    }


def _load_decisions(path: Path, sources: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": "nadoc.photoproduct-visual-review-decisions.v1",
            "status": "human_input_required",
            "simulation_ready": False,
            "gate_effect": "none",
            "source_definition_packet": sources["definition_packet"],
            "source_conformer_index": sources["conformer_index"],
            "decisions": [],
        }
    payload = _read_json(path, "visual review decisions")
    if (
        payload.get("schema") != "nadoc.photoproduct-visual-review-decisions.v1"
        or payload.get("simulation_ready") is not False
        or payload.get("gate_effect") != "none"
        or payload.get("source_definition_packet") != sources["definition_packet"]
        or payload.get("source_conformer_index") != sources["conformer_index"]
        or not isinstance(payload.get("decisions"), list)
    ):
        raise PhotoproductReviewError(
            "visual review decisions are stale or do not match the current source hashes"
        )
    return payload


def build_photoproduct_review_catalog(*, storage_root: Path | None = None) -> dict[str, Any]:
    root = (storage_root or _storage_root()).resolve()
    definition_path = root / DEFINITION_PACKET_RELATIVE
    conformer_path = root / CONFORMER_INDEX_RELATIVE
    definition = _read_json(definition_path, "TT-CPD definition review packet")
    conformer_index = _read_json(conformer_path, "TT-CPD conformer review index")
    if definition.get("schema") != "nadoc.tt-cpd-definition-human-review-packet.v1":
        raise PhotoproductReviewError("unsupported definition review packet schema")
    if conformer_index.get("schema") != "nadoc.photoproduct-coupled-conformer-review-index.v1":
        raise PhotoproductReviewError("unsupported conformer review index schema")
    sources = {
        "definition_packet": _source(definition_path),
        "conformer_index": _source(conformer_path),
    }
    decisions_path = root / DECISIONS_RELATIVE
    decisions = _load_decisions(decisions_path, sources)
    by_key = {
        (item.get("stage"), item.get("product_id"), item.get("conformer_id")): item
        for item in decisions["decisions"]
    }

    definition_scenes = []
    for candidate in definition.get("candidates") or []:
        product_id = str(candidate.get("product_id") or "")
        candidate_path = _checked_source(
            candidate.get("definition_candidate") or {}, f"{product_id} definition"
        )
        chemical = _read_json(candidate_path, f"{product_id} chemical definition")
        center_audits = {
            item.get("atom"): item
            for item in (
                (candidate.get("minimum_geometry_evidence") or {})
                .get("chirality_audit", {})
                .get("centers", [])
            )
        }
        scene = _definition_scene(
            product_id=product_id,
            definition_path=candidate_path,
            definition_record=candidate.get("definition_candidate") or {},
            definition=chemical,
            center_audits=center_audits,
            metadata={
                "stereochemistry": candidate.get("stereochemistry"),
                "orientation": candidate.get("orientation"),
                "ordered_c5_configurations": candidate.get("ordered_c5_configurations"),
                "frequency_status": (candidate.get("frequency_evidence") or {}).get("status"),
                "mirror_operation_used": _read_json(
                    _checked_source(candidate.get("candidate_manifest") or {}, f"{product_id} candidate manifest"),
                    f"{product_id} candidate manifest",
                ).get("mirror_operation_used"),
            },
        )
        scene["decision"] = _decision_for_scene(
            by_key.get(("chemical_definition", product_id, None)), scene
        )
        definition_scenes.append(scene)

    conformer_groups = []
    for record in conformer_index.get("records") or []:
        product_id = str(record.get("product_id") or "")
        plan_path = _checked_source(record.get("plan") or {}, f"{product_id} conformer plan")
        plan = _read_json(plan_path, f"{product_id} conformer plan")
        graph_path = _checked_source(
            (plan.get("sources") or {}).get("model_graph") or {}, f"{product_id} model graph"
        )
        map_path = _checked_source(
            (plan.get("sources") or {}).get("stable_atom_map") or {}, f"{product_id} stable atom map"
        )
        graph = _read_json(graph_path, f"{product_id} model graph")
        atom_map = _source(map_path)
        chemical_path = _checked_source(
            (plan.get("sources") or {}).get("stereochemistry_evidence") or {},
            f"{product_id} stereochemistry evidence",
        )
        chemical = _read_json(chemical_path, f"{product_id} stereochemistry evidence")
        chemical_centers = {
            item.get("atom"): item for item in chemical.get("product_stereocenters") or []
        }
        frames = []
        for conformer in plan.get("conformers") or []:
            conformer_id = str(conformer.get("id") or "")
            audited_centers = [
                {**(chemical_centers.get(item.get("atom")) or {}), **item}
                for item in (conformer.get("chirality_audit") or {}).get("centers") or []
            ]
            conformer_scene = _scene(
                product_id=product_id,
                model_id=str(record.get("model_id") or ""),
                geometry=conformer.get("geometry") or {},
                atom_map=atom_map,
                bonds=graph.get("bonds") or [],
                stereocenters=audited_centers or list(chemical_centers.values()),
                metadata={
                    "conformer_id": conformer_id,
                    "source_candidate_id": conformer.get("source_candidate_id"),
                    "geometry_audit": conformer.get("geometry_audit"),
                    "chirality_passed": (conformer.get("chirality_audit") or {}).get("passed"),
                },
            )
            frames.append(
                {
                    **conformer_scene,
                    "conformer_id": conformer_id,
                    "decision": _decision_for_scene(
                        by_key.get(
                            ("coupled_conformer", product_id, conformer_id)
                        ),
                        conformer_scene,
                    ),
                }
            )
        conformer_groups.append(
            {"product_id": product_id, "model_id": record.get("model_id"), "frames": frames}
        )

    boundary_scenes = []
    for relative in BOUNDARY_MODEL_RELATIVES:
        model_dir = root / relative
        manifest_path = model_dir / "candidate_manifest.json"
        manifest = _read_json(manifest_path, f"DNA boundary model {relative.name}")
        if (
            manifest.get("schema")
            != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
            or manifest.get("status") != "candidate_pending_cap_review"
            or manifest.get("gate_effect") != "none"
            or manifest.get("product_id") != "tt-cpd-cis-syn"
        ):
            raise PhotoproductReviewError(
                f"unsupported DNA boundary candidate: {manifest_path}"
            )
        outputs = manifest.get("outputs") or {}

        def local_output(name: str) -> dict[str, str]:
            record = outputs.get(name) or {}
            local_path = model_dir / Path(str(record.get("path") or "")).name
            expected = str(record.get("sha256") or "")
            if not local_path.is_file() or _sha256(local_path) != expected:
                raise PhotoproductReviewError(
                    f"DNA boundary {name} is missing or hash-mismatched: {local_path}"
                )
            return {"path": str(local_path), "sha256": expected}

        geometry = local_output("xyz")
        atom_map = local_output("atom_map")
        sdf = local_output("sdf")
        keys = _atom_keys(Path(atom_map["path"]))
        chain = str((manifest.get("source_selection") or {}).get("chain") or "")
        review_id = f"chain-{chain.lower()}"
        scene = _scene(
            product_id="tt-cpd-cis-syn",
            model_id=str(manifest.get("model_id") or ""),
            geometry=geometry,
            atom_map=atom_map,
            bonds=_sdf_bonds(Path(sdf["path"]), keys),
            stereocenters=(manifest.get("chirality_audit") or {}).get("centers") or [],
            metadata={
                "review_id": review_id,
                "source_selection": manifest.get("source_selection"),
                "formal_charge": manifest.get("formal_charge"),
                "caps_and_protonation": manifest.get("caps_and_protonation"),
                "serialization_note": manifest.get("serialization_note"),
                "crosslink_distances": manifest.get("crosslink_distances"),
                "chirality_passed": (manifest.get("chirality_audit") or {}).get("passed"),
                "source_manifest": _source(manifest_path),
            },
            replace_dna_boundary_with_model_caps=False,
        )
        scene["conformer_id"] = review_id
        scene["decision"] = _decision_for_scene(
            by_key.get(("dna_boundary_model", "tt-cpd-cis-syn", review_id)), scene
        )
        boundary_scenes.append(scene)

    return {
        "schema": "nadoc.photoproduct-visual-review-catalog.v1",
        "simulation_ready": False,
        "gate_effect": "none",
        "review_scope": "visual_identity_and_stereochemistry_only",
        "parameter_acceptance_scope": "excluded_quantitative_machine_gates_required",
        "sources": sources,
        "decision_store": str(decisions_path),
        "definition_scenes": definition_scenes,
        "conformer_groups": conformer_groups,
        "boundary_scenes": boundary_scenes,
        "stale_decision_count": sum(
            1
            for scene in definition_scenes
            if (scene.get("decision") or {}).get("stale") is True
        )
        + sum(
            1
            for group in conformer_groups
            for frame in group["frames"]
            if (frame.get("decision") or {}).get("stale") is True
        )
        + sum(
            1
            for scene in boundary_scenes
            if (scene.get("decision") or {}).get("stale") is True
        ),
    }


def record_photoproduct_visual_decision(
    *,
    stage: str,
    product_id: str,
    decision: str,
    reviewer: str,
    notes: str,
    conformer_id: str | None = None,
    partition: str | None = None,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    if stage not in {
        "chemical_definition",
        "coupled_conformer",
        "dna_boundary_model",
    }:
        raise PhotoproductReviewError("unsupported review stage")
    if decision not in {"approve", "reject", "revise"}:
        raise PhotoproductReviewError("decision must be approve, reject, or revise")
    if len(reviewer.strip()) < 2:
        raise PhotoproductReviewError("reviewer name is required")
    if len(notes.strip()) < 12:
        raise PhotoproductReviewError("review notes must contain at least 12 characters")
    if stage == "chemical_definition" and conformer_id is not None:
        raise PhotoproductReviewError("chemical-definition decisions cannot name a conformer")
    if stage == "coupled_conformer" and not conformer_id:
        raise PhotoproductReviewError("coupled-conformer decisions require a conformer ID")
    if stage == "dna_boundary_model" and not conformer_id:
        raise PhotoproductReviewError("DNA-boundary decisions require a candidate ID")
    if decision == "approve" and stage == "coupled_conformer":
        if partition not in {"training", "validation"}:
            raise PhotoproductReviewError(
                "approved conformers require a training or validation partition"
            )
    elif partition is not None:
        raise PhotoproductReviewError("reject/revise decisions cannot enter a fit partition")

    root = (storage_root or _storage_root()).resolve()
    validate_photoproduct_storage_root(root)
    catalog = build_photoproduct_review_catalog(storage_root=root)
    valid_keys = {
        ("chemical_definition", scene["product_id"], None)
        for scene in catalog["definition_scenes"]
    }
    valid_keys.update(
        ("coupled_conformer", group["product_id"], frame["conformer_id"])
        for group in catalog["conformer_groups"]
        for frame in group["frames"]
    )
    valid_keys.update(
        ("dna_boundary_model", scene["product_id"], scene["conformer_id"])
        for scene in catalog["boundary_scenes"]
    )
    key = (stage, product_id, conformer_id)
    if key not in valid_keys:
        raise PhotoproductReviewError(f"unknown review target: {key}")

    path = root / DECISIONS_RELATIVE
    payload = _load_decisions(path, catalog["sources"])
    record = {
        "stage": stage,
        "product_id": product_id,
        "conformer_id": conformer_id,
        "decision": decision,
        "partition": partition,
        "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes.strip(),
        "source_geometry_sha256": next(
            (
                scene["source_geometry"]["sha256"]
                for scene in catalog["definition_scenes"]
                if key == ("chemical_definition", scene["product_id"], None)
            ),
            next(
                (
                    frame["source_geometry"]["sha256"]
                    for group in catalog["conformer_groups"]
                    for frame in group["frames"]
                    if key == ("coupled_conformer", group["product_id"], frame["conformer_id"])
                ),
                next(
                    (
                        scene["source_geometry"]["sha256"]
                        for scene in catalog["boundary_scenes"]
                        if key
                        == (
                            "dna_boundary_model",
                            scene["product_id"],
                            scene["conformer_id"],
                        )
                    ),
                    None,
                ),
            ),
        ),
        "gate_effect": "none",
    }
    payload["decisions"] = [
        item
        for item in payload["decisions"]
        if (item.get("stage"), item.get("product_id"), item.get("conformer_id")) != key
    ] + [record]
    payload["decisions"].sort(
        key=lambda item: (
            str(item.get("stage")),
            str(item.get("product_id")),
            str(item.get("conformer_id") or ""),
        )
    )
    payload["status"] = "revision_requested" if any(
        item["decision"] == "revise" for item in payload["decisions"]
    ) else "human_review_in_progress"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return {"decision": record, "decision_store": _source(path), "simulation_ready": False, "gate_effect": "none"}
