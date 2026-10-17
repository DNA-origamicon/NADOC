"""Live aptamer publication pins inputs and preserves legacy boundaries."""

import pytest
from fastapi import HTTPException

from backend.api import part_aptamer_commands as commands, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.routes_design_interchange import AptamerImportRequest, import_aptamer_design
from backend.core.models import Design
from backend.core.part_input_sources import EmbeddedInput, SourceContractError
from tests.test_part_aptamer_commands import tiny_pdb


@pytest.fixture(autouse=True)
def document(monkeypatch):
    token = set_current_doc("aptamer-native-route")
    monkeypatch.setattr(commands, "NATIVE_ROUTE_ENABLED", True)
    try:
        state.load_design(None)
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def import_one(**params):
    return import_aptamer_design(AptamerImportRequest(content=tiny_pdb(), **params))


def test_first_import_pins_source_creates_explicit_empty_root_and_one_undo():
    revision = state.revision()
    result = import_one(name="Authored name", expected_revision=revision)
    design = state.get_or_404()
    assert design.recipe_root.kind == "empty"
    assert design.recipe_root.initial_name == "Authored name"
    assert design.metadata.tags == ["aptamer", "G4", "K+"]
    assert state.revision() == revision + 1
    assert state.undo_depth() == 1
    assert len(design.input_sources) == len(design.feature_log) == 1
    params = design.feature_log[0].params
    assert params["initialize_metadata"] is True
    assert params["source_label"] == "local PDB"
    assert "content" not in params and "template_id" not in params
    assert params["source"]["sha256"] in design.input_sources
    assert result["import_warnings"]
    state.undo()
    empty = state.get_or_404()
    assert not empty.helices and not empty.feature_log and not empty.input_sources
    assert empty.recipe_root == design.recipe_root
    state.redo()
    assert state.get_or_404().helices == design.helices
    assert state.get_or_404().input_sources == design.input_sources


def test_repeated_imports_deduplicate_bytes_and_keep_independent_identities():
    import_one()
    first = state.get_or_404()
    import_one()
    second = state.get_or_404()
    assert len(second.input_sources) == 1
    assert len(second.feature_log) == len(second.helices) == len(second.strands) == 2
    assert len({item.id for item in second.cluster_transforms}) == 2
    assert second.helices[0] == first.helices[0]
    assert second.feature_log[1].params["initialize_metadata"] is False
    assert second.metadata == first.metadata


def test_existing_legacy_document_does_not_acquire_an_empty_root_or_metadata():
    state.load_design(Design(metadata={"name": "Existing", "tags": ["preserve"]}))
    import_one(name="Source name")
    design = state.get_or_404()
    assert design.recipe_root is None
    assert design.metadata.name == "Existing" and design.metadata.tags == ["preserve"]
    assert design.feature_log[0].params["initialize_metadata"] is False


def test_selected_bundled_source_records_exact_name_and_provenance():
    from backend.core.aptamer import CATALOG, template_content
    from backend.core.part_input_sources import EmbeddedResolver, InputSource

    import_aptamer_design(AptamerImportRequest(template_id="148D", name="ignored override"))
    design = state.get_or_404()
    params = design.feature_log[0].params
    entry = next(row for row in CATALOG if row["id"] == "148D")
    assert params["name"] == entry["name"]
    assert params["source_label"] == entry["url"]
    assert EmbeddedResolver(design.input_sources)(InputSource.model_validate(params["source"])) == template_content("148D").encode()


def test_first_import_stale_revision_and_native_failure_are_atomic(monkeypatch):
    revision = state.revision()
    with pytest.raises(HTTPException) as caught:
        import_one(expected_revision=revision - 1)
    assert caught.value.status_code == 409
    assert state.get_design() is None and state.revision() == revision

    def reject(_kind, _design, params, **_kwargs):
        from backend.core.part_input_sources import InputSource
        raise SourceContractError("Refuse native evaluation", code="source_limit",
                                  source=InputSource.model_validate(params["source"]))

    monkeypatch.setattr(commands, "build", reject)
    with pytest.raises(HTTPException) as caught:
        import_one()
    assert caught.value.status_code == 413
    assert state.get_design() is None and state.revision() == revision and state.undo_depth() == 0


def test_retained_corrupt_source_is_not_silently_replaced():
    import_one()
    design = state.get_or_404()
    digest = next(iter(design.input_sources))
    design.input_sources[digest] = EmbeddedInput(data_b64="AAAA")
    before, revision = design.model_dump_json(), state.revision()
    with pytest.raises(HTTPException) as caught:
        import_one()
    assert caught.value.status_code == 422
    assert state.get_or_404().model_dump_json() == before and state.revision() == revision


def test_multi_chain_import_remains_legacy_without_a_false_native_receipt():
    import_aptamer_design(AptamerImportRequest(content=tiny_pdb() + "TER\n" + tiny_pdb()))
    design = state.get_or_404()
    assert len(design.strands) == 2
    assert design.recipe_root is None and not design.input_sources
    assert "aptamer_version" not in design.feature_log[0].params


def test_unmeasured_route_gate_preserves_legacy_compatibility(monkeypatch):
    monkeypatch.setattr(commands, "NATIVE_ROUTE_ENABLED", False)
    import_one()
    assert state.get_or_404().recipe_root is None
    assert "aptamer_version" not in state.get_or_404().feature_log[0].params


def test_legacy_first_import_encoding_failure_leaves_no_partial_document(monkeypatch):
    monkeypatch.setattr(commands, "NATIVE_ROUTE_ENABLED", False)
    revision = state.revision()

    def fail_encoding(_design):
        raise RuntimeError("encoding failed")

    monkeypatch.setattr(state, "encode_design_snapshot", fail_encoding)
    with pytest.raises(RuntimeError, match="encoding failed"):
        import_one()
    assert state.get_design() is None
    assert state.revision() == revision and state.undo_depth() == 0
