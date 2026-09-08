import hashlib
import json

import pytest

from backend.parameterization.photoproduct_stereo_candidates import (
    _audit_signed_volume_records,
    _candidate_patch_charge_scope,
    build_tt_cpd_chemical_definition_candidate,
    tt_cpd_candidate_recipe,
)


def test_noncanonical_definition_source_never_claims_canonical_scope_identity():
    scope = _candidate_patch_charge_scope("tt-cpd-trans-syn-i")
    assert scope["product_id"] == "tt-cpd-trans-syn-i"
    assert scope["status"] == "boundary_transfer_review_required"
    assert "chemical_definition_sha256" not in scope
    assert scope["source_scope"]["product_id"] == "tt-cpd-cis-syn"
    assert scope["source_scope"]["chemical_definition_sha256"]
    assert "no charge or parameter transfer" in scope["source_scope"]["transfer_claim"]


def test_all_eight_ordered_isomers_have_explicit_face_and_graph_recipes():
    expected = {
        "cis-syn": ("syn", [False, False]),
        "cis-syn-II": ("syn", [True, True]),
        "trans-syn-I": ("syn", [True, False]),
        "trans-syn-II": ("syn", [False, True]),
        "cis-anti-I": ("anti", [True, False]),
        "cis-anti-II": ("anti", [False, True]),
        "trans-anti-I": ("anti", [False, False]),
        "trans-anti-II": ("anti", [True, True]),
    }
    recipes = {
        stereo: tt_cpd_candidate_recipe(stereo) for stereo in expected
    }
    assert len(recipes) == 8
    for stereo, (orientation, flips) in expected.items():
        assert recipes[stereo]["orientation"] == orientation
        assert recipes[stereo]["endpoint_face_flips"] == flips
        assert recipes[stereo]["crosslinks"] == (
            [["1:C5", "2:C5"], ["1:C6", "2:C6"]]
            if orientation == "syn"
            else [["1:C5", "2:C6"], ["1:C6", "2:C5"]]
        )


def test_unknown_stereo_candidate_never_falls_back_to_a_mirror():
    with pytest.raises(ValueError, match="unsupported TT-CPD candidate"):
        tt_cpd_candidate_recipe("plausible-looking-isomer")


def test_candidate_signed_volume_audit_recomputes_all_four_centers():
    coordinates = {}
    records = []
    for endpoint in (1, 2):
        for offset, center in enumerate(("C5", "C6")):
            key = f"{endpoint}:{center}"
            prefix = f"{endpoint}:{center}:ref"
            coordinates[key] = [10.0 * endpoint, 3.0 * offset, 0.0]
            coordinates[f"{prefix}:a"] = [10.0 * endpoint + 1.0, 3.0 * offset, 0.0]
            coordinates[f"{prefix}:b"] = [10.0 * endpoint, 3.0 * offset + 1.0, 0.0]
            coordinates[f"{prefix}:c"] = [10.0 * endpoint, 3.0 * offset, 1.0]
            records.append(
                {
                    "atom": key,
                    "reference_atoms": [
                        f"{prefix}:a",
                        f"{prefix}:b",
                        f"{prefix}:c",
                    ],
                    "expected_sign": "positive",
                }
            )
    assert _audit_signed_volume_records(
        coordinates=coordinates, records=records
    )["passed"] is True
    records[0]["expected_sign"] = "negative"
    assert _audit_signed_volume_records(
        coordinates=coordinates, records=records
    )["passed"] is False


def test_definition_candidate_requires_passed_hash_linked_audit(tmp_path):
    manifest = tmp_path / "candidate.json"
    manifest.write_text(
        '{"schema":"nadoc.tt-cpd-stereo-candidate.v1",'
        '"status":"candidate_not_reviewed",'
        '"product_id":"tt-cpd-cis-syn-ii"}'
    )
    audit = tmp_path / "audit.json"
    audit.write_text(
        '{"schema":"nadoc.tt-cpd-stereo-candidate-audit.v1",'
        '"status":"passed_candidate","candidates":[]}'
    )
    with pytest.raises(ValueError, match="covered by the passed series audit"):
        build_tt_cpd_chemical_definition_candidate(
            product_id="tt-cpd-cis-syn-ii",
            candidate_manifest_path=manifest,
            candidate_audit_path=audit,
            independent_audit_path=audit,
            output_path=tmp_path / "definition.json",
        )


def test_definition_candidate_requires_independent_stereo_crosscheck(tmp_path):
    manifest = tmp_path / "candidate.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-stereo-candidate.v1",
                "status": "candidate_not_reviewed",
                "product_id": "tt-cpd-cis-syn-ii",
                "outputs": {"sdf": {"sha256": "a" * 64}},
            }
        )
    )
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-stereo-candidate-audit.v1",
                "status": "passed_candidate",
                "candidates": [
                    {
                        "product_id": "tt-cpd-cis-syn-ii",
                        "passed": True,
                        "manifest_sha256": digest,
                    }
                ],
            }
        )
    )
    independent = tmp_path / "independent.json"
    independent.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-openbabel-stereo-audit.v1",
                "status": "failed",
                "passed": False,
                "candidate_audit": {
                    "sha256": hashlib.sha256(audit.read_bytes()).hexdigest()
                },
                "records": [],
            }
        )
    )

    with pytest.raises(ValueError, match="independent stereo audit"):
        build_tt_cpd_chemical_definition_candidate(
            product_id="tt-cpd-cis-syn-ii",
            candidate_manifest_path=manifest,
            candidate_audit_path=audit,
            independent_audit_path=independent,
            output_path=tmp_path / "definition.json",
        )
