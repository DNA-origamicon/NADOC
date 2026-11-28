"""History evaluation must never expose candidates or disturb live undo state."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly_history_transaction import apply_history_change
from backend.core.models import Assembly


def renamed(assembly, name):
    return assembly.model_copy(update={"metadata": assembly.metadata.model_copy(update={"name": name})})


@pytest.fixture(autouse=True)
def session():
    assembly_state.close_session()
    assembly_state.load_assembly(Assembly())
    yield
    assembly_state.close_session()


def test_failed_evaluation_preserves_live_state_revision_and_redo():
    original = assembly_state.get_or_404()
    assembly_state.set_assembly(renamed(original, "second"))
    assembly_state.undo()
    source, revision = assembly_state.copy_for_persist()
    depths = assembly_state.undo_depth(), assembly_state.redo_depth()

    def evaluate():
        assembly_state.get_or_404().metadata.name = "in-place candidate"
        assembly_state.snapshot()
        assembly_state.remember_instance_display("example", visible=False)
        raise HTTPException(422, detail="downstream reference missing")

    with pytest.raises(HTTPException, match="downstream reference missing"):
        apply_history_change(evaluate)
    assert assembly_state.get_or_404() == source
    assert assembly_state.revision() == revision
    assert (assembly_state.undo_depth(), assembly_state.redo_depth()) == depths
    assert assembly_state.get_display_overrides() == {}


def test_other_context_sees_only_published_state_and_one_undo_step():
    source, revision = assembly_state.copy_for_persist()
    before_depth = assembly_state.undo_depth()

    def evaluate():
        assembly_state.set_assembly(renamed(assembly_state.get_or_404(), "candidate"))
        assembly_state.snapshot()
        with ThreadPoolExecutor(max_workers=1) as pool:
            observed = pool.submit(assembly_state.copy_for_persist).result()
        assert observed == (source, revision)

    result = apply_history_change(evaluate)
    assert result.metadata.name == "candidate"
    assert assembly_state.revision() == revision + 1
    assert assembly_state.undo_depth() == before_depth + 1
    assert assembly_state.undo() == source
    assert assembly_state.redo().metadata.name == "candidate"


def test_stale_candidate_does_not_overwrite_concurrent_edit():
    def evaluate():
        assembly_state.get_or_404().metadata.name = "candidate"
        with ThreadPoolExecutor(max_workers=1) as pool:
            def concurrent_edit():
                assembly_state.set_assembly(renamed(assembly_state.get_or_404(), "newer edit"))
            pool.submit(concurrent_edit).result()

    with pytest.raises(HTTPException) as error:
        apply_history_change(evaluate)
    assert error.value.status_code == 409
    assert assembly_state.get_or_404().metadata.name == "newer edit"


def test_legacy_in_place_mutation_also_invalidates_candidate():
    source, revision = assembly_state.copy_for_persist()
    assembly_state.get_or_404().metadata.name = "unversioned live change"
    with pytest.raises(HTTPException) as error:
        assembly_state.publish_candidate(source, source=source, expected_revision=revision)
    assert error.value.status_code == 409


def test_nested_evaluation_restores_outer_session_and_registry():
    original = assembly_state.get_or_404()
    registry = assembly_state.revision_map()
    with assembly_state.isolated_evaluation(original):
        assembly_state.get_or_404().metadata.name = "outer"
        outer = assembly_state.get_or_404()
        with assembly_state.isolated_evaluation(outer):
            assembly_state.get_or_404().metadata.name = "inner"
        assert assembly_state.get_or_404().metadata.name == "outer"
        assert assembly_state.revision_map() == registry
    assert assembly_state.get_or_404() is original
