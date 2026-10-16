"""Saved-file recovery evaluates explicit inputs without opening the old part.

These are private evaluator contracts. No HTTP route, live publication, file
write, worker process, or general damaged-file salvage is exercised here.
"""

from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest

from backend.api import part_proof_commands, state
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, Design
from backend.core.part_history_contract import FIELD_ROLES
from tests.test_part_deformation_preview import _append
from tests.test_part_group_repair import action, digest
from tests.test_part_group_repair_evaluation import dependent_source
from tests.test_part_structure_proof import assess, grouped_source


def service():
    # Test-first collection must remain safe before the new module exists.
    return importlib.import_module("backend.api.part_recipe_file_recovery")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def saved(kind="bend"):
    source = dependent_source(kind)
    return source, source.model_dump_json(indent=2).encode("utf-8")


def request(data, actions):
    return {"version": 1, "expected_source_sha256": sha256(data).hexdigest(),
            "actions": deepcopy(actions)}


def group_actions(source):
    return [action(row) for row in source.feature_log if row.feature_type == "cluster_create"]


def refused(result):
    assert result["status"] in {"failed", "unverified"}, result
    assert result["issues"] and all(type(issue.get("code")) is str for issue in result["issues"])
    assert "candidate" not in result


def patch_shared(monkeypatch, module, owner, name, replacement):
    """Patch the real shared seam and any already-imported function alias."""
    original = getattr(owner, name)
    for alias, value in tuple(vars(module).items()):
        if value is original:
            monkeypatch.setattr(module, alias, replacement)
    monkeypatch.setattr(owner, name, replacement)
    return original


def no_execution(monkeypatch, module):
    patch_shared(monkeypatch, module, part_proof_commands, "execute",
                 lambda *_a, **_k: pytest.fail("Refused/inspection input executed a native command"))


def test_inspection_reports_exact_file_receipt_and_explicit_upgrade_without_execution(monkeypatch):
    source, data = saved()
    original = bytes(data)
    with pytest.raises(ValueError, match="lattice frame placement cluster is missing"):
        Design.from_json(data.decode())
    module = service()
    no_execution(monkeypatch, module)
    result = module.inspect_recipe_file(data)
    assert result["status"] == "review", result
    assert "candidate" not in result
    receipt = result["recovery"]
    assert receipt["source_sha256"] == sha256(data).hexdigest()
    assert receipt["source_size_bytes"] == len(data)
    assert receipt["source_design_id"] == source.id
    assert receipt["old_state_verified"] is False
    excluded = set(receipt["excluded_fields"])
    assert {name for name, role in FIELD_ROLES.items()
            if role in {"physical", "presentation", "repair_draft"}} <= excluded
    assert {"helices", "strands", "cluster_transforms", "metadata"} <= excluded
    assert len(result["upgrades"]) == 1
    assert type(result["upgrades"][0]["label"]) is str and result["upgrades"][0]["label"]
    assert result["upgrades"][0]["action"] == group_actions(source)[0]
    assert data == original
    assert source.feature_log[1].proof_version == 1


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_explicit_recovery_rebuilds_real_downstream_inputs_as_a_new_valid_copy(kind):
    source, data = saved(kind)
    original_data = bytes(data)
    before = source.model_dump_json()
    body = request(data, group_actions(source))
    original_request = deepcopy(body)
    result = service().recover_recipe_file(data, body)
    assert result["status"] == "ready", result
    assert result["validation"]["passed"] is True
    candidate = Design.model_validate(result["candidate"])
    assert candidate.id != source.id and candidate.id
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert candidate.feature_log[2:] == source.feature_log[2:]
    old, new = source.feature_log[1], candidate.feature_log[1]
    assert new.model_dump(mode="json") == {**old.model_dump(mode="json"), "proof_version": 2}
    assert candidate.helices == source.helices and candidate.strands == source.strands
    assert candidate.lattice_frames == source.lattice_frames
    assert candidate.metadata.identity_last_known_path is None
    recovery = result["recovery"]
    assert recovery["source_sha256"] == sha256(data).hexdigest()
    assert recovery["source_size_bytes"] == len(data)
    assert recovery["source_design_id"] == source.id and recovery["old_state_verified"] is False
    upgrades = recovery["definition_upgrades"]
    assert len(upgrades) == 1
    assert upgrades[0] == {"feature_id": old.id, "child_id": None, "kind": "cluster_create",
        "cluster_id": old.cluster_id, "from_version": 1, "to_version": 2,
        "before_definition_sha256": digest(old), "after_definition_sha256": digest(new), "changed": True}
    reloaded = Design.from_json(candidate.to_json())
    for row in reloaded.feature_log:
        if row.feature_type == "snapshot":
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    proof = assess(reloaded)
    assert proof["status"] == "verified" and proof["structure"]["status"] == "valid", proof
    assert source.model_dump_json() == before and body == original_request
    assert data == original_data


def test_saved_materialized_geometry_and_nonrecipe_state_are_not_recovery_inputs():
    source, _ = saved()
    raw = source.model_dump(mode="json")
    raw.update(helices={"invalid": "not topology input"}, strands="untrusted saved output",
               cluster_transforms=None, lattice_frames="ignored materialization",
               annotations=[{"text": "Original only"}], loadouts=[{"sentinel": "do not activate"}],
               atomistic_reference={"sentinel": "do not install"}, repair_draft={"untrusted": True})
    raw["metadata"] = {"name": "Do not reuse", "identity_last_known_path": "original.nadoc"}
    for row in raw["feature_log"]:
        if row["feature_type"] == "snapshot":
            row["design_snapshot_gz_b64"] = row["post_state_gz_b64"] = "not gzip or base64"
    data = encoded(raw)
    result = service().recover_recipe_file(data, request(data, group_actions(source)))
    assert result["status"] == "ready", result
    candidate = Design.model_validate(result["candidate"])
    assert candidate.helices and candidate.strands
    assert candidate.annotations == [] and candidate.loadouts == []
    assert candidate.atomistic_reference is None and candidate.repair_draft is None
    assert candidate.metadata.identity_last_known_path is None
    assert {"helices", "strands", "metadata", "annotations", "loadouts", "atomistic_reference",
            "repair_draft"} <= set(result["recovery"]["excluded_fields"])
    assert json.loads(data) == raw


def test_exact_original_byte_digest_conflict_refuses_before_native_work(monkeypatch):
    source, data = saved()
    module = service()
    no_execution(monkeypatch, module)
    body = request(data, group_actions(source))
    # Whitespace is semantically harmless JSON but a different original file.
    result = module.recover_recipe_file(data + b"\n", body)
    refused(result)
    assert body["expected_source_sha256"] == sha256(data).hexdigest()


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 2}, {"candidate_id": "caller-owned"}, {"expected_revision": 7},
], ids=["bool-version", "unknown-version", "caller-candidate", "live-revision"])
def test_request_cannot_supply_versions_or_live_publication_authority(monkeypatch, changes):
    source, data = saved()
    module = service()
    no_execution(monkeypatch, module)
    refused(module.recover_recipe_file(data, {**request(data, group_actions(source)), **changes}))


@pytest.mark.parametrize("variant", ["empty", "too-many", "unknown", "duplicate", "stale-definition"])
def test_only_nonempty_bounded_unique_exact_group_actions_can_execute(monkeypatch, variant):
    source, data = saved()
    actions = group_actions(source)
    if variant == "empty":
        actions = []
    elif variant == "too-many":
        actions *= 65
    elif variant == "unknown":
        actions = [{"action": "set_input", "feature_id": "group-feature",
                    "parameter_path": ["proof_version"], "expected_old": 1, "value": 2}]
    elif variant == "duplicate":
        actions *= 2
    else:
        actions[0]["expected_definition_sha256"] = "0" * 64
    module = service()
    no_execution(monkeypatch, module)
    refused(module.recover_recipe_file(data, request(data, actions)))


def test_unselected_grouping_is_not_automatically_upgraded_to_make_repair_succeed():
    source = grouped_source()
    group = ClusterRigidTransform(id="5d229460-ea62-4076-a40e-c547d2b27d01", name="Second group",
                                  helix_ids=[helix.id for helix in source.helices])
    source = _append(source, ClusterCreateLogEntry(id="second-group", cluster_id=group.id,
        name=group.name, helix_ids=group.helix_ids, cluster_snapshot=group, proof_version=1))
    data = source.model_dump_json().encode()
    # Upgrading only the later group cannot recreate the owner deleted earlier.
    result = service().recover_recipe_file(data, request(data, [action(source.feature_log[-1])]))
    refused(result)
    assert any(issue["code"] == "invalid_structure" for issue in result["issues"]), result
    assert source.feature_log[1].proof_version == source.feature_log[2].proof_version == 1


def test_missing_downstream_owner_keeps_first_failure_and_no_partial_candidate():
    source, _ = saved()
    source.feature_log[2].cluster_id = "missing-pose-owner"
    data = source.model_dump_json().encode()
    result = service().recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)
    assert result["issues"][0]["feature_id"] == "move-feature"
    assert result["issues"][0]["code"] == "invalid_command_inputs"
    assert result["issues"][0]["detail"] == "Missing pose cluster"


class CancelledRecovery(RuntimeError):
    pass


@pytest.mark.parametrize("during_replay", [False, True], ids=["before-admission", "between-commands"])
@pytest.mark.parametrize("exception_type", [CancelledRecovery, ValueError, TypeError])
def test_cancellation_propagates_without_returning_a_candidate(monkeypatch, during_replay, exception_type):
    source, data = saved()
    module = service()
    executed = []
    original = part_proof_commands.execute
    cancellation = exception_type("Caller cancelled private recovery")

    def execute(kind, design, params):
        candidate = original(kind, design, params)
        executed.append(kind)
        return candidate

    patch_shared(monkeypatch, module, part_proof_commands, "execute", execute)

    def checkpoint():
        if not during_replay or executed:
            raise cancellation

    with pytest.raises(exception_type) as caught:
        module.recover_recipe_file(data, request(data, group_actions(source)), checkpoint=checkpoint)
    assert caught.value is cancellation
    assert len(executed) == (1 if during_replay else 0)
    assert source.feature_log[1].proof_version == 1


@pytest.mark.parametrize("exception_type", [ValueError, TypeError])
def test_inspection_cancellation_propagates_before_admission(monkeypatch, exception_type):
    _, data = saved()
    module = service()
    no_execution(monkeypatch, module)
    cancellation = exception_type("Caller cancelled private inspection")

    def checkpoint():
        raise cancellation

    with pytest.raises(exception_type) as caught:
        module.inspect_recipe_file(data, checkpoint=checkpoint)
    assert caught.value is cancellation


def test_recovery_never_reads_or_installs_an_active_document_or_writes_a_file(monkeypatch):
    from backend.core import part_document_io

    source, data = saved()
    module = service()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Private file recovery crossed a live-state or filesystem boundary")

    with state._lock:
        sessions = {key: (value, value.design, value.revision, tuple(value.history), tuple(value.redo))
                    for key, value in state._sessions.items()}
    for name in ("get_or_404", "get_design", "load_design", "set_design", "set_design_silent",
                 "snapshot", "drop_doc", "capture_design_for_evaluation"):
        monkeypatch.setattr(state, name, forbidden)
    monkeypatch.setattr(part_document_io, "read_file", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    assert result["status"] == "ready", result
    with state._lock:
        assert set(state._sessions) == set(sessions)
        for key, (session, design, revision, history, redo) in sessions.items():
            current = state._sessions[key]
            assert current is session and current.design is design and current.revision == revision
            assert tuple(current.history) == history and tuple(current.redo) == redo


def test_unreferenced_corrupt_retained_source_is_not_silently_discarded(monkeypatch):
    source, _ = saved()
    raw = source.model_dump(mode="json")
    raw["input_sources"] = {"0" * 64: {"data_b64": "YWJj"}}
    data = encoded(raw)
    module = service()
    no_execution(monkeypatch, module)
    refused(module.recover_recipe_file(data, request(data, group_actions(source))))


def test_missing_pinned_source_refuses_before_any_native_execution(monkeypatch):
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_input_sources import describe

    source, _ = saved()
    descriptor = describe(b"missing pinned source", format="pdb", media_type="chemical/x-pdb")
    raw = source.model_dump(mode="json")
    raw["feature_log"].append(SnapshotLogEntry(
        id="source-dependent-feature", op_kind="protein-import", label="Pinned protein",
        params={"_proof_version": 1, "source": descriptor.model_dump(mode="json")},
    ).model_dump(mode="json"))
    data = encoded(raw)
    module = service()
    no_execution(monkeypatch, module)
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)
    assert result["issues"][0]["code"] == "source_unavailable"
    assert result["issues"][0]["references"][0]["identity"] == descriptor.sha256


def test_result_byte_refusal_never_exposes_a_candidate(monkeypatch):
    from backend.api import part_evaluation_worker

    source, data = saved()
    module = service()
    monkeypatch.setattr(part_evaluation_worker, "MAX_CANDIDATE_BYTES", 1024)
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)
    assert result["issues"][0]["code"] == "result_limit"
    assert source.feature_log[1].proof_version == 1


def test_normal_load_numeric_type_drift_refuses_before_independent_proof(monkeypatch):
    from backend.core import part_history_contract

    source, data = saved()
    module = service()
    original = Design.from_json
    loaded = []

    def changed_load(cls, text):
        candidate = original(text)
        assert candidate.id != source.id
        params = candidate.feature_log[0].params
        assert type(params["length_bp"]) is int
        params["length_bp"] = float(params["length_bp"])
        loaded.append(candidate.id)
        return candidate

    monkeypatch.setattr(Design, "from_json", classmethod(changed_load))
    patch_shared(monkeypatch, module, part_history_contract, "assess_part_history",
                 lambda *_a, **_k: pytest.fail("Changed download inputs reached independent proof"))
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)
    assert result["issues"][0]["code"] == "recovery_roundtrip_mismatch"
    assert len(loaded) == 1


def test_ordinary_validation_failure_cannot_be_returned_as_ready(monkeypatch):
    from backend.core import validator

    source, data = saved()
    module = service()
    report = validator.ValidationReport([validator.ValidationResult(False, "Unsafe recovered topology")])
    patch_shared(monkeypatch, module, validator, "validate_design", lambda *_a, **_k: report)
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)


def test_independent_replay_failure_withholds_candidate_after_successful_repair(monkeypatch):
    from backend.core import part_history_contract

    source, data = saved()
    module = service()
    calls = []
    original = part_history_contract.assess_part_history

    def assess_candidate(candidate, **kwargs):
        proof = original(candidate, **kwargs)
        calls.append((candidate.id, proof["status"]))
        assert proof["status"] == "verified", proof
        return {**proof, "status": "mismatch", "native_editable": False,
                "issues": [{"code": "independent_replay_mismatch"}]}

    patch_shared(monkeypatch, module, part_history_contract, "assess_part_history", assess_candidate)
    result = module.recover_recipe_file(data, request(data, group_actions(source)))
    refused(result)
    assert len(calls) == 1 and calls[0][0] != source.id


def test_definition_work_limit_precedes_replay_even_when_saved_output_is_tiny(monkeypatch):
    source, _ = saved()
    raw = source.model_dump(mode="json")
    raw["feature_log"][0]["params"]["name"] = "x" * 500_001
    data = encoded(raw)
    module = service()
    no_execution(monkeypatch, module)
    refused(module.recover_recipe_file(data, request(data, group_actions(source))))
