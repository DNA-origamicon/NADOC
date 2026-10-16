"""Definition-only admission retains original invalid files without loading them."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest
from pydantic import ValidationError

from backend.core.models import Design, MinorMutationLogEntry, RoutingClusterLogEntry
from backend.core.part_input_sources import describe, embed, portable_sources
from tests.test_group_creation_v2 import grouping, row, source
from tests.test_part_deformation_preview import _append, native_source


def module():
    from backend.core import part_recipe_file
    return part_recipe_file


def encoded(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@pytest.fixture(scope="module")
def broken_bytes():
    original = source()
    broken = _append(original, row(grouping(original), 1))
    return broken.model_dump_json().encode()


@pytest.fixture
def document(broken_bytes):
    return json.loads(broken_bytes)


def reject(data, *, code="recipe_file_invalid"):
    with pytest.raises(module().RecipeFileError) as caught:
        module().admit_recipe_file(encoded(data))
    assert caught.value.code == code


def test_actual_saved_grouping_defect_still_fails_normal_load_but_definitions_are_admitted(broken_bytes):
    with pytest.raises(ValidationError, match="placement cluster is missing"):
        Design.from_json(broken_bytes.decode())
    admitted = module().admit_recipe_file(broken_bytes)
    assert admitted.original_bytes is broken_bytes
    assert admitted.original_sha256 == sha256(broken_bytes).hexdigest()
    assert admitted.source.feature_log[-1].proof_version == 1
    assert admitted.source.feature_log[-1].cluster_snapshot.id == admitted.source.feature_log[-1].cluster_id
    assert not admitted.source.helices and not admitted.source.strands and not admitted.source.lattice_frames
    assert not admitted.source.cluster_transforms
    assert Design.model_validate_json(admitted.source.model_dump_json()) == admitted.source
    assert admitted.source.recipe_root.initial_name == admitted.source.metadata.name
    assert admitted.source.id == json.loads(broken_bytes)["id"]


def test_never_calls_normal_loader_model_construct_or_any_saved_geometry_builder(document, monkeypatch):
    monkeypatch.setattr(Design, "from_json", lambda *_a, **_k: pytest.fail("Loaded invalid output"))
    monkeypatch.setattr(Design, "model_construct", lambda *_a, **_k: pytest.fail("Bypassed Design schema"))
    monkeypatch.setattr("backend.core.deformation.deformed_nucleotide_arrays",
                        lambda *_a, **_k: pytest.fail("Computed saved geometry"))
    document["helices"] = {"arbitrary": "invalid materialized geometry"}
    document["strands"] = [None, 17]
    document["metadata"] = {"name": "Unlogged replacement name"}
    document["loadouts"] = [{"snapshot_gz_b64": "not gzip"}]
    document["annotations"] = [{"unrecognized": "presentation payload"}]
    document["repair_draft"] = {"status": "ready", "candidate": "never authority"}
    raw = encoded(document)
    admitted = module().admit_recipe_file(raw)
    assert admitted.original_bytes == raw
    assert {"helices", "strands", "metadata", "loadouts", "annotations", "repair_draft"} <= set(admitted.excluded_fields)
    assert admitted.source.metadata.name == document["recipe_root"]["initial_name"]
    assert admitted.source.loadouts == [] and admitted.source.annotations == []
    assert admitted.source.repair_draft is None


def test_exclusion_inventory_reports_every_present_nonrecipe_field_including_empty(document):
    admitted = module().admit_recipe_file(encoded(document))
    retained = {"id", "recipe_root", "feature_log", "input_sources", "feature_log_cursor", "feature_log_sub_cursor"}
    assert admitted.excluded_fields == tuple(sorted(set(document) - retained))
    assert "crossovers" in admitted.excluded_fields


def test_snapshot_and_routing_recovery_payloads_are_stripped_only_at_declared_locations(document):
    snapshot = document["feature_log"][0]
    snapshot.update(design_snapshot_gz_b64={"poison": "not decoded"},
                    post_state_gz_b64="not gzip", snapshot_size_bytes=-10,
                    diff_removed_ids=[{"opaque": True}])
    snapshot["params"]["post_state_gz_b64"] = "a command input must not disappear"
    child = MinorMutationLogEntry(id="child", op_subtype="helix-update", label="Update",
                                 params={"_proof_version": 1, "helix_id": "missing"}).model_dump(mode="json")
    child["diff_added_b64"] = {"poison": True}
    group = RoutingClusterLogEntry(id="routing", children=[]).model_dump(mode="json")
    group.update(children=[child], pre_state_gz_b64=["poison"], post_state_gz_b64="bad")
    document["feature_log"].append(group)
    admitted = module().admit_recipe_file(encoded(document))
    saved = admitted.source.feature_log
    assert saved[0].design_snapshot_gz_b64 == "" and saved[0].snapshot_size_bytes == 0
    assert saved[0].post_state_gz_b64 == "" and saved[0].diff_removed_ids == []
    assert saved[0].params["post_state_gz_b64"] == "a command input must not disappear"
    assert saved[-1].pre_state_gz_b64 == "" and saved[-1].children[0].diff_added_b64 == ""
    assert ("feature_log", 0, "design_snapshot_gz_b64") in admitted.stripped_recovery_fields
    assert ("feature_log", 2, "children", 0, "diff_added_b64") in admitted.stripped_recovery_fields
    assert saved[1].cluster_snapshot is not None


def test_retained_definitions_and_source_table_are_detached_from_other_admissions(document):
    raw = encoded(document)
    first, second = module().admit_recipe_file(raw), module().admit_recipe_file(raw)
    before = second.source.model_dump_json()
    first.source.feature_log[-1].cluster_snapshot.helix_ids.clear()
    first.source.feature_log[0].params["cells"].clear()
    assert second.source.model_dump_json() == before
    assert first.original_bytes == second.original_bytes == raw


def test_encoded_sources_are_preserved_exactly_but_integrity_is_an_evaluator_responsibility(document):
    data = b"immutable named source"
    descriptor = describe(data, format="pdb", media_type="chemical/x-pdb")
    blob = embed(descriptor, data)
    document["input_sources"] = {descriptor.sha256: blob.model_dump()}
    admitted = module().admit_recipe_file(encoded(document))
    assert admitted.source.input_sources[descriptor.sha256] == blob
    assert portable_sources(admitted.source)[descriptor.sha256].size_bytes == len(data)
    document["input_sources"][descriptor.sha256]["data_b64"] = "broken"
    corrupt = module().admit_recipe_file(encoded(document))
    assert corrupt.source.input_sources[descriptor.sha256].data_b64 == "broken"
    with pytest.raises(ValueError):
        portable_sources(corrupt.source)


@pytest.mark.parametrize("field", ["id", "recipe_root", "feature_log", "feature_log_cursor", "feature_log_sub_cursor"])
def test_required_envelope_fields_are_not_inferred(document, field):
    del document[field]
    reject(document)


def test_absent_sources_mean_empty_without_inventing_bytes(document):
    document.pop("input_sources")
    assert module().admit_recipe_file(encoded(document)).source.input_sources == {}


@pytest.mark.parametrize("field,value", [
    ("feature_log_cursor", 0), ("feature_log_cursor", True), ("feature_log_cursor", -1.0),
    ("feature_log_cursor", "-1"), ("feature_log_sub_cursor", -2),
], ids=["past", "bool", "float", "string", "subcursor"])
def test_only_exact_latest_cursor_is_admitted(document, field, value):
    document[field] = value
    reject(document)


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 1.0}, {"version": "1"}, {"version": 2}, {"kind": "import"},
    {"source_json": "{}"}, {"source_sha256": "0" * 64}, {"new_root_field": True},
], ids=["bool", "float", "string", "future", "import", "baked-source", "digest", "unknown"])
def test_root_scope_is_explicit_empty_v1(document, changes):
    document["recipe_root"].update(changes)
    reject(document)


@pytest.mark.parametrize("field", ["version", "kind", "lattice_type", "initial_name"])
def test_root_semantic_fields_must_be_present(document, field):
    del document["recipe_root"][field]
    reject(document)


@pytest.mark.parametrize("location", ["top", "row", "nested", "sources"])
def test_unknown_schema_fields_are_not_silently_dropped(document, location):
    target = {"top": document, "row": document["feature_log"][0],
              "nested": document["feature_log"][-1]["cluster_snapshot"]}.get(location)
    if location == "sources":
        document["input_sources"] = {"a" * 64: {"data_b64": "", "unreviewed": True}}
    else:
        target["unreviewed"] = True
    reject(document)


@pytest.mark.parametrize("feature_type", ["minor", "checkpoint", "future"])
def test_legacy_or_unknown_top_rows_are_rejected_not_removed(document, feature_type):
    document["feature_log"].append({"feature_type": feature_type, "id": "legacy"})
    reject(document)


@pytest.mark.parametrize("location", ["wrapper", "group", "deformation", "child"])
def test_missing_typed_ids_refuse_before_uuid_defaults(document, monkeypatch, location):
    if location == "wrapper":
        del document["feature_log"][0]["id"]
    elif location == "group":
        del document["feature_log"][-1]["cluster_snapshot"]["id"]
    elif location == "deformation":
        deformation = native_source().feature_log[-1].model_dump(mode="json")
        del deformation["op_snapshot"]["id"]
        document["feature_log"].append(deformation)
    else:
        document["feature_log"].append({"feature_type": "routing-cluster", "id": "routing",
                                       "children": [{"feature_type": "minor", "op_subtype": "nick", "params": {}}]})
    monkeypatch.setattr("backend.core.models.uuid.uuid4", lambda: pytest.fail("Minted missing recipe identity"))
    reject(document)


@pytest.mark.parametrize("identity", ["", 7, True, "x" * 257], ids=["empty", "integer", "bool", "long"])
def test_wrapper_identity_is_explicit_bounded_text(document, identity):
    document["feature_log"][0]["id"] = identity
    reject(document)


@pytest.mark.parametrize("collision", ["parent", "child", "siblings"])
def test_all_wrapper_and_child_ids_share_one_namespace(document, collision):
    child = {"feature_type": "minor", "id": "child", "op_subtype": "nick", "label": "Nick", "params": {}}
    group = {"feature_type": "routing-cluster", "id": "routing", "children": [child]}
    if collision == "parent":
        group["id"] = document["feature_log"][0]["id"]
    elif collision == "child":
        child["id"] = document["feature_log"][0]["id"]
    else:
        group["children"].append(deepcopy(child))
    document["feature_log"].append(group)
    reject(document)


@pytest.mark.parametrize("variant", ["empty-routing", "missing-params", "params-list", "overlay-bool", "command-bool"])
def test_input_definitions_are_not_filled_or_coerced(document, variant):
    if variant == "empty-routing":
        document["feature_log"].append({"id": "routing", "feature_type": "routing-cluster", "children": []})
    elif variant == "missing-params":
        del document["feature_log"][0]["params"]
    elif variant == "params-list":
        document["feature_log"][0]["params"] = []
    elif variant == "overlay-bool":
        document["feature_log"][-1]["proof_version"] = True
    else:
        document["feature_log"][0]["params"]["_proof_version"] = True
    reject(document)


@pytest.mark.parametrize("payload", [
    b'{"id":"a","id":"b"}', b'{"metadata":{"x":1,"x":2}}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":1e999}', b'\xff', b'{"x":"\\ud800"}', b'[]', b'{',
], ids=["duplicate-top", "duplicate-nested", "nan", "infinity", "overflow", "utf8", "surrogate", "array", "syntax"])
def test_strict_json_refuses_before_definition_admission(payload):
    with pytest.raises(module().RecipeFileError):
        module().admit_recipe_file(payload)


@pytest.mark.parametrize("mutable", [bytearray(b"{}"), memoryview(b"{}"), "{}"], ids=["bytearray", "view", "text"])
def test_original_input_must_be_exact_immutable_bytes(mutable):
    with pytest.raises(module().RecipeFileError):
        module().admit_recipe_file(mutable)


def test_wire_limit_is_checked_before_decode(document, monkeypatch):
    raw = encoded(document)
    monkeypatch.setattr(module(), "MAX_FILE_BYTES", len(raw))
    assert module().admit_recipe_file(raw).original_bytes == raw
    with pytest.raises(module().RecipeFileError) as caught:
        module().admit_recipe_file(raw + b" ")
    assert caught.value.code == "recipe_file_limit"


@pytest.mark.parametrize("payload", [b"[" * 65 + b"0" + b"]" * 65, b"[" + b"0," * 30_000 + b"0]"],
                         ids=["depth", "nodes"])
def test_depth_and_nodes_are_bounded_before_json_allocation(payload, monkeypatch):
    monkeypatch.setattr(module().json, "loads", lambda *_a, **_k: pytest.fail("Allocated excessive JSON graph"))
    with pytest.raises(module().RecipeFileError) as caught:
        module().admit_recipe_file(payload)
    assert caught.value.code == "recipe_file_limit"


def test_quoted_escaped_brackets_are_not_counted_as_depth(document):
    document["metadata"] = {"name": '[{\\\"' * 100}
    assert module().admit_recipe_file(encoded(document)).source.feature_log


@pytest.mark.parametrize("budget", ["MAX_GRAPH_BYTES", "MAX_HISTORY_ROWS", "MAX_SOURCES"])
def test_independent_graph_row_and_source_budgets_are_enforced(document, monkeypatch, budget):
    monkeypatch.setattr(module(), budget, 1)
    if budget == "MAX_SOURCES":
        document["input_sources"] = {"a" * 64: {"data_b64": ""}, "b" * 64: {"data_b64": ""}}
    reject(document, code="recipe_file_limit")


def test_checkpoint_cancellation_propagates_without_constructing_a_carrier(broken_bytes):
    class Cancelled(BaseException):
        pass
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise Cancelled

    with pytest.raises(Cancelled):
        module().admit_recipe_file(broken_bytes, checkpoint=checkpoint)
    assert calls == 4
