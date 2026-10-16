"""Typed autosave ownership; temporary files only, no lifespan/cache thread."""

from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api import doc_context, session_cache, state
from backend.api import part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api import part_immutable_persistence as persistence
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def document(tmp_path, monkeypatch):
    doc = "__persist__" + uuid4().hex
    previous = policy.current_configuration()
    owner = persistence.StrictPersistence(tmp_path)
    with ExitStack() as cleanup:
        token = doc_context.set_current_doc(doc)
        cleanup.callback(doc_context.reset_current_doc, token)
        cleanup.callback(state.configure_part_publication_policy, previous)
        cleanup.callback(state.drop_doc, doc)
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode=previous.default_mode,
            document_modes={**previous.document_modes, doc: "registered_only"}))
        monkeypatch.setattr(session_cache, "_session_dir", tmp_path / ".session")
        monkeypatch.setattr(session_cache, "_strict_persistence", owner)
        monkeypatch.setattr(session_cache, "_last_flushed", {})
        monkeypatch.setattr(session_cache, "_seen", {})
        monkeypatch.setattr(session_cache, "_stable_since", None)
        yield doc, owner


def initialize(doc, owner):
    source, _revision = host.create_immutable_empty("Durable part", "HONEYCOMB")
    captured = persistence.capture_immutable(doc)
    owner.write_initial(captured, owner.reserve_empty(doc))
    return source, captured


def changed(source):
    candidate = revisions.materialize_revision(source)
    candidate.annotations_enabled = not candidate.annotations_enabled
    return revisions.prepare_revision(candidate)


def legacy_file(doc):
    directory = session_cache._doc_dir(doc)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / session_cache._DESIGN_FILE


def test_capture_retains_only_exact_handle_session_and_revision_without_copy(document, monkeypatch):
    doc, _owner = document
    source, revision = host.create_immutable_empty()
    monkeypatch.setattr(state, "_snapshot_copy", lambda *_a: pytest.fail("Immutable capture copied a model"))
    monkeypatch.setattr(revisions, "materialize_revision", lambda *_a: pytest.fail("Immutable capture decoded a model"))
    captured = persistence.capture_immutable(doc)
    assert captured.source is source and captured.revision == revision
    assert captured.session_identity == state._sessions[doc].identity
    assert captured.doc_id == doc


def test_absent_and_mutable_capture_use_existing_legacy_path_without_session_creation(document):
    doc, _owner = document
    assert persistence.capture_immutable(doc) is None and doc not in state._sessions
    source = state.create_empty_part("Legacy representation", "HONEYCOMB")
    assert persistence.capture_immutable(doc) is None and state.get_design() is source


def test_durable_write_runs_outside_state_lock_and_binds_no_mutable_model(document, monkeypatch):
    doc, owner = document
    source, _revision = host.create_immutable_empty()
    captured = persistence.capture_immutable(doc)
    original = owner.cache.write
    observed = []

    def write(*args):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        observed.append(True)
        return original(*args)

    monkeypatch.setattr(owner.cache, "write", write)
    owner.write_initial(captured, owner.reserve_empty(doc))
    assert observed == [True] and owner.read_pending(doc).payload == source.payload
    binding = owner._bindings[doc]
    assert binding.source() is source and not hasattr(binding, "design")


def test_newer_capture_writes_its_actual_revision_and_stale_capture_cannot_replace_it(document, monkeypatch):
    doc, owner = document
    source, first = initialize(doc, owner)
    latest = replace(first, source=changed(source), revision=first.revision + 2)
    assert owner.write_capture(latest) == latest.revision
    before = owner.read_pending(doc).payload
    monkeypatch.setattr(owner.cache, "write", lambda *_a: pytest.fail("Older snapshot rewrote newer durable bytes"))
    assert owner.write_capture(replace(first, revision=first.revision + 1)) == latest.revision
    assert owner.read_pending(doc).payload == before


def test_same_revision_different_handle_and_reopened_session_are_refused(document):
    doc, owner = document
    source, first = initialize(doc, owner)
    for capture in (replace(first, source=changed(source)), replace(first, session_identity="different-session")):
        with pytest.raises(CommandContractError):
            owner.write_capture(capture)
    assert owner.read_pending(doc).payload == source.payload


def test_unbound_internal_handle_does_not_implicitly_overwrite_pending_content(document):
    doc, owner = document
    source, first = initialize(doc, owner)
    other_owner = persistence.StrictPersistence(owner.cache.directory.parent)
    with pytest.raises(CommandContractError) as error:
        other_owner.write_capture(first)
    assert error.value.code == "strict_cache_unbound"
    assert other_owner.read_pending(doc).payload == source.payload


def test_busy_host_writer_refuses_without_waiting_on_file_io(document):
    doc, owner = document
    _source, capture = initialize(doc, owner)
    owner._lock.acquire()
    try:
        with pytest.raises(CommandContractError) as error:
            owner.write_capture(capture)
        assert error.value.code == "strict_cache_busy"
    finally:
        owner._lock.release()


def test_file_binding_checks_exact_payload_without_granting_host_publication(document):
    doc, owner = document
    source, first = initialize(doc, owner)
    other = persistence.StrictPersistence(owner.cache.directory.parent)
    stored = other.read_pending(doc)
    with pytest.raises(CommandContractError) as error:
        other.bind_qualified_record(replace(first, source=changed(source)), stored.lease)
    assert error.value.code == "strict_cache_changed" and not other._bindings
    other.bind_qualified_record(first, stored.lease)
    assert state._sessions[doc].design is source and state._sessions[doc].revision == first.revision
    assert not state._sessions[doc].history


def test_failed_publication_after_initial_durable_write_keeps_pending_record(document):
    doc, owner = document
    source, _first = initialize(doc, owner)
    state.drop_doc(doc)
    assert owner.read_pending(doc).payload == source.payload
    with pytest.raises(CommandContractError) as error:
        owner.reserve_empty(doc)
    assert error.value.code == "strict_cache_pending" and doc not in state._sessions


def test_binding_admission_precedes_initial_write(document, monkeypatch):
    doc, owner = document
    host.create_immutable_empty()
    capture = persistence.capture_immutable(doc)
    absent = owner.reserve_empty(doc)
    monkeypatch.setattr(persistence, "MAX_RECORDS", 0)
    with pytest.raises(CommandContractError) as error:
        owner.write_initial(capture, absent)
    assert error.value.code == "strict_cache_limit"
    assert not list(owner.cache.directory.iterdir())


@pytest.mark.parametrize("revision", [True, 0, -1, "1"])
def test_invalid_capture_revision_refuses_before_file_write(document, monkeypatch, revision):
    doc, owner = document
    host.create_immutable_empty()
    capture = replace(persistence.capture_immutable(doc), revision=revision)
    monkeypatch.setattr(owner.cache, "write", lambda *_a: pytest.fail("Invalid capture reached a file write"))
    with pytest.raises(CommandContractError):
        owner.write_initial(capture, owner.reserve_empty(doc))


def test_typed_autosave_preserves_legacy_part_and_uses_no_old_snapshot(document, monkeypatch):
    doc, owner = document
    source, first = initialize(doc, owner)
    prior = legacy_file(doc)
    prior.write_bytes(b"prior legacy part must remain")
    monkeypatch.setattr(state, "copy_doc_for_persist", lambda *_a: pytest.fail("Strict autosave used mutable snapshot"))
    assert session_cache._write_doc(doc) == (first.revision, 0)
    assert prior.read_bytes() == b"prior legacy part must remain"
    assert owner.read_pending(doc).payload == source.payload


def test_autosave_marks_only_actual_captured_revision(document, monkeypatch):
    doc, owner = document
    _source, first = initialize(doc, owner)
    monkeypatch.setattr(session_cache, "_combined_revisions", lambda: {doc: (first.revision + 1, 0)})
    monkeypatch.setattr(session_cache, "_write_registry", lambda *_a: None)
    session_cache._flush(force=True)
    assert session_cache._last_flushed == {doc: (first.revision, 0)}


def test_busy_or_refused_write_stays_pending_and_unrelated_legacy_flush_continues(document, monkeypatch):
    doc, owner = document
    _source, first = initialize(doc, owner)
    other = "legacy-other"
    monkeypatch.setattr(session_cache, "_combined_revisions", lambda: {doc: (first.revision, 0), other: (2, 0)})
    monkeypatch.setattr(session_cache, "_write_registry", lambda *_a: None)
    monkeypatch.setattr(state, "copy_doc_for_persist", lambda identity: (None, 2))
    original = owner.write_if_immutable

    def busy(identity):
        if identity == doc:
            raise CommandContractError("Injected contention", code="strict_cache_busy")
        return original(identity)

    monkeypatch.setattr(owner, "write_if_immutable", busy)
    session_cache._flush(force=True)
    assert session_cache._last_flushed == {other: (2, 0)}
    monkeypatch.setattr(owner, "write_if_immutable", original)
    session_cache._flush(force=True)
    assert session_cache._last_flushed[doc] == (first.revision, 0)


def test_pending_typed_record_shadows_legacy_restore_before_design_decode(document, monkeypatch):
    doc, owner = document
    initialize(doc, owner)
    prior = legacy_file(doc)
    prior.write_bytes(b"old unparsed design")
    state.drop_doc(doc)
    monkeypatch.setattr(session_cache.Design, "from_json", lambda *_a: pytest.fail("Shadowed legacy bytes decoded"))
    assert session_cache.restore() == 0 and doc not in state._sessions
    assert prior.read_bytes() == b"old unparsed design"


@pytest.mark.parametrize("live_part", [False, True])
@pytest.mark.parametrize("live_assembly", [False, True])
def test_pending_typed_record_refuses_legacy_part_write_but_keeps_assembly_independent(
        document, monkeypatch, caplog, live_part, live_assembly):
    doc, owner = document
    source, _first = initialize(doc, owner)
    prior = legacy_file(doc)
    prior.write_bytes(b"preserved old legacy part")
    heads = prior.parent / session_cache._WORKSPACE_HEADS_FILE
    heads.write_bytes(b"preserved old workspace heads")
    assembly_path = prior.parent / session_cache._ASSEMBLY_FILE
    assembly_path.write_text("previous assembly")
    state.drop_doc(doc)
    config = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode=config.default_mode,
        document_modes={**config.document_modes, doc: "compatibility"}))
    if live_part:
        state.create_empty_part("New compatibility part", "HONEYCOMB")
    assembly = SimpleNamespace(to_json=lambda: "new independent assembly") if live_assembly else None
    monkeypatch.setattr(session_cache.assembly_state, "copy_doc_for_persist", lambda *_a: (assembly, 4))
    monkeypatch.setattr(state, "copy_doc_for_persist", lambda *_a: pytest.fail("Shadowed part was copied"))
    monkeypatch.setattr(state, "workspace_heads_for_doc", lambda *_a: pytest.fail("Shadowed workspace heads read"))
    assert session_cache._write_doc(doc) is False
    assert prior.read_bytes() == b"preserved old legacy part"
    assert heads.read_bytes() == b"preserved old workspace heads"
    assert owner.read_pending(doc).payload == source.payload
    if live_assembly:
        assert assembly_path.read_text() == "new independent assembly"
    else:
        assert not assembly_path.exists()
    assert "strict recovery must finish" in caplog.text


def test_corrupt_typed_record_blocks_legacy_restore_and_prune(document, monkeypatch):
    doc, owner = document
    owner.reserve_empty(doc)
    typed = owner.cache.directory / persistence._record_name(doc)
    typed.write_bytes(b"corrupt pending record")
    prior = legacy_file(doc)
    prior.write_bytes(b"preserved legacy fallback for explicit recovery")
    monkeypatch.setattr(session_cache.Design, "from_json", lambda *_a: pytest.fail("Unqualified fallback restored"))
    assert session_cache.restore() == 0
    assert session_cache._prune(now=10**12) == 0
    assert prior.exists() and typed.read_bytes() == b"corrupt pending record"


def test_oversized_discovery_does_not_turn_exact_pending_identity_into_absence(document, monkeypatch):
    doc, owner = document
    initialize(doc, owner)
    for index in range(3):
        (owner.cache.directory / f"unknown-{index}").write_bytes(b"preserved")
    from backend.api import part_immutable_cache
    monkeypatch.setattr(part_immutable_cache, "MAX_RECORDS", 2)
    with pytest.raises(CommandContractError):
        owner.discover()
    assert owner.shadows_legacy(doc)


def test_close_cleanup_keeps_typed_and_shadowed_legacy_part_files(document, monkeypatch):
    doc, owner = document
    source, first = initialize(doc, owner)
    prior = legacy_file(doc)
    prior.write_bytes(b"preserved legacy part")
    session_cache._last_flushed = {doc: (first.revision, 0)}
    state.drop_doc(doc)
    monkeypatch.setattr(session_cache, "_combined_revisions", lambda: {})
    session_cache._flush(force=True)
    assert prior.read_bytes() == b"preserved legacy part"
    assert owner.read_pending(doc).payload == source.payload


def test_missing_typed_namespace_leaves_ordinary_legacy_restore_and_prune_unchanged(document, monkeypatch):
    doc, owner = document
    # Policy is deliberately compatible for this ordinary legacy document.
    other = "__legacy_restore__" + uuid4().hex
    prior = legacy_file(other)
    model = create_empty_part("Legacy cached part", "HONEYCOMB")
    prior.write_text(model.to_json())
    try:
        assert not owner.cache.directory.exists()
        assert session_cache.restore() == 1
        assert state.peek_design(other).id == model.id
        monkeypatch.setattr(session_cache, "_MAX_DOCS", 0)
        assert session_cache._prune() == 1 and not prior.exists()
    finally:
        state.drop_doc(other)


def test_unavailable_typed_namespace_preserves_legacy_instead_of_assuming_absent(document, tmp_path, monkeypatch):
    doc, owner = document
    outside = tmp_path / "unavailable"
    outside.mkdir()
    owner.cache.directory.symlink_to(outside, target_is_directory=True)
    prior = legacy_file(doc)
    prior.write_bytes(b"legacy recovery bytes")
    monkeypatch.setattr(session_cache.Design, "from_json", lambda *_a: pytest.fail("Unavailable strict namespace fell back"))
    assert session_cache.restore() == 0
    assert session_cache._prune(now=10**12) == 0
    assert prior.read_bytes() == b"legacy recovery bytes" and list(outside.iterdir()) == []
