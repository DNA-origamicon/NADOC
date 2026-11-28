"""Assembly-owned file revisions survive external edits, replay, and undo."""

import pytest
from fastapi import HTTPException

from backend.api import assembly_state, state, crud
from backend.api.assembly import (
    AddInstanceRequest, PatchInstanceDesignRequest, add_instance, patch_instance_design,
    _load_design_from_source,
)
from backend.core.assembly_flatten import _load_design
from backend.core.assembly_source_versions import design_digest
from backend.core.models import Assembly
from scripts.agent_structure_guard import publish
from tests.test_assembly_command_replay import replay_saved


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session()
    state.close_session()
    yield
    assembly_state.close_session()
    state.close_session()


def authored_part(length):
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=length))
    return state.get_or_404().model_copy(deep=True)


def test_file_revision_replacement_never_overwrites_source_and_undo_is_complete(tmp_path):
    original = authored_part(21)
    path = tmp_path / '__e2e__pinned.nadoc'
    publish(original, path)
    raw = path.read_bytes()
    root = Assembly()
    assembly_state.load_assembly(root)
    add_instance(AddInstanceRequest(source={'type': 'file', 'path': str(path)}))
    first = assembly_state.get_or_404().instances[0]
    assert first.source.revision == original
    assert first.source.revision_sha256 == design_digest(original)
    before = assembly_state.get_or_404().model_copy(deep=True)
    replacement = authored_part(42)
    patch_instance_design(first.id, PatchInstanceDesignRequest(content=replacement.to_json()))
    after = assembly_state.get_or_404()
    from backend.core.assembly_polymer import _sources_match
    assert not _sources_match(first.source, after.instances[0].source)
    assert path.read_bytes() == raw
    assert _load_design_from_source(after.instances[0].source) == replacement
    assert _load_design(after.instances[0].source) == replacement
    assert after.feature_log[-1].op_kind == 'assembly-replace-instance-source'
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert _load_design(assembly_state.get_or_404().instances[0].source) == original
    assert assembly_state.redo() == after
    # Disappearing external files cannot invalidate the pinned saved recipe.
    moved = tmp_path / '__e2e__moved.nadoc'
    path.rename(moved)
    reopened = Assembly.from_json(after.to_json())
    assert _load_design(reopened.instances[0].source) == replacement
    replay_saved(root, reopened)


def test_inline_replacement_stays_inline_and_failed_replace_is_atomic():
    root = Assembly()
    assembly_state.load_assembly(root)
    design = authored_part(21)
    add_instance(AddInstanceRequest(source={'type': 'inline', 'design': design.model_dump(mode='json')}))
    instance = assembly_state.get_or_404().instances[0]
    before, revision = assembly_state.copy_for_persist()
    with pytest.raises(HTTPException):
        patch_instance_design(instance.id, PatchInstanceDesignRequest(content='invalid'))
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision
    replacement = authored_part(42)
    patch_instance_design(instance.id, PatchInstanceDesignRequest(content=replacement.to_json()))
    after = assembly_state.get_or_404()
    assert after.instances[0].source.type == 'inline'
    replay_saved(root, after)
    assert assembly_state.undo() == before


def test_pinned_digest_mismatch_is_rejected_by_both_source_readers(tmp_path):
    design = authored_part(21)
    path = tmp_path / '__e2e__integrity.nadoc'
    publish(design, path)
    assembly_state.load_assembly(Assembly())
    add_instance(AddInstanceRequest(source={'type': 'file', 'path': str(path)}))
    source = assembly_state.get_or_404().instances[0].source.model_copy(update={'revision_sha256': 'wrong'})
    from backend.core.models import PartSourceFile
    with pytest.raises(ValueError, match='digest'):
        PartSourceFile.model_validate(source.model_dump(mode='json'))
    with pytest.raises(HTTPException, match='digest'):
        _load_design_from_source(source)
    with pytest.raises(ValueError, match='digest'):
        _load_design(source)
