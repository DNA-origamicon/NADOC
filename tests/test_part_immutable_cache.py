"""Typed strict cache bytes in pytest-owned directories, never live workspaces."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import os
import struct

import pytest

from backend.api import part_immutable_cache as cache
from backend.api.part_immutable_revision import is_prepared_revision, prepare_revision
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def store(tmp_path):
    return cache.StrictPartCache(tmp_path)


@pytest.fixture
def revision():
    return prepare_revision(create_empty_part("Saved strict part", "HONEYCOMB"))


def path(store, doc="strict-doc"):
    return store.directory / cache._record_name(doc)


def saved(store, revision, doc="strict-doc"):
    return store.write(store.acquire_absent(doc), revision)


def raw_record(store, manifest, payload, *, doc="strict-doc", raw_manifest=None, magic=None):
    store.directory.mkdir(exist_ok=True)
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
           if raw_manifest is None else raw_manifest)
    path(store, doc).write_bytes((cache._MAGIC if magic is None else magic) + struct.pack("!I", len(raw)) + raw + payload)


def manifest_for(payload, doc="strict-doc"):
    return {"storage_version": 1, "doc_id": doc, "payload_bytes": len(payload),
            "payload_sha256": sha256(payload).hexdigest()}


def test_full_record_roundtrip_has_exact_design_bytes_and_no_authority(store, revision, tmp_path):
    first = saved(store, revision)
    result = store.read("strict-doc")
    assert result.payload == revision.payload
    assert result.manifest.doc_id == "strict-doc"
    assert result.manifest.payload_bytes == len(revision.payload)
    assert result.manifest.payload_sha256 == sha256(revision.payload).hexdigest()
    assert result.lease is not first and not is_prepared_revision(result)
    assert not (tmp_path / ".session").exists()
    assert list(store.directory.iterdir()) == [path(store)]
    discovery = store.discover()
    assert discovery.manifests == (result.manifest,) and discovery.issues == ()
    with pytest.raises(FrozenInstanceError):
        result.manifest.doc_id = "other"


def test_default_document_uses_exact_hashed_namespace_without_legacy_collision(store, revision):
    saved(store, revision, "__default__")
    assert path(store, "__default__").name == sha256(b"__default__").hexdigest() + ".partcache"
    assert store.read("__default__").manifest.doc_id == "__default__"


@pytest.mark.parametrize("doc", [".", "..", "a/b", "a?b", "x" * 81, "", None])
def test_unsafe_identity_refuses_before_namespace_creation(store, doc):
    with pytest.raises(ValueError):
        store.acquire_absent(doc)
    assert not store.directory.exists()


def test_pending_record_blocks_fresh_empty_even_when_record_is_unreadable(store):
    store.directory.mkdir()
    path(store).write_bytes(b"prior durable content")
    with pytest.raises(CommandContractError) as error:
        store.acquire_absent("strict-doc")
    assert error.value.code == "strict_cache_pending"
    assert path(store).read_bytes() == b"prior durable content"


def test_existing_record_requires_matching_store_owned_lease(store, revision, tmp_path):
    saved(store, revision)
    foreign = cache.StrictPartCache(tmp_path).read("strict-doc").lease
    with pytest.raises(CommandContractError) as error:
        store.write(foreign, revision)
    assert error.value.code == "strict_cache_changed"
    with pytest.raises(TypeError):
        cache.CacheLease()
    with pytest.raises(CommandContractError):
        store.write({"doc_id": "strict-doc"}, revision)


def test_write_accepts_no_mutable_design_or_saved_receipt(store):
    lease = store.acquire_absent("strict-doc")
    for value in (create_empty_part("Mutable input", "HONEYCOMB"), {"status": "verified"}, b"saved bytes"):
        with pytest.raises(CommandContractError):
            store.write(lease, value)
    assert not list(store.directory.iterdir())


def test_stale_lease_cannot_replace_a_later_same_bytes_revision(store, revision):
    first = saved(store, revision)
    second = store.write(first, revision)
    before = path(store).read_bytes()
    with pytest.raises(CommandContractError) as error:
        store.write(first, revision)
    assert error.value.code == "strict_cache_changed"
    assert path(store).read_bytes() == before
    assert store.write(second, revision) is not second


def test_explicit_file_lease_recheck_admits_only_the_observed_state(store, revision):
    absent = store.acquire_absent("strict-doc")
    assert store.assert_current(absent) is None
    current = store.write(absent, revision)
    assert store.assert_current(current) is None
    with pytest.raises(CommandContractError) as error:
        store.assert_current(absent)
    assert error.value.code == "strict_cache_changed"
    store.write(current, revision)
    with pytest.raises(CommandContractError) as error:
        store.assert_current(current)
    assert error.value.code == "strict_cache_changed"


def test_content_appearing_after_absent_admission_is_never_overwritten(store, revision):
    lease = store.acquire_absent("strict-doc")
    path(store).write_bytes(b"other process pending content")
    with pytest.raises(CommandContractError) as error:
        store.write(lease, revision)
    assert error.value.code == "strict_cache_changed"
    assert path(store).read_bytes() == b"other process pending content"


def test_inplace_external_change_invalidates_prior_file_lease(store, revision):
    lease = saved(store, revision)
    data = bytearray(path(store).read_bytes())
    data[-1] ^= 1
    path(store).write_bytes(data)
    with pytest.raises(CommandContractError) as error:
        store.write(lease, revision)
    assert error.value.code == "strict_cache_changed"
    assert path(store).read_bytes() == data


def test_atomic_replace_failure_preserves_previous_complete_record_and_cleans_only_own_temp(
        store, revision, monkeypatch):
    lease = saved(store, revision)
    before = path(store).read_bytes()

    def refuse(*args, **kwargs):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(cache.os, "replace", refuse)
    with pytest.raises(CommandContractError):
        store.write(lease, revision)
    assert path(store).read_bytes() == before
    assert list(store.directory.iterdir()) == [path(store)]


def test_first_link_failure_leaves_no_partial_record(store, revision, monkeypatch):
    lease = store.acquire_absent("strict-doc")

    def refuse(*args, **kwargs):
        raise OSError("injected first publication failure")

    monkeypatch.setattr(cache.os, "link", refuse)
    with pytest.raises(CommandContractError):
        store.write(lease, revision)
    assert not list(store.directory.iterdir())


def test_failure_after_first_link_keeps_record_and_cleans_only_owned_temporary(store, revision, monkeypatch):
    lease = store.acquire_absent("strict-doc")
    original = os.unlink
    calls = []

    def fail_once(name, **kwargs):
        calls.append(name)
        if len(calls) == 1:
            raise OSError("injected failure after link publication")
        return original(name, **kwargs)

    monkeypatch.setattr(cache.os, "unlink", fail_once)
    with pytest.raises(CommandContractError):
        store.write(lease, revision)
    assert store.read("strict-doc").payload == revision.payload
    assert list(store.directory.iterdir()) == [path(store)]


@pytest.mark.parametrize("action", ["read", "discover", "acquire_absent", "write"])
def test_contended_directory_lease_refuses_without_waiting(store, revision, action):
    import fcntl

    lease = saved(store, revision)
    descriptor = os.open(store.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(CommandContractError) as error:
            if action == "write":
                store.write(lease, revision)
            elif action == "discover":
                store.discover()
            else:
                getattr(store, action)("strict-doc")
        assert error.value.code == "strict_cache_busy"
    finally:
        os.close(descriptor)
    assert store.read("strict-doc").payload == revision.payload


@pytest.mark.parametrize("fail_after_publish", [False, True])
def test_fsync_failure_preserves_complete_durable_record_or_absence(
        store, revision, monkeypatch, fail_after_publish):
    lease = store.acquire_absent("strict-doc")
    original = os.fsync
    calls = []

    def fail(descriptor):
        calls.append(descriptor)
        if len(calls) == (2 if fail_after_publish else 1):
            raise OSError("injected fsync failure")
        return original(descriptor)

    monkeypatch.setattr(cache.os, "fsync", fail)
    with pytest.raises(CommandContractError):
        store.write(lease, revision)
    if fail_after_publish:
        assert store.read("strict-doc").payload == revision.payload
        with pytest.raises(CommandContractError) as error:
            store.acquire_absent("strict-doc")
        assert error.value.code == "strict_cache_pending"
    else:
        assert not path(store).exists()
    assert all(item.name.endswith(".partcache") for item in store.directory.iterdir())


@pytest.mark.parametrize("field,value", [
    ("storage_version", 2), ("storage_version", True), ("payload_bytes", True),
    ("payload_bytes", -1), ("payload_bytes", cache.MAX_CANDIDATE_BYTES + 1),
    ("payload_sha256", "bad"), ("doc_id", "different-doc"), ("doc_id", "../outside"),
    ("unexpected", "saved authority"),
])
def test_manifest_contract_refuses_without_decoding_or_removing_payload(store, field, value):
    payload = b"not a Design parser input"
    manifest = manifest_for(payload)
    manifest[field] = value
    raw_record(store, manifest, payload)
    before = path(store).read_bytes()
    with pytest.raises(CommandContractError):
        store.read("strict-doc")
    assert path(store).read_bytes() == before


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"storage_version":1,"storage_version":1}', b"{" + b" " * 4096 + b"}"])
def test_bad_manifest_is_bounded_and_preserved(store, raw):
    raw_record(store, {}, b"x", raw_manifest=raw)
    before = path(store).read_bytes()
    with pytest.raises(CommandContractError):
        store.read("strict-doc")
    assert path(store).read_bytes() == before


def test_noncanonical_manifest_representation_is_not_silently_normalized(store):
    payload = b"untrusted source bytes"
    manifest = manifest_for(payload)
    raw_record(store, manifest, payload, raw_manifest=json.dumps(manifest, indent=2).encode())
    with pytest.raises(CommandContractError) as error:
        store.read("strict-doc")
    assert error.value.code == "strict_cache_invalid"


def test_oversized_record_is_refused_before_manifest_decode(store, revision, monkeypatch):
    saved(store, revision)
    monkeypatch.setattr(cache, "MAX_CANDIDATE_BYTES", 1)
    monkeypatch.setattr(cache, "MAX_MANIFEST_BYTES", 1)
    monkeypatch.setattr(cache, "_parse_manifest", lambda *a: pytest.fail("Oversized record reached JSON decoding"))
    with pytest.raises(CommandContractError):
        store.read("strict-doc")
    assert path(store).exists()


@pytest.mark.parametrize("change", ["digest", "truncated", "extra", "magic", "header"])
def test_malformed_record_never_becomes_a_restore_input(store, revision, change):
    saved(store, revision)
    data = path(store).read_bytes()
    if change == "digest":
        data = data[:-1] + bytes([data[-1] ^ 1])
    elif change == "truncated":
        data = data[:-1]
    elif change == "extra":
        data += b"extra"
    elif change == "magic":
        data = b"wrong" + data[5:]
    else:
        data = cache._MAGIC + b"\0"
    path(store).write_bytes(data)
    with pytest.raises(CommandContractError):
        store.read("strict-doc")
    assert path(store).read_bytes() == data


def test_namespace_symlink_cannot_read_or_write_outside_workspace(store, revision, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store.directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(CommandContractError):
        store.acquire_absent("strict-doc")
    with pytest.raises(CommandContractError):
        store.discover()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "hardlink"])
def test_nonexclusive_regular_record_cannot_escape_or_block_read(store, tmp_path, kind):
    store.directory.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"sentinel")
    if kind == "symlink":
        path(store).symlink_to(outside)
    elif kind == "directory":
        path(store).mkdir()
    elif kind == "fifo":
        os.mkfifo(path(store))
    else:
        os.link(outside, path(store))
    with pytest.raises(CommandContractError):
        store.read("strict-doc")
    assert outside.read_bytes() == b"sentinel"
    assert store.discover().issues and path(store).exists()


def test_unknown_files_are_reported_preserved_and_consume_new_record_admission(store, revision, monkeypatch):
    store.directory.mkdir()
    pending = store.directory / ".write-interrupted"
    pending.write_bytes(b"unfinished prior work")
    monkeypatch.setattr(cache, "MAX_RECORDS", 1)
    discovery = store.discover()
    assert not discovery.manifests and discovery.issues[0]["record"] == pending.name
    with pytest.raises(CommandContractError) as error:
        store.acquire_absent("strict-doc")
    assert error.value.code == "strict_cache_limit"
    assert pending.read_bytes() == b"unfinished prior work"


def test_oversized_inventory_refuses_without_pruning(store, monkeypatch):
    store.directory.mkdir()
    for name in ("one", "two", "three"):
        (store.directory / name).write_bytes(name.encode())
    monkeypatch.setattr(cache, "MAX_RECORDS", 2)
    with pytest.raises(CommandContractError) as error:
        store.discover()
    assert error.value.code == "strict_cache_limit"
    assert sorted(item.name for item in store.directory.iterdir()) == ["one", "three", "two"]


def test_discovery_does_not_create_an_absent_namespace(store):
    assert store.discover() == cache.Discovery((), ())
    assert not store.directory.exists()
