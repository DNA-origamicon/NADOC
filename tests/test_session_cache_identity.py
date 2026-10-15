"""ISSUE-88: cache identities must never alias or escape their document directory.

All deletion probes use only pytest-owned temporary files. No lifespan, cache
thread, existing workspace or user file participates in these regressions.
"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import part_publication_policy as policy, session_cache, state
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
from backend.api.part_strict_http import StrictPartDispatch


UNSAFE = [
    "", ".", "..", "../outside", "a/b", "a\\b", "a:b", "a?b", "a b", "é",
    "x" * 81, "x" * 80 + "one", "x" * 80 + "two", "\x00",
]


@pytest.mark.parametrize("doc_id", UNSAFE)
def test_unsafe_document_cache_identity_is_rejected_without_mapping(tmp_path, monkeypatch, doc_id):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path / ".session")
    with pytest.raises(ValueError, match="(?i)(document|cache).*identity"):
        session_cache._doc_dir(doc_id)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("doc_id", [
    "__default__", "shared-arm", "named.part_1", "__headless_build_1__",
    "__headless_oxdna_1__", "__headless_assembly_1__", "a" * 80,
    # Collection must be identical in every xdist worker. Both UUID spellings
    # are still real browser/headless identity shapes without random test IDs.
    "7ed758e1-02b7-4ebf-a5b1-9ce0327d08ea", "7ed758e102b74ebfa5b19ce0327d08ea",
])
def test_supported_document_cache_identity_is_preserved_exactly(tmp_path, monkeypatch, doc_id):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path)
    assert session_cache._doc_dir(doc_id) == tmp_path / doc_id


@pytest.mark.parametrize("doc_id", [None, False, 1, b"safe", [], {}, " safe", "safe ", "safe\n"])
def test_document_identity_rejects_noncanonical_types_and_whitespace(doc_id):
    with pytest.raises(UnsafeDocumentIdentity):
        require_document_identity(doc_id)


@pytest.mark.parametrize("unsafe,valid", [
    ("a/b", "a_b"), ("a?b", "a_b"),
    ("x" * 80 + "one", "x" * 80), ("x" * 80 + "two", "x" * 80),
])
def test_unsafe_removal_cannot_delete_a_colliding_valid_document(tmp_path, monkeypatch, unsafe, valid):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path)
    directory = tmp_path / valid
    directory.mkdir()
    retained = directory / session_cache._DESIGN_FILE
    retained.write_bytes(b"valid document must survive")
    with pytest.raises(ValueError, match="(?i)(document|cache).*identity"):
        session_cache._remove_doc_dir(unsafe)
    assert retained.read_bytes() == b"valid document must survive"


@pytest.mark.parametrize("unsafe", [".", ".."])
def test_dot_identity_cannot_remove_cache_root_or_parent_files(tmp_path, monkeypatch, unsafe):
    directory = tmp_path / ".session"
    directory.mkdir()
    monkeypatch.setattr(session_cache, "_session_dir", directory)
    root_file = directory / session_cache._DESIGN_FILE
    parent_file = tmp_path / session_cache._DESIGN_FILE
    root_file.write_bytes(b"root sentinel")
    parent_file.write_bytes(b"parent sentinel")
    with pytest.raises(ValueError, match="(?i)(document|cache).*identity"):
        session_cache._remove_doc_dir(unsafe)
    assert root_file.read_bytes() == b"root sentinel"
    assert parent_file.read_bytes() == b"parent sentinel"


def test_unsafe_cache_write_refuses_before_copying_any_document(tmp_path, monkeypatch):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path / ".session")

    def forbidden_capture(*args, **kwargs):
        pytest.fail("Unsafe document identity reached a state capture")

    monkeypatch.setattr(session_cache.design_state, "copy_doc_for_persist", forbidden_capture)
    monkeypatch.setattr(session_cache.assembly_state, "copy_doc_for_persist", forbidden_capture)
    with pytest.raises(ValueError, match="(?i)(document|cache).*identity"):
        session_cache._write_doc("../outside")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("removed", [False, True])
def test_unsafe_autosave_reports_unsupported_identity_and_continues_valid_flush(
        tmp_path, monkeypatch, caplog, removed):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path)
    monkeypatch.setattr(session_cache, "_last_flushed", {"a/b": (1, 0)} if removed else {})
    monkeypatch.setattr(session_cache, "_seen", {})
    monkeypatch.setattr(session_cache, "_stable_since", None)
    current = {"valid": (2, 0)} if removed else {"a/b": (1, 0), "valid": (2, 0)}
    monkeypatch.setattr(session_cache, "_combined_revisions", lambda: current)
    captures, registries = [], []

    def empty_capture(doc_id):
        captures.append(doc_id)
        return None, 0

    monkeypatch.setattr(session_cache.design_state, "copy_doc_for_persist", empty_capture)
    monkeypatch.setattr(session_cache.assembly_state, "copy_doc_for_persist", empty_capture)
    monkeypatch.setattr(session_cache, "_write_registry", lambda revisions: registries.append(dict(revisions)))
    session_cache._flush(force=True)
    assert captures == ["valid", "valid"]
    assert registries == [{"valid": (2, 0)}]
    assert "unsafe_document_identity" in caplog.text
    assert "autosave" in caplog.text.lower()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("doc_id", [".", "..", "a/b", "a?b", "x" * 81, "é"])
def test_strict_empty_creation_rejects_uncacheable_identity_before_session_creation(doc_id):
    previous = policy.current_configuration()
    assert doc_id not in state._sessions
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    try:
        with TestClient(StrictPartDispatch(FastAPI())) as client:
            result = client.post("/api/design/registered-empty", params={"doc": doc_id}, json={})
        assert result.status_code == 422
        assert result.json()["detail"]["code"] == "unsafe_document_identity"
        assert doc_id not in state._sessions
    finally:
        state.configure_part_publication_policy(previous)
        state.drop_doc(doc_id)


@pytest.mark.parametrize("doc_id", [".", "a/b", "x" * 81])
def test_strict_unsafe_identity_is_refused_before_receiving_body(doc_id):
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    sent = []

    async def forbidden_receive():
        pytest.fail("Unsafe document context acquired a request body")

    async def forbidden_fallback(*args):
        pytest.fail("Unsafe strict document context reached compatibility")

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/design/registered-empty",
        "query_string": b"", "headers": [(b"x-nadoc-doc", doc_id.encode()),
            (b"content-type", b"application/json")]}
    try:
        asyncio.run(StrictPartDispatch(forbidden_fallback)(scope, forbidden_receive, send))
        assert sent[0]["status"] == 422
        assert b"unsafe_document_identity" in sent[1]["body"]
        assert doc_id not in state._sessions
    finally:
        state.configure_part_publication_policy(previous)
