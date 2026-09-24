"""Preliminary availability must not imply release or relax chemical identity checks."""

import copy
import hashlib
import json

import pytest

from backend.core.cpd_forcefield import photoproduct_package_assets
from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_capability
from backend.core.photoproducts import (
    preflight_photoproduct,
    create_photoproduct_from_preflight,
)
from backend.core.cpd_product import _template_coordinates, ProductPlacementError
from tests.conftest import make_minimal_design


def _design():
    d = make_minimal_design(helix_length_bp=12)
    return d.copy_with(
        strands=[
            s.model_copy(update={"sequence": ("T" if i == 0 else "A") * 12})
            for i, s in enumerate(d.strands)
        ]
    )


def test_preliminary_is_scoped_and_never_passes_full_release_gates():
    cap = photoproduct_capability("TT-CPD", "cis-syn")
    assert cap["simulation_supported"] and not cap["simulation_ready"]
    assert cap["gate_status"]["solution_validation"] != "passed"
    assert not photoproduct_capability("TT-CPD", "cis-syn-II")["simulation_supported"]


def test_builder_preflight_preserves_design_and_packages_verified_evidence():
    d = _design()
    before = d.model_dump_json()
    report = preflight_photoproduct(d, ["h0:5:FORWARD", "h0:6:FORWARD"])
    assert report["simulation_supported"] and not report["simulation_ready"]
    assert report["placement_report"]["chirality_audit"]["passed"]
    assert d.model_dump_json() == before
    product, _ = create_photoproduct_from_preflight(d, report)
    assets = photoproduct_package_assets(product)
    assert any(a["kind"].startswith("preliminary_evidence_") for a in assets)
    for a in assets:
        assert hashlib.sha256(a["source_path"].read_bytes()).hexdigest() == a["sha256"]


def test_nonadjacent_product_remains_intent_only():
    report = preflight_photoproduct(_design(), ["h0:2:FORWARD", "h0:7:FORWARD"])
    assert report["eligible"] and not report["simulation_supported"]
    assert any(
        w["code"] == "preliminary_context_unsupported" for w in report["warnings"]
    )


def test_terminal_product_remains_intent_only():
    report = preflight_photoproduct(_design(), ["h0:0:FORWARD", "h0:1:FORWARD"])
    assert report["eligible"] and not report["simulation_supported"]
    assert any("internal TT" in w["message"] for w in report["warnings"])


def test_preliminary_template_does_not_impersonate_qm_evidence():
    p = (
        REGISTRY_PATH.parent
        / "photoproducts/tt-cpd-cis-syn/preliminary-v6/template.json"
    )
    template = json.loads(p.read_text())
    with pytest.raises(ProductPlacementError):
        _template_coordinates(template)
    _template_coordinates(template, allowed_release_statuses=frozenset({"preliminary"}))
    bad = copy.deepcopy(template)
    del bad["provenance"]["coordinates_sha256"]
    with pytest.raises(ProductPlacementError, match="provenance hashes"):
        _template_coordinates(bad, allowed_release_statuses=frozenset({"preliminary"}))


def test_raw_seed_cannot_overwrite_audited_product_placement():
    from backend.core.cpd_forcefield import (
        assert_photoproduct_seed_inputs,
        CpdCapabilityError,
    )

    d = _design()
    report = preflight_photoproduct(d, ["h0:5:FORWARD", "h0:6:FORWARD"])
    product, _ = create_photoproduct_from_preflight(d, report)
    with pytest.raises(CpdCapabilityError, match="bypass"):
        assert_photoproduct_seed_inputs(product, solute_coords=[], graphene_only=False)
    with pytest.raises(CpdCapabilityError, match="bypass"):
        assert_photoproduct_seed_inputs(product, solute_coords=None, graphene_only=True)
    assert_photoproduct_seed_inputs(product, solute_coords=None, graphene_only=False)


def test_reversed_selection_keeps_chemical_five_to_three_order():
    report = preflight_photoproduct(_design(), ["h0:6:FORWARD", "h0:5:FORWARD"])
    assert report["simulation_supported"]
    assert report["orientation"]["base_key_1"] == "h0:5:FORWARD"
    assert report["orientation"]["base_key_2"] == "h0:6:FORWARD"
