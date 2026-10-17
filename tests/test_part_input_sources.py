"""Pinned inputs remain portable and cannot fall back to a changed local asset."""

import base64

import pytest
from pydantic import ValidationError

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import (
    EmbeddedInput, EmbeddedResolver, InputSource, SourceContractError, decode, describe, embed, verify,
)
from backend.core.project_revisions import ProjectRevisionStore


@pytest.fixture
def source():
    return describe(b"ATOM source\n", format="pdb", media_type="chemical/x-pdb")


def test_portable_source_round_trip_without_a_library_or_store(source):
    blob = embed(source, b"ATOM source\n")
    restored = EmbeddedInput.model_validate_json(blob.model_dump_json())
    descriptor = InputSource.model_validate_json(source.model_dump_json())
    table = {source.sha256: restored}
    resolver = EmbeddedResolver(table)
    table.clear()
    assert resolver(descriptor) == b"ATOM source\n"
    with pytest.raises(ValidationError):
        restored.data_b64 = "changed"


@pytest.mark.parametrize("patch", [
    {"version": True}, {"version": 2}, {"size_bytes": True}, {"size_bytes": -1},
    {"size_bytes": 50_000_001}, {"sha256": "../source"}, {"sha256": "A" * 64},
    {"format": "../../pdb"}, {"media_type": "file:///source"}, {"path": "/source"},
    {"url": "https://example.org/source"},
])
def test_descriptor_is_strict_data_without_location_or_code(source, patch):
    with pytest.raises(ValidationError):
        InputSource.model_validate({**source.model_dump(), **patch})


@pytest.mark.parametrize("data", [b"ATOM change\n", b"short", b"ATOM source\nextra"])
def test_mismatched_bytes_have_repairable_source_identity(source, data):
    with pytest.raises(SourceContractError) as error:
        verify(source, data)
    assert error.value.code == "source_integrity_mismatch"
    assert error.value.status == "unverified"
    assert error.value.as_issue()["references"] == [{
        "kind": "input_source", "identity": source.sha256, "parameter_path": ["source"],
    }]


def test_missing_bytes_do_not_search_by_name(source):
    with pytest.raises(SourceContractError) as error:
        EmbeddedResolver({})(source)
    assert error.value.code == "source_unavailable"
    assert error.value.status == "unverified"


@pytest.mark.parametrize("encoded", ["%%%%", "YQ==\n", "YR=="])
def test_malformed_or_noncanonical_embedding_rejected(encoded):
    one = describe(b"a", format="pdb", media_type="chemical/x-pdb")
    with pytest.raises(SourceContractError):
        decode(one, EmbeddedInput(data_b64=encoded))


def test_unexpected_decoded_size_is_rejected(source):
    blob = EmbeddedInput(data_b64=base64.b64encode(b"a" * 10).decode())
    with pytest.raises(SourceContractError):
        decode(source, blob)


def test_staging_is_idempotent_and_never_advances_a_branch(tmp_path, source):
    store = ProjectRevisionStore(tmp_path)
    path = store.stage_input("part", source, b"ATOM source\n")
    assert store.stage_input("part", source, b"ATOM source\n") == path
    assert store.read_input("part", source) == b"ATOM source\n"
    assert store.branch_head("part", "main") is None
    assert [p.name for p in path.parent.iterdir()] == [source.sha256 + ".blob"]
    assert not list(path.parent.glob("*.tmp"))


def test_only_verified_bytes_can_restore_a_corrupt_cache(tmp_path, source):
    store = ProjectRevisionStore(tmp_path)
    path = store.stage_input("part", source, b"ATOM source\n")
    path.write_bytes(b"ATOM change\n")
    with pytest.raises(SourceContractError):
        store.read_input("part", source)
    with pytest.raises(SourceContractError):
        store.stage_input("part", source, b"unverified replacement")
    assert path.read_bytes() == b"ATOM change\n"
    store.stage_input("part", source, b"ATOM source\n")
    assert store.read_input("part", source) == b"ATOM source\n"


def test_missing_store_object_reports_source_dependency(tmp_path, source):
    with pytest.raises(SourceContractError) as error:
        ProjectRevisionStore(tmp_path).read_input("part", source)
    assert error.value.code == "source_unavailable"


@pytest.mark.parametrize("project", ["../outside", "part/subdir", ""])
def test_input_paths_cannot_escape_project(tmp_path, source, project):
    with pytest.raises(ValueError):
        ProjectRevisionStore(tmp_path).stage_input(project, source, b"ATOM source\n")
    assert not (tmp_path / ".nadoc-projects").exists()


def test_bad_admission_does_not_leave_a_partial_store(tmp_path, source):
    with pytest.raises(SourceContractError):
        ProjectRevisionStore(tmp_path).stage_input("part", source, b"wrong")
    assert not (tmp_path / ".nadoc-projects").exists()


def test_store_io_error_is_unverified_source_availability(tmp_path, source):
    store = ProjectRevisionStore(tmp_path)
    store.input_path("part", source.sha256).mkdir(parents=True)
    with pytest.raises(SourceContractError) as error:
        store.read_input("part", source)
    assert error.value.code == "source_unavailable"
    assert error.value.status == "unverified"


def test_resolver_bounds_aggregate_sources_before_copy_or_decode(source):
    blob = embed(source, b"ATOM source\n")
    with pytest.raises(CommandContractError) as error:
        EmbeddedResolver({source.sha256: blob}, max_encoded_bytes=1)
    assert error.value.code == "source_limit"
    with pytest.raises(ValueError, match="digests"):
        EmbeddedResolver({"../../source": blob})


@pytest.mark.parametrize("kind", ["protein-import", "aptamer-import", "cadnano-import"])
def test_portable_closure_uses_the_same_normalized_receipts_as_proof(source, kind):
    from backend.core.models import Design, MinorMutationLogEntry, RoutingClusterLogEntry
    from backend.core.part_input_sources import portable_sources

    child = MinorMutationLogEntry.model_construct(op_subtype=kind, params={
        "_proof_version": 1, "source": source.model_dump()})
    design = Design(feature_log=[RoutingClusterLogEntry(children=[child])])
    with pytest.raises(SourceContractError) as error:
        portable_sources(design)
    assert error.value.code == "source_unavailable"
    design.input_sources = {source.sha256: embed(source, b"ATOM source\n")}
    assert portable_sources(design) == {source.sha256: source}
