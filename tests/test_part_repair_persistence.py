"""Whole-document persistence keeps proposals and their available input bytes."""

from uuid import uuid4

import pytest

from backend.api import doc_context, session_cache, state
from backend.core.design_loadouts import decode_snapshot, encode_snapshot
from backend.core.models import Design, DesignLoadout
from backend.core.part_input_sources import describe, embed
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.project_revisions import ProjectRevisionStore
from tests.test_part_repair_document_boundaries import proposal, source


def portable_document(*, missing=False, generation=0, data=b"pinned proposed input"):
    design = source()
    selected = describe(data, format="blob", media_type="application/octet-stream")
    saved = proposal(generation=generation).model_dump(mode="json")
    saved["actions"][0].update(parameter_path=["source"], expected_old=None, value=selected.model_dump(mode="json"))
    return design.copy_with(repair_draft=RepairDraft.model_validate(saved),
        input_sources={} if missing else {selected.sha256: embed(selected, data)})


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("loader", ["json", "dict"])
def test_whole_document_roundtrip_retains_exact_proposal_and_available_bytes(missing, loader):
    design = portable_document(missing=missing)
    restored = Design.from_json(design.to_json()) if loader == "json" else Design.from_dict(design.to_dict())
    assert restored.repair_draft == design.repair_draft
    assert restored.input_sources == design.input_sources
    assert restored.repair_draft.base == design.repair_draft.base
    assert "revision" not in restored.repair_draft.model_dump()
    assert "status" not in restored.repair_draft.model_dump()


@pytest.fixture
def document():
    identity = f"__draft_persistence_test__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    try:
        yield identity
    finally:
        with state._lock:
            state._sessions.pop(identity, None)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def test_session_cache_roundtrip_keeps_draft_without_restoring_runtime_readiness(document, monkeypatch, tmp_path):
    design = portable_document()
    state.load_design(design)
    fingerprint = repair_base_fingerprint(design)
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path / "session")
    session_cache._write_doc(document)
    with state._lock:
        state._sessions.pop(document)
    assert session_cache.restore() == 1
    restored = state.get_or_404()
    assert restored is not design and restored.repair_draft == design.repair_draft
    assert restored.input_sources == design.input_sources
    assert repair_base_fingerprint(restored) == fingerprint
    assert restored.repair_draft.base == design.repair_draft.base
    assert state.undo_depth() == state.redo_depth() == 0


@pytest.mark.parametrize("missing", [False, True])
def test_loadout_snapshot_roundtrip_keeps_branch_proposal_and_missing_source_selection(missing):
    design = portable_document(missing=missing)
    encoded, _ = encode_snapshot(design)
    restored = decode_snapshot(encoded)
    assert restored.repair_draft == design.repair_draft
    assert restored.input_sources == design.input_sources
    assert restored.loadouts == [] and restored.active_loadout_id is None


def test_loadout_activation_restores_that_branch_draft_instead_of_carrying_current_proposal(document, monkeypatch):
    from backend.api import routes_design_loadouts as routes

    first = portable_document(generation=1)
    second = portable_document(missing=True, generation=4)
    loadouts = []
    for identity, design in (("first", first), ("second", second)):
        payload, size = encode_snapshot(design)
        loadouts.append(DesignLoadout(id=identity, name=identity, design_snapshot_gz_b64=payload, snapshot_size_bytes=size))
    state.load_design(first.copy_with(loadouts=loadouts, active_loadout_id="first"))
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda design, _report, **_kw: {"design_id": design.id})
    routes.select_loadout("second")
    assert state.get_or_404().repair_draft == second.repair_draft
    assert not state.get_or_404().input_sources
    routes.select_loadout("first")
    assert state.get_or_404().repair_draft == first.repair_draft
    assert state.get_or_404().input_sources == first.input_sources
    assert state.undo_depth() == state.redo_depth() == 0


def test_loadout_create_delete_active_undo_and_activate_keep_independent_drafts_and_sources(document, monkeypatch):
    from backend.api import routes_design_loadouts as routes

    first = portable_document(generation=1)
    second = portable_document(generation=4, data=b"different branch input")
    state.load_design(first)
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda design, _report, **_kw: {"design_id": design.id})
    routes.create_loadout(routes.LoadoutCreateBody(name="Second"))
    first_id, second_id = [item.id for item in state.get_or_404().loadouts]
    state.set_design_silent(state.get_or_404().copy_with(
        repair_draft=second.repair_draft, input_sources=second.input_sources))
    routes.select_loadout(first_id)
    assert state.get_or_404().repair_draft == first.repair_draft
    assert state.get_or_404().input_sources == first.input_sources
    routes.select_loadout(second_id)
    assert state.get_or_404().repair_draft == second.repair_draft
    assert state.get_or_404().input_sources == second.input_sources
    routes.delete_loadout(second_id)
    assert state.get_or_404().active_loadout_id == first_id
    assert state.get_or_404().repair_draft == first.repair_draft
    assert state.get_or_404().input_sources == first.input_sources
    state.undo()
    assert state.get_or_404().active_loadout_id == second_id
    assert state.get_or_404().repair_draft == second.repair_draft
    assert state.get_or_404().input_sources == second.input_sources
    routes.activate_last_editable_loadout()
    assert state.get_or_404().active_loadout_id == second_id
    assert state.get_or_404().repair_draft == second.repair_draft
    assert state.get_or_404().input_sources == second.input_sources


@pytest.mark.parametrize("missing", [False, True])
def test_content_addressed_project_revision_retains_draft_and_proposed_source_bytes(tmp_path, missing):
    design = portable_document(missing=missing)
    store = ProjectRevisionStore(tmp_path)
    revision = store.commit(design, loadout_id="main", loadout_name="Main",
                            parent_revision_id=None, expected_head=None)
    restored = store.load_design(design.id, revision.revision_id)
    assert restored.repair_draft == design.repair_draft
    assert restored.input_sources == design.input_sources
    assert not restored.loadouts
    # Editing only a proposal creates a distinct whole-document revision, but
    # leaves the published recipe/evidence fingerprint unchanged.
    edited = design.copy_with(repair_draft=design.repair_draft.model_copy(update={"generation": 1}))
    next_revision = store.commit(edited, loadout_id="main", loadout_name="Main",
        parent_revision_id=revision.revision_id, expected_head=revision.revision_id)
    assert next_revision.snapshot_sha256 != revision.snapshot_sha256
    assert repair_base_fingerprint(edited) == repair_base_fingerprint(design)


@pytest.mark.parametrize("mode", ["thin", "full"])
@pytest.mark.parametrize("missing", [False, True])
def test_portable_package_keeps_proposal_without_promoting_draft_only_missing_bytes_to_required_inputs(
    tmp_path, monkeypatch, mode, missing
):
    from backend.core import native_part_package as package

    design = portable_document(missing=missing)
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "part.nadoc").write_text(design.to_json())
    monkeypatch.setattr(package, "_job_classes", lambda: ())
    archive = tmp_path / "part.nadocpkg"
    manifest = package.create_package(workspace, "part.nadoc", archive, mode=mode)
    assert bool(manifest["authoring_inputs"]) is (not missing)
    destination = tmp_path / "destination"
    package.import_package(destination, archive, "part.nadoc")
    restored = Design.from_json((destination / "part.nadoc").read_text())
    assert restored.repair_draft == design.repair_draft
    assert restored.input_sources == design.input_sources


def test_save_as_identity_change_keeps_old_draft_base_until_explicit_rebase():
    original = portable_document()
    copied = Design.from_json(original.copy_with(id="new-part").to_json())
    assert copied.repair_draft.base_design_id == original.id
    assert copied.repair_draft.base_design_id != copied.id
