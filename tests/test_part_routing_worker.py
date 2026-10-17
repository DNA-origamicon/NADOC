"""Real bounded routing transport and independently checked prefix packets.

The native fixture records its bundle, crossover and forced ligation producers.
Only the two positive transport operations spawn processes; malformed metadata
uses the same evaluator/result validators directly, without another native run.
"""

from copy import deepcopy
from multiprocessing.shared_memory import SharedMemory
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api import doc_context, part_proof_commands as commands, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_ordinary_recipe_recording as host
from backend.api import part_publication_policy as policy
from backend.api import part_routing_edit_context as context
from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_routing_edit_inputs import normalize
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from tests.test_group_lineage_routing_annotations import recipe_prefix
from tests.test_part_pattern_recording import saved, unchanged
from tests.test_part_transform_preview import snapshot


@pytest.fixture
def source():
    prefix = recipe_prefix()
    result = snapshot(prefix, "crossover-extra-bases", {
        "crossover_id": prefix.crossovers[0].id, "sequence": "AC"}, "selected-extra")
    return prefix, result


def operation(source, *, inputs_only=True):
    entry = source.feature_log[-1]
    child = entry.children[0]
    params = normalize(child.op_subtype, child.params, {} if inputs_only else {"sequence": "NN"})
    return {"request": EvaluationRequest(operation="edit", params=params,
        index=len(source.feature_log) - 1, sub_index=0, expected_revision=7).model_dump(mode="json"),
        "header": {"identity": entry.id, "timestamp": "2026-10-16T00:00:00+00:00",
            "source_revision": 7, "source_design_id": source.id,
            "expected_feature_id": entry.id, "expected_child_id": child.id,
            "expected_kind": child.op_subtype, "routing_recording_version": 1,
            "routing_inputs_only": inputs_only, "added_output_ids": []}}


def packet(source):
    prefix, current = source
    child = current.feature_log[-1].children[0]
    return {"kind": child.op_subtype, "params": normalize(child.op_subtype, child.params, {}),
        "prefix": context.inventory(prefix), "source_design_id": current.id, "source_revision": 7,
        "feature_id": current.feature_log[-1].id, "child_id": child.id}


def guards(value):
    return {"kind": value["kind"], "design_id": value["source_design_id"],
        "revision": value["source_revision"], "feature_id": value["feature_id"],
        "child_id": value["child_id"], "expected_params": deepcopy(value["params"])}


def verified(design):
    result = assess_part_history(design, execute=commands.execute, dependencies=commands.dependencies)
    assert result["status"] == "verified" and result["native_editable"], result


def test_native_junction_reference_fixture_cold_proves_without_transport(source):
    prefix, current = source
    assert prefix.crossovers and prefix.forced_ligations
    assert all(row.pre_state_gz_b64 == "poisoned-pre" for row in current.feature_log
               if row.feature_type == "routing-cluster")
    verified(Design.model_validate_json(current.model_dump_json()))


def test_real_spawned_prefix_and_edit_close_unlink_and_publish_once(source, monkeypatch):
    prefix, original = source
    doc = f"__routing_spawn__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    markers = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    worker_type = host.EvaluationWorker
    workers, names = [], []

    def tracked(design, definition):
        worker = worker_type(design, definition)
        workers.append(worker)
        names.extend(buffer.name for buffer in worker._buffers)
        return worker

    monkeypatch.setattr(host, "EvaluationWorker", tracked)
    try:
        state.load_design(original)
        session = state._sessions[doc]
        before = saved(session)
        index = len(original.feature_log) - 1
        expected = {"expected_design_id": original.id, "expected_revision": session.revision,
            "expected_feature_id": original.feature_log[index].id,
            "expected_child_id": original.feature_log[index].children[0].id}
        preview = host.routing_inputs(index, 0, **expected)
        assert preview["prefix"] == context.inventory(prefix)
        assert preview["params"] == normalize(preview["kind"], original.feature_log[index].children[0].params, {})
        assert preview["prefix"]["crossovers"][0]["half_a"]["helix_id"] in {h.id for h in prefix.helices}
        assert preview["prefix"]["forced_ligations"][0]["extra_bases"] is None
        unchanged(session, before)
        candidate, report, entry = host.edit_routing(index, 0, {"sequence": "NN"}, **expected)
        assert report.passed and candidate is session.design and entry.id == expected["expected_feature_id"]
        assert candidate.crossovers[0].extra_bases == "NN"
        assert candidate.forced_ligations == original.forced_ligations
        assert session.revision == before[2] + 1 and len(session.history) == len(before[3]) + 1
        assert original.model_dump_json() == before[1]
        verified(Design.model_validate_json(candidate.model_dump_json()))
        assert len(workers) == 2
    finally:
        for worker in workers:
            worker.close()
            assert worker._closed and worker._process_closed and not worker.is_alive()
        for name in names:
            with pytest.raises(FileNotFoundError):
                SharedMemory(name=name)
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


@pytest.mark.parametrize("key,value", [
    ("routing_recording_version", True), ("routing_recording_version", 2),
    ("source_revision", True), ("source_revision", 8), ("source_design_id", "wrong"),
    ("expected_feature_id", "wrong"), ("expected_child_id", "wrong"), ("expected_kind", "nick"),
    ("routing_inputs_only", 1), ("added_output_ids", "not-a-list"),
    ("added_output_ids", ["11111111-1111-4111-8111-111111111111"]),
    ("pattern_recording_version", 1), ("extrusion_recording_version", 1),
])
def test_private_routing_header_refuses_before_native_proof(source, key, value):
    original = source[1]
    request = operation(original)
    request["header"][key] = value
    before = original.model_dump_json()
    result = evaluate(original, request, executor=lambda *_: pytest.fail("Invalid header entered native proof"))
    assert result["status"] in {"failed", "unverified"} and result["issues"]
    assert original.model_dump_json() == before


def test_read_only_worker_operation_cannot_change_inputs(source):
    request = operation(source[1])
    request["request"]["params"]["sequence"] = "NN"
    result = evaluate(source[1], request, executor=lambda *_: pytest.fail("Input query executed a changed child"))
    assert result["status"] in {"failed", "unverified"}
    assert result["issues"][0]["code"] == "invalid_operation_admission"


def test_complete_native_packet_is_detached_and_preserves_nullable_fields(source):
    value = packet(source)
    copied = context.validate_packet(value, **guards(value))
    assert copied == value and copied is not value
    copied["prefix"]["strands"][0]["domains"].clear()
    copied["params"]["sequence"] = "NN"
    assert value["prefix"]["strands"][0]["domains"] and value["params"]["sequence"] == "AC"


@pytest.mark.parametrize("fault", ["params", "numeric_proof", "helix_bool", "helix_missing", "helix_extra",
    "strand_domains", "strand_boolean", "strand_name", "domain_direction", "domain_ordinal_scalar",
    "domain_extra", "half_direction", "half_bool", "half_missing", "junction_sequence",
    "forced_direction", "forced_bool", "forced_extra", "duplicate_id", "envelope_revision"])
def test_malformed_prefix_packet_refuses_without_coercion_or_extra_geometry(source, fault):
    value = packet(source)
    expected = guards(value)
    inv = value["prefix"]
    if fault == "params":
        value["params"]["sequence"] = "NN"
    elif fault == "numeric_proof":
        value["params"]["_proof_version"] = 1.0
    elif fault == "helix_bool":
        inv["helices"][0]["bp_start"] = True
    elif fault == "helix_missing":
        del inv["helices"][0]["length_bp"]
    elif fault == "helix_extra":
        inv["helices"][0]["axis_start"] = [1, 2, 3]
    elif fault == "strand_domains":
        del inv["strands"][0]["domains"]
    elif fault == "strand_boolean":
        inv["strands"][0]["is_scaffold"] = 1
    elif fault == "strand_name":
        inv["strands"][0]["name"] = []
    elif fault == "domain_direction":
        inv["strands"][0]["domains"][0]["direction"] = "forward"
    elif fault == "domain_ordinal_scalar":
        inv["strands"][0]["domains"][0]["start_bp"] = 0.0
    elif fault == "domain_extra":
        inv["strands"][0]["domains"][0]["geometry"] = []
    elif fault == "half_direction":
        inv["crossovers"][0]["half_a"]["strand"] = "SIDEWAYS"
    elif fault == "half_bool":
        inv["crossovers"][0]["half_a"]["index"] = True
    elif fault == "half_missing":
        del inv["crossovers"][0]["half_b"]
    elif fault == "junction_sequence":
        inv["crossovers"][0]["extra_bases"] = 3
    elif fault == "forced_direction":
        inv["forced_ligations"][0]["three_prime_direction"] = "forward"
    elif fault == "forced_bool":
        inv["forced_ligations"][0]["five_prime_bp"] = False
    elif fault == "forced_extra":
        inv["forced_ligations"][0]["nucleotides"] = []
    elif fault == "duplicate_id":
        inv["helices"].append(deepcopy(inv["helices"][0]))
    else:
        value["source_revision"] = True
        expected["revision"] = 1
    with pytest.raises(CommandContractError) as caught:
        context.validate_packet(value, **expected)
    assert caught.value.code == "invalid_routing_result"


def test_expanded_packet_budget_refuses_before_json_encoding(source, monkeypatch):
    value = packet(source)
    expected = guards(value)
    monkeypatch.setattr(context, "MAX_ITEMS", 5)
    monkeypatch.setattr(context, "json", SimpleNamespace(
        dumps=lambda *_a, **_k: pytest.fail("Unadmitted packet encoded"), loads=context.json.loads))
    with pytest.raises((CommandContractError, ValueError)):
        context.validate_packet(value, **expected)
