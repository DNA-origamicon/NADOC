"""Headless geometry contracts for the review-only CPD catalog."""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.cpd_preview import (
    BACKBONE_NAMES,
    CORE_PATH,
    attach_isomer_previews,
    build_isomer_previews,
)
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry
from backend.core.cpd_representation import project_cpd_residue


@pytest.fixture(scope="module")
def previews():
    return build_isomer_previews()


def test_all_eight_identities_and_crosslinks_match_registered_chemistry(previews):
    entries = {
        p["id"]: p
        for p in photoproduct_registry()["products"]
        if p["product"] == "TT-CPD"
    }
    assert {m["id"] for m in previews} == entries.keys()
    for m in previews:
        entry = entries[m["id"]]
        definition = load_chemical_definition("TT-CPD", entry["stereochemistry"])
        atoms = {a["id"]: np.array(a["position"]) for a in m["atoms"]}
        assert len(atoms) == 50
        assert audit_product_chirality(definition, atoms)["passed"]
        assert m["orderedC5"] == entry["structural_class"]["ordered_c5_configurations"]
        crosslinks = [b for b in m["bonds"] if b["crosslink"]]
        assert len(crosslinks) == 2
        assert {frozenset(b["atoms"]) for b in crosslinks} == {
            frozenset((b["atom_1"], b["atom_2"]))
            for b in definition["graph_delta"]["bonds_added"]
        }
        for b in m["bonds"]:
            assert (
                0.9 < np.linalg.norm(atoms[b["atoms"][0]] - atoms[b["atoms"][1]]) < 1.8
            )
        # Preview availability never becomes local force-field evidence.
        assert all(not a["checks"] for a in m["atoms"])
        assert any(c["state"] == "pending" for c in m["checks"])


def test_estimated_sugars_preserve_reference_geometry_and_handedness(previews):
    reference = {a["id"]: np.array(a["position"]) for a in previews[0]["atoms"]}
    for m in previews:
        coords = {a["id"]: np.array(a["position"]) for a in m["atoms"]}
        for endpoint in (1, 2):
            keys = [f"{endpoint}:{n}" for n in sorted(BACKBONE_NAMES)]
            original = np.array([reference[k] for k in keys])
            moved = np.array([coords[k] for k in keys])
            assert np.allclose(
                np.linalg.norm(original[:, None] - original, axis=2),
                np.linalg.norm(moved[:, None] - moved, axis=2),
            )

            # Signed sugar volume rejects a reflected sugar even if distances agree.
            def volume(points):
                p = [points[f"{endpoint}:{n}"] for n in ("C1'", "O4'", "C2'", "C3'")]
                return np.linalg.det(np.array(p[1:]) - p[0])

            assert volume(coords) * volume(reference) > 0
            local = {
                k.split(":")[1]: v
                for k, v in coords.items()
                if k.startswith(f"{endpoint}:")
            }
            geometry = project_cpd_residue(local)
            assert np.allclose(geometry["backbone_position"], coords[f"{endpoint}:O5'"])


def test_core_distances_preserved_and_current_cis_syn_template_used(previews):
    cores = json.loads(CORE_PATH.read_text())["products"]
    entry = photoproduct_registry()["products"][0]
    template = json.loads(
        (
            REGISTRY_PATH.parent / entry["assets"]["coordinate_template"]["path"]
        ).read_text()
    )["coordinates"]
    for m in previews:
        coords = {a["id"]: np.array(a["position"]) for a in m["atoms"]}
        source = (
            template
            if m["stereochemistry"] == "cis-syn"
            else cores[m["id"]]["coordinates"]
        )
        keys = (
            list(coords)
            if m["stereochemistry"] == "cis-syn"
            else [k for k in source if "CM" not in k]
        )
        before = np.array([source[k] for k in keys])
        after = np.array([coords[k] for k in keys])
        assert np.allclose(
            np.linalg.norm(before[:, None] - before, axis=2),
            np.linalg.norm(after[:, None] - after, axis=2),
        )


def test_snapshot_refresh_preserves_evidence_and_release_registry(previews):
    registry = REGISTRY_PATH.read_bytes()
    payload = {
        "generatedAt": "original evidence date",
        "models": [{"id": "preserved-study"}],
        "sources": {"existing": {"file": "study"}},
    }
    result = attach_isomer_previews(payload)
    assert result["generatedAt"] == "original evidence date"
    assert result["models"] == [{"id": "preserved-study"}]
    assert result["sources"]["existing"] == {"file": "study"}
    assert REGISTRY_PATH.read_bytes() == registry
    saved = json.loads(
        (
            Path(__file__).resolve().parents[1] / "frontend/public/cpd-progress.json"
        ).read_text()
    )
    for expected, actual in zip(previews, saved["isomers"], strict=True):
        assert expected["id"] == actual["id"]
        assert np.allclose(
            [a["position"] for a in expected["atoms"]],
            [a["position"] for a in actual["atoms"]],
            atol=1e-5,
        )
