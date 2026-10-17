"""The public batch compiles editable rows, never opaque authoring payloads."""

from copy import deepcopy
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_registered_batch import prepare_batch
from backend.core.part_batch_inputs import BatchRequest
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, import_root
from backend.core.models import SnapshotLogEntry


HELIX = "00000000-0000-0000-0000-000000000001"
STRAND = "00000000-0000-0000-0000-000000000002"
CLUSTER = "00000000-0000-0000-0000-000000000003"
GOLD = "00000000-0000-0000-0000-000000000004"
SEED = "00000000-0000-0000-0000-000000000099"


def source():
    return create_empty_part("Registered batch", "HONEYCOMB").copy_with(id="batch-part")


def command(kind, params, **changes):
    return {"kind": kind, "version": 1, "params": params, **changes}


def helix(**changes):
    return command("helix-add", {"helix_id": HELIX, "axis_start": {"x": 0., "y": 0., "z": 0.},
        "axis_end": {"x": 0., "y": 0., "z": 10.88}, "length_bp": 32, **changes}, label="Editable helix")


def strand(**changes):
    return command("strand-add", {"strand_id": STRAND, "domains": [{"helix_id": HELIX,
        "start_bp": 0, "end_bp": 7, "direction": "FORWARD"}], "strand_type": "scaffold", **changes})


def gold(**changes):
    return command("nanoparticle-create", {"nanoparticle_id": GOLD, "diameter_nm": 10., **changes})


def mixed_commands():
    return [helix(), strand(), command("cluster_create", {"cluster_id": CLUSTER, "name": "User group",
        "helix_ids": [HELIX]}), command("cluster_op", {"cluster_id": CLUSTER, "translation": [1., 2., 3.],
        "rotation": [0., 0., 0., 1.], "pivot": [0., 0., 0.]}), gold(),
        command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 12.}, label="Resize gold")]


def request(*commands, **changes):
    return {"batch_version": 1, "expected_design_id": "batch-part", "expected_revision": 7,
        "commands": list(commands or mixed_commands()), **changes}


def prepare(design=None, body=None, **changes):
    context = {"source_revision": 7, "history_seed": SEED, "timestamp": "2026-10-15T00:00:00Z", **changes}
    return prepare_batch(design or source(), body or request(), **context)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


@pytest.mark.parametrize("kind", ["python", "bundle-create", "sweep", "deformation", "cluster-paste",
    "photoproduct-create", "duplex-relax", "protein-import", "element-paste"])
def test_only_reviewed_public_kinds_are_accepted(kind):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(request(command(kind, {})))


@pytest.mark.parametrize("key,value", [("design", {}), ("snapshot", "bytes"), ("params", {}),
    ("code", "import os"), ("history_seed", SEED), ("_proof_version", 1), ("origin", "trusted")])
def test_envelope_cannot_supply_execution_authority_or_full_state(key, value):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(request(**{key: value}))


@pytest.mark.parametrize("key,value", [("_proof_version", 1), ("_generated_scope", {}), ("_generator", {}),
    ("_helix_id", HELIX), ("native_residues", []), ("deformations", []), ("sweep_positions", []),
    ("design_snapshot_gz_b64", "data"), ("diff_added_b64", "data"), ("code", "print('x')")])
def test_native_private_fields_and_output_geometry_cannot_enter_primitive_parameters(key, value):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(request(helix(**{key: value})))


@pytest.mark.parametrize("change", [{"batch_version": True}, {"batch_version": 2},
    {"expected_revision": True}, {"expected_revision": -1}, {"commands": []},
    {"commands": [gold()] * 33}])
def test_version_revision_and_batch_count_are_strict(change):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(request(**change))


@pytest.mark.parametrize("body", [request(helix(helix_id="not-a-uuid")),
    request(helix(axis_start={"x": 0., "y": 0., "z": 0., "metadata": {}})),
    request(helix(length_bp=True)), request(helix(phase_offset=float("nan"))),
    request(strand(domains=[{"helix_id": HELIX, "start_bp": 0, "end_bp": 7,
                            "direction": "FORWARD", "binds_overhang_id": "hidden"}])),
    request(strand(strand_type="linker")),
    request(command("nanoparticle-patch", {"nanoparticle_id": GOLD, "coating": {"seed": 1}})),
    request(command("nanoparticle-patch", {"nanoparticle_id": GOLD, "pose": [0.] * 16})),
    request(command("cluster_create", {"cluster_id": CLUSTER, "name": "group", "helix_ids": [HELIX]}, label="discarded")),
    request(command("cluster_op", {"cluster_id": CLUSTER, "translation": [0.] * 3,
                                  "rotation": [0.] * 4, "pivot": [0.] * 3}))])
def test_nested_inputs_remain_explicit_finite_controls(body):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(body)


def test_shared_operation_budget_rejects_before_schema_copy():
    with pytest.raises(ValidationError, match="budget"):
        BatchRequest.model_validate(request(strand(sequence="A" * 70_000)))


def test_mixed_batch_builds_separate_standard_rows_and_does_not_mutate_input():
    design, body = source(), request()
    before, inputs = design.model_dump_json(), deepcopy(body)
    result = prepare(design, body)
    assert result["status"] == "ready", result
    candidate = result["candidate"]
    assert design.model_dump_json() == before and body == inputs
    assert [entry.feature_type for entry in candidate.feature_log] == [
        "routing-cluster", "cluster_create", "cluster_op", "snapshot", "snapshot"]
    assert [child.op_subtype for child in candidate.feature_log[0].children] == ["helix-add", "strand-add"]
    assert candidate.feature_log[0].children[0].label == "Editable helix"
    assert candidate.feature_log[-1].label == "Resize gold"
    assert candidate.nanoparticles[0].diameter_nm == 12.
    assert candidate.strands[0].id == STRAND
    assert candidate.cluster_transforms[0].id == CLUSTER
    assert candidate.cluster_transforms[0].translation == [1., 2., 3.]
    assert result["batch"]["completed"] == [item["child_id"] or item["feature_id"] for item in result["batch"]["commands"]]
    assert result["batch"]["not_evaluated"] == []
    assert result["batch"]["candidate_replay_verified"] is False
    assert result["source_assessment"]["status"] == "verified"
    assert proof(candidate)["status"] == "verified"
    assert candidate.feature_log[0].pre_state_gz_b64 and candidate.feature_log[0].children[0].diff_added_b64


def test_validation_is_separate_from_reproducibility_and_semantic_noops_are_retained():
    result = prepare(body=request(gold(), command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 10.})))
    assert result["status"] == "ready" and not result["validation"].passed  # No scaffold in a particle-only part.
    assert len(result["candidate"].feature_log) == 2
    assert proof(result["candidate"])["status"] == "verified"


@pytest.mark.parametrize("change", [{"expected_design_id": "other"}, {"expected_revision": 8}])
def test_part_and_revision_guards_run_before_any_executor(change):
    result = prepare(body=request(**change), executor=lambda *_a: pytest.fail("Stale batch executed"))
    assert result["issues"][0]["code"] == "batch_conflict" and "candidate" not in result


@pytest.mark.parametrize("commands", [[helix(), helix()], [gold(), gold()],
    [helix(), strand(), strand()], [command("cluster_create", {"cluster_id": CLUSTER, "name": "A", "helix_ids": [HELIX]})] * 2])
def test_all_producer_ids_are_reserved_before_first_native_command(commands):
    result = prepare(body=request(*commands), executor=lambda *_a: pytest.fail("Collision executed"))
    assert result["issues"][0]["code"] == "invalid_selection" and "candidate" not in result


def test_producer_collision_with_current_design_is_refused_before_source_replay():
    design = prepare(body=request(gold()))["candidate"]
    result = prepare(design, request(gold()), history_seed=str(uuid5(UUID(SEED), "new")),
                     executor=lambda *_a: pytest.fail("Collision replayed"))
    assert result["issues"][0]["references"][0]["identity"] == GOLD


def test_typed_identity_namespaces_do_not_rewrite_user_names_or_cross_kind_refs():
    result = prepare(body=request(helix(), strand(strand_id=HELIX), gold(nanoparticle_id=HELIX)))
    assert result["status"] == "ready", result
    assert result["candidate"].helices[0].id == result["candidate"].strands[0].id == result["candidate"].nanoparticles[0].id == HELIX
    assert proof(result["candidate"])["status"] == "verified"


@pytest.mark.parametrize("commands", [[helix(length_bp=30_000), helix(helix_id=STRAND, length_bp=30_000)],
    [helix(), strand(domains=[{"helix_id": HELIX, "start_bp": 0, "end_bp": 50_000, "direction": "FORWARD"}])]])
def test_final_command_cannot_escape_prospective_work_admission(commands):
    result = prepare(body=request(*commands), executor=lambda *_a: pytest.fail("Oversized batch executed"))
    assert result["issues"][0]["code"] == "command_limit" and result["batch"]["completed"] == []


def test_forward_reference_fails_at_first_command_without_executing_later_producer():
    calls = []

    def run(kind, design, params):
        calls.append(kind)
        return execute(kind, design, params)

    result = prepare(body=request(strand(), helix(), gold()), executor=run)
    assert result["status"] == "failed" and calls == [] and "candidate" not in result
    issue = result["issues"][0]
    assert issue["command_index"] == 0 and issue["child_id"]
    assert issue["references"] == [{"kind": "helix", "identity": HELIX, "parameter_path": ["domains", 0, "helix_id"]}]
    assert len(result["batch"]["not_evaluated"]) == 2


def test_strand_work_admission_counts_existing_source_and_all_new_domains():
    design = prepare(body=request(helix(length_bp=30_000), strand(domains=[{
        "helix_id": HELIX, "start_bp": 0, "end_bp": 29_999, "direction": "FORWARD"}])))["candidate"]
    result = prepare(design, request(strand(strand_id=GOLD, domains=[{
        "helix_id": HELIX, "start_bp": 29_999, "end_bp": 0, "direction": "REVERSE"}])),
        history_seed=str(uuid5(UUID(SEED), "second")), executor=lambda *_a: pytest.fail("Aggregate strand work replayed"))
    assert result["issues"][0]["code"] == "command_limit"


def test_native_default_cluster_collision_is_detected_without_publishing_partial_helix():
    from backend.core.feature_identity import identity_factory

    default = identity_factory(HELIX)("cluster", [HELIX])
    design = source()
    before = design.model_dump_json()
    result = prepare(design, request(helix(), command("cluster_create", {
        "cluster_id": default, "name": "Would replace default", "helix_ids": [HELIX]})))
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["references"][0]["kind"] == "cluster"
    assert len(result["batch"]["completed"]) == 1
    assert design.model_dump_json() == before


def test_grouping_cannot_silently_duplicate_existing_rigid_ownership():
    result = prepare(body=request(helix(), command("cluster_create", {"cluster_id": CLUSTER,
        "name": "First group", "helix_ids": [HELIX]}), command("cluster_create", {
        "cluster_id": GOLD, "name": "Second group", "helix_ids": [HELIX]})))
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["code"] == "invalid_selection"
    assert result["issues"][0]["references"][0]["parameter_path"] == ["helix_ids", 0]


def test_domain_membership_lookup_ignores_unrelated_members_but_retains_ambiguous_strand_matches():
    from backend.api.part_registered_batch import _references
    from backend.core.models import ClusterRigidTransform, Domain, DomainRef, Strand
    from backend.core.part_command_errors import ReferenceResolutionError

    design = prepare(body=request(helix()))["candidate"]
    design.strands = [Strand(id=f"unrelated-{index}", domains=[Domain(helix_id="other",
        start_bp=0, end_bp=1, direction="FORWARD")]) for index in range(600)]
    design.cluster_transforms.append(ClusterRigidTransform(id="domain-scope", domain_ids=[
        DomainRef(strand_id=strand.id, domain_index=0) for strand in design.strands]))
    params = {"cluster": {"id": CLUSTER, "helix_ids": [HELIX]}}
    _references("cluster_create", design, params)
    design.strands.append(Strand(id="unrelated-599", domains=[Domain(helix_id=HELIX,
        start_bp=0, end_bp=1, direction="FORWARD")]))
    with pytest.raises(ReferenceResolutionError) as error:
        _references("cluster_create", design, params)
    assert error.value.references[0]["identity"] == HELIX


def test_minor_groups_close_at_other_rows_and_new_groups_have_distinct_host_ids():
    result = prepare(body=request(helix(), gold(), strand()))
    assert result["status"] == "ready", result
    entries = result["candidate"].feature_log
    assert [entry.feature_type for entry in entries] == ["routing-cluster", "snapshot", "routing-cluster"]
    assert entries[0].id != entries[2].id
    assert proof(result["candidate"])["status"] == "verified"


def test_source_proof_runs_once_then_each_new_command_once_and_recovery_is_ignored():
    design = prepare(body=request(gold()))["candidate"]
    for entry in design.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    calls = []

    def run(kind, current, params):
        calls.append(kind)
        return execute(kind, current, params)

    result = prepare_batch(design, request(command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 11.})),
        source_revision=7, history_seed=str(uuid5(UUID(SEED), "second")), timestamp="now", executor=run)
    assert result["status"] == "ready", result
    assert calls == ["nanoparticle-create", "nanoparticle-patch"]
    assert proof(result["candidate"])["status"] == "verified"
    assert design.feature_log[0].post_state_gz_b64 == "poisoned recovery"
    assert all(entry.post_state_gz_b64 != "poisoned recovery" for entry in result["candidate"].feature_log)


def test_source_mismatch_or_unsupported_history_never_executes_batch():
    design = prepare(body=request(gold()))["candidate"]
    design.nanoparticles[0].diameter_nm = 99.
    calls = []

    def run(kind, current, params):
        calls.append(kind)
        return execute(kind, current, params)

    result = prepare_batch(design, request(helix()), source_revision=7,
        history_seed=str(uuid5(UUID(SEED), "new")), timestamp="now", executor=run)
    assert result["status"] == "mismatch" and calls == ["nanoparticle-create"]
    assert "candidate" not in result and result["batch"]["completed"] == []
    design.feature_log[0].params.pop("_proof_version")
    assert prepare(design, request(helix()), history_seed=str(uuid5(UUID(SEED), "new")))["status"] == "unverified"


def test_import_root_is_reproduced_without_claiming_native_source_construction():
    design = source().copy_with(recipe_root=None)
    design.recipe_root = import_root(design)
    result = prepare(design, request(gold()))
    assert result["status"] == "ready"
    assert result["source_assessment"]["status"] == "reproduced_import"
    assert proof(result["candidate"])["native_editable"] is False


def test_failure_discards_mutated_candidate_and_preserves_completed_prefix_diagnostics():
    design = source()
    before = design.model_dump_json()

    def run(kind, current, params):
        if kind == "nanoparticle-patch":
            current.nanoparticles.clear()
            params["nanoparticle_id"] = "tampered"
            raise CommandContractError("Unavailable contract", code="source_unavailable")
        return execute(kind, current, params)

    result = prepare(design, request(gold(), command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 11.}),
        helix()), executor=run)
    assert result["status"] == "unverified" and "candidate" not in result
    assert len(result["batch"]["completed"]) == len(result["batch"]["not_evaluated"]) == 1
    assert result["issues"][0]["command_index"] == 1
    assert design.model_dump_json() == before


def test_internal_keyerror_is_not_reported_as_a_repairable_dependency():
    def defect(*_args):
        raise KeyError("internal defect")

    with pytest.raises(KeyError, match="internal defect"):
        prepare(body=request(gold()), executor=defect)


def test_cancellation_checkpoint_during_source_replay_stops_before_new_commands():
    class Cancelled(Exception):
        pass

    design = prepare(body=request(gold()))["candidate"]
    before, calls = design.model_dump_json(), []

    def run(kind, current, params):
        calls.append(kind)
        return execute(kind, current, params)

    def checkpoint():
        if calls:
            raise Cancelled("host cancellation")

    with pytest.raises(Cancelled, match="host cancellation"):
        prepare(design, request(helix()), history_seed=str(uuid5(UUID(SEED), "second")),
                executor=run, checkpoint=checkpoint)
    assert calls == ["nanoparticle-create"]
    assert design.model_dump_json() == before


def test_cancellation_checkpoint_after_first_suffix_row_discards_all_partial_work():
    class Cancelled(Exception):
        pass

    design, calls = source(), []
    before = design.model_dump_json()

    def run(kind, current, params):
        calls.append(kind)
        return execute(kind, current, params)

    def checkpoint():
        if calls:
            raise Cancelled("host cancellation")

    with pytest.raises(Cancelled, match="host cancellation"):
        prepare(design, request(gold(), helix()), executor=run, checkpoint=checkpoint)
    assert calls == ["nanoparticle-create"]
    assert design.model_dump_json() == before


def test_cumulative_recovery_budget_and_recipe_row_reservation_are_shared(monkeypatch):
    from backend.api import part_recovery_budget

    monkeypatch.setattr(part_recovery_budget, "MAX_RECOVERY_BYTES", 1)
    result = prepare(body=request(gold()))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "command_limit"
    assert "candidate" not in result
    design = source().copy_with(feature_log=[SnapshotLogEntry(id=f"old-{index}", op_kind="nanoparticle-create",
        label="legacy") for index in range(1999)])
    result = prepare(design, request(helix()), executor=lambda *_a: pytest.fail("Entry limit replayed"))
    assert result["issues"][0]["code"] == "entry_limit"  # One child PLUS its routing header.


def test_host_feature_ids_are_allocated_once_and_cannot_overwrite_prior_rows():
    first, second = prepare(), prepare()
    assert first["batch"]["commands"] == second["batch"]["commands"]
    result = prepare(first["candidate"], request(command("nanoparticle-delete", {"nanoparticle_id": GOLD})),
                     executor=lambda *_a: pytest.fail("Reused transaction identity executed"))
    assert result["issues"][0]["code"] == "batch_identity_collision"


def test_ordinary_feature_and_child_edits_preserve_batch_ids_and_cold_reproducibility():
    from backend.api.part_recipe_edit import prepare_change

    candidate = prepare()["candidate"]
    identities = [(entry.id, [child.id for child in getattr(entry, "children", [])]) for entry in candidate.feature_log]
    changed, _ = prepare_change(candidate, candidate, 0, lambda: None,
        sub_index=0, params={"length_bp": 40, "_helix_id": STRAND})
    assert changed.helices[0].id == HELIX and changed.helices[0].length_bp == 40
    assert [(entry.id, [child.id for child in getattr(entry, "children", [])]) for entry in changed.feature_log] == identities
    changed, _ = prepare_change(changed, changed, 2, lambda: None, params={"translation": [3., 2., 1.]})
    assert changed.cluster_transforms[0].translation == [3., 2., 1.]
    assert proof(changed)["status"] == "verified"
    assert candidate.model_dump(include=AUTHORING_FIELDS) != changed.model_dump(include=AUTHORING_FIELDS)
