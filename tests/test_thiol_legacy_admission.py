"""Unsupported opaque ownership keeps its existing explicitly unverified route."""

import pytest

from backend.api import part_thiol_commands as commands, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies
from backend.api.routes_nanoparticles import ThiolConjugationRequest, put_conjugation
from backend.core.nanoparticle import create_gold_nanosphere
from backend.core.part_command_errors import ReferenceResolutionError
from tests.test_part_thiol_commands import deletion, params, source
from tests.test_protein import _design_with_overhang


def test_opaque_unrelated_animation_keeps_legacy_live_graft_without_native_certification(monkeypatch):
    design = _design_with_overhang().copy_with(
        nanoparticles=[create_gold_nanosphere(10, nanoparticle_id="gold")])
    design.overhangs[0].strand_anim_setup = {"binder_strand_id": "legacy-animation-binder"}
    assert not commands.native_route_eligible(design, "gold", count=1, sequence="ACGT")
    monkeypatch.setattr(commands, "record", lambda *_a, **_kw: pytest.fail("Opaque source entered native admission"))
    token = set_current_doc("thiol-legacy-opaque-admission")
    try:
        state.load_design(design)
        response = put_conjugation("gold", ThiolConjugationRequest(sequence="ACGT", count=1))
        saved = state.get_or_404()
        assert saved.nanoparticle_conjugations[0].id == response["conjugation_id"]
        assert saved.overhangs[0].strand_anim_setup == design.overhangs[0].strand_anim_setup
        entry = saved.feature_log[-1]
        assert "thiol_version" not in entry.params
        assert not dependencies(entry.op_kind, entry.params).known
    finally:
        state.close_session()
        reset_current_doc(token)


def test_supported_missing_owned_endpoint_is_not_legacy_eligibility():
    design = commands.build("nanoparticle-conjugate", source(), params())
    design.overhangs = []
    assert commands.native_route_eligible(design, "gold")
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-conjugation-delete", design, deletion())
    assert error.value.code == "missing_reference"
