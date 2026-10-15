"""Repair transaction planning/replay; numerical executors are test doubles."""

from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.api import part_recipe_repair as repair
from backend.api.part_nanoparticle_commands import build as gold_build
from backend.core.models import MinorMutationLogEntry, Nanoparticle, OverhangRotationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_dependencies import Dependencies
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS


def row(identity, kind, params):
    return SnapshotLogEntry(id=identity, op_kind=kind, label=f"Keep label {identity}", timestamp="2026-10-15T12:00:00Z",
        params=params, design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned saved output")


def gold_params(identity, **extra):
    return {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": identity, **extra}


def source():
    design = create_empty_part("Repair source", "HONEYCOMB")
    design.id = "repair-part"
    design.nanoparticles = [Nanoparticle(id="materialized-but-not-in-recipe", diameter_nm=99)]
    design.feature_log = [row("create", "nanoparticle-create", gold_params("gold", diameter_nm=10.0)),
        row("patch", "nanoparticle-patch", gold_params("missing", diameter_nm=12.0)),
        row("later", "nanoparticle-create", gold_params("future", diameter_nm=8.0))]
    return design


def set_input(feature="patch", path=None, expected="missing", value="gold", **extra):
    return {"action": "set_input", "feature_id": feature, "parameter_path": path or ["nanoparticle_id"],
            "expected_old": expected, "value": value, **extra}


def request(*actions, **extra):
    return {"repair_version": 1, "expected_design_id": "repair-part", "expected_revision": 7,
            "actions": list(actions) or [set_input()], **extra}


def known(_kind, _params):
    return Dependencies()


def evaluate(design, body=None, **options):
    return repair.prepare_repair(design, request() if body is None else body, source_revision=options.pop("source_revision", 7),
        executor=options.pop("executor", gold_build), dependency_resolver=options.pop("dependency_resolver", known), **options)


def test_broken_model_repairs_from_root_without_old_proof_and_regenerates_recovery(monkeypatch):
    from backend.api import state
    from backend.core import part_history_contract

    design = source()
    before = design.model_dump_json()
    monkeypatch.setattr(part_history_contract, "assess_part_history", lambda *_a, **_k: pytest.fail("Repair attempted old-model proof"))
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_a: pytest.fail("Repair read recovery"))
    result = evaluate(design)
    assert result["status"] == "ready", result
    candidate = result["candidate"]
    assert [(item.id, item.diameter_nm) for item in candidate.nanoparticles] == [("gold", 12), ("future", 8)]
    assert candidate.id == design.id and candidate.recipe_root == design.recipe_root
    assert result["repair"]["completed_prefix"] == ["create", "patch", "later"]
    assert not result["repair"]["old_state_verified"] and result["repair"]["not_evaluated"] == []
    for old, new in zip(design.feature_log, candidate.feature_log):
        assert (new.id, new.label, new.timestamp) == (old.id, old.label, old.timestamp)
        assert new.design_snapshot_gz_b64 and new.design_snapshot_gz_b64 != "poisoned recovery"
        assert new.post_state_gz_b64 and new.post_state_gz_b64 != "poisoned saved output"
    assert design.model_dump_json() == before


def test_replacement_can_only_resolve_in_replayed_prefix_and_later_rows_are_not_failed():
    design = source()
    design.nanoparticles.append(Nanoparticle(id="future", diameter_nm=8))
    before = design.model_dump_json()
    result = evaluate(design, request(set_input(value="future")))
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["code"] == "missing_reference"
    assert result["issues"][0]["feature_id"] == "patch"
    assert result["issues"][0]["references"] == [{"kind": "nanoparticle", "identity": "future",
                                                  "parameter_path": ["nanoparticle_id"]}]
    assert result["repair"]["completed_prefix"] == ["create"]
    assert result["repair"]["not_evaluated"] == ["later"]
    assert design.model_dump_json() == before


@pytest.mark.parametrize("failure", ["reference", "unavailable", "internal"])
def test_failed_or_internally_broken_executor_cannot_expose_partial_candidate_or_mutate_source(failure):
    design = source()
    before = design.model_dump_json()
    calls = []

    def run(kind, current, params):
        calls.append(kind)
        if kind == "nanoparticle-patch":
            current.nanoparticles[0].diameter_nm = 777
            params["nanoparticle_id"] = "executor-mutated-input"
            if failure == "reference":
                raise ReferenceResolutionError("Missing dependency", references=[{
                    "kind": "nanoparticle", "identity": "gone", "parameter_path": ["nanoparticle_id"]}])
            if failure == "unavailable":
                raise CommandContractError("Source is unavailable", code="source_unavailable")
            raise KeyError("internal defect")
        return gold_build(kind, current, params)

    if failure == "internal":
        with pytest.raises(KeyError, match="internal defect"):
            evaluate(design, executor=run)
    else:
        result = evaluate(design, executor=run)
        assert "candidate" not in result
        assert result["status"] == ("failed" if failure == "reference" else "unverified")
        assert result["repair"]["completed_prefix"] == ["create"]
        assert result["repair"]["not_evaluated"] == ["later"]
    assert calls == ["nanoparticle-create", "nanoparticle-patch"]
    assert design.model_dump_json() == before


@pytest.mark.parametrize("change,code", [
    (lambda d: setattr(d, "recipe_root", None), "missing_recipe_root"),
    (lambda d: setattr(d, "recipe_root", d.recipe_root.model_copy(update={"version": 2})), "unsupported_root_version"),
    (lambda d: setattr(d, "feature_log_cursor", 0), "historical_cursor"),
    (lambda d: setattr(d, "feature_log_sub_cursor", 0), "historical_cursor"),
    (lambda d: setattr(d.feature_log[1], "id", "create"), "ambiguous_feature_identity"),
])
def test_unsupported_roots_and_ambiguous_history_fail_before_execution(change, code):
    design = source()
    change(design)
    result = evaluate(design, executor=lambda *_a: pytest.fail("Invalid repair executed"))
    assert result["issues"][0]["code"] == code and "candidate" not in result


@pytest.mark.parametrize("changes,revision", [({"expected_design_id": "other"}, 7), ({"expected_revision": 6}, 7), ({}, 8), ({}, True)])
def test_request_is_bound_to_trusted_captured_revision_and_document(changes, revision):
    result = evaluate(source(), request(**changes), source_revision=revision,
                      executor=lambda *_a: pytest.fail("Stale repair executed"))
    assert result["issues"][0]["code"] == "repair_conflict"
    assert "candidate" not in result


@pytest.mark.parametrize("action,code", [
    (set_input(expected="outdated"), "repair_conflict"),
    (set_input(feature="gone"), "missing_feature"),
    (set_input(path=["absent"]), "invalid_parameter_path"),
    (set_input(feature="create", path=["nanoparticle_id"], expected="gold", value="renamed"), "protected_recipe_identity"),
    (set_input(path=["_proof_version"], expected=1, value=2), "protected_recipe_identity"),
    (set_input(path=["nanoparticle_version"], expected=1, value=2), "protected_recipe_identity"),
    (set_input(child_id="absent-child"), "invalid_repair_target"),
])
def test_definition_preconditions_are_exact_and_protected_inputs_are_rejected(action, code):
    design = source()
    before = design.model_dump_json()
    result = evaluate(design, request(action), executor=lambda *_a: pytest.fail("Rejected action executed"))
    assert result["issues"][0]["code"] == code
    assert design.model_dump_json() == before


def test_paths_preserve_token_types_exact_keys_and_unrelated_equal_text():
    design = source()
    design.feature_log = [row("create", "nanoparticle-create", {"_proof_version": 1,
        "refs": [{"key/with:punctuation": "old"}], "label": "old", "metadata": {"old": "old"}})]
    action = set_input(feature="create", path=["refs", 0, "key/with:punctuation"], expected="old", value="new")
    result = evaluate(design, request(action), executor=lambda _k, d, _p: d)
    assert result["status"] == "ready", result
    params = result["candidate"].feature_log[0].params
    assert params["refs"] == [{"key/with:punctuation": "new"}]
    assert params["label"] == "old" and params["metadata"] == {"old": "old"}
    for path in (["refs", "0", "key/with:punctuation"], ["refs", 1, "key/with:punctuation"]):
        failed = evaluate(design, request({**action, "parameter_path": path}))
        assert failed["issues"][0]["code"] == "invalid_parameter_path"


def test_overlapping_paths_and_strict_expected_types_do_not_depend_on_action_order():
    design = source()
    action = set_input(path=["diameter_nm"], expected=12.0, value=13.0)
    for actions in ((action, action), (action, set_input(path=["diameter_nm", 0], expected=0, value=1))):
        result = evaluate(design, request(*actions))
        assert result["issues"][0]["code"] == "overlapping_repair_paths"
    result = evaluate(design, request(set_input(path=["_proof_version"], expected=True, value=1)))
    assert result["issues"][0]["code"] == "repair_conflict"


def test_closed_scope_and_identity_namespace_are_not_repairable_fields():
    for key, old, new, path in (("history_seed", str(UUID(int=1)), str(UUID(int=2)), ["history_seed"]),
                               ("_generated_scope", {"retained": ["old"]}, "new", ["_generated_scope", "retained", 0])):
        design = source()
        design.feature_log[1].params[key] = old
        expected = old if key == "history_seed" else "old"
        result = evaluate(design, request(set_input(path=path, expected=expected, value=new)))
        assert result["issues"][0]["code"] == "protected_recipe_identity"


def test_legacy_target_cannot_be_promoted_by_a_repair_patch():
    design = source()
    design.feature_log[1].params["_proof_version"] = 0
    result = evaluate(design, request(set_input(path=["_proof_version"], expected=0, value=1)),
        dependency_resolver=lambda _k, p: Dependencies(known=p.get("_proof_version") == 1))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "missing_proof_contract"


def test_routing_child_identity_labels_and_poisoned_diffs_survive_repair():
    design = source()
    child = MinorMutationLogEntry(id="child", op_subtype="nick", label="Keep child", timestamp="then",
        params={"_proof_version": 1, "helix_id": "old", "_strand_id": "stable-output"},
        diff_added_b64="poisoned child", diff_removed_b64="poisoned child", diff_modified_b64="poisoned child")
    design.feature_log = [design.feature_log[0], RoutingClusterLogEntry(id="group", label="Keep group",
        children=[child], pre_state_gz_b64="poisoned group", post_state_gz_b64="poisoned group")]

    def execute(kind, current, params):
        return gold_build(kind, current, params) if kind == "nanoparticle-create" else current

    result = evaluate(design, request(set_input(feature="group", child_id="child", path=["helix_id"], expected="old", value="new")), executor=execute)
    assert result["status"] == "ready", result
    group = result["candidate"].feature_log[1]
    rebuilt = group.children[0]
    assert group.id == "group" and group.label == "Keep group"
    assert (rebuilt.id, rebuilt.label, rebuilt.timestamp) == ("child", "Keep child", "then")
    assert rebuilt.params["_strand_id"] == "stable-output" and rebuilt.params["helix_id"] == "new"
    assert rebuilt.diff_added_b64 != "poisoned child" and group.post_state_gz_b64 != "poisoned group"
    assert result["repair"]["completed_prefix"] == ["create", "child"]


def test_unchanged_supported_overlay_replays_but_overlay_definition_edit_is_deferred():
    design = source()
    design.feature_log = [design.feature_log[0], OverhangRotationLogEntry(id="overlay", overhang_ids=["x"],
        rotations=[[0, 0, 0, 1]], proof_version=1)]
    result = evaluate(design, request(set_input(feature="create", path=["diameter_nm"], expected=10.0, value=11.0)),
        executor=lambda kind, d, p: gold_build(kind, d, p) if kind != "overhang_rotation" else d)
    assert result["status"] == "ready" and result["repair"]["completed_prefix"] == ["create", "overlay"]
    result = evaluate(design, request(set_input(feature="overlay", path=["overhang_ids", 0], expected="x", value="y")))
    assert result["issues"][0]["code"] == "unsupported_repair_target"


def numerical(kind):
    if kind == "nanoparticle-patch":
        from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE

        return {"_proof_version": 1, "coating_version": 1, "importer_version": 1,
            "action": "set", "nanoparticle_id": "gold", "mode": "adsorption", "footprint_nm2": 40.0,
            "spacer_nm": 0.3, "seed": 1, "coverage_source": None, "coverage_reference": None,
            "count_override": 1, "pdb_source": {"version": 1, "sha256": PDB_SHA256, "size_bytes": PDB_SIZE,
                "format": "pdb", "media_type": "chemical/x-pdb"},
            "engine": {"id": "nadoc.streptavidin-native.v1", "implementation_sha256": "0" * 64, "runtime_sha256": "0" * 64}}
    if kind == "duplex-relax":
        return {"_proof_version": 1, "relaxation_version": 1, "source": {"kind": "native"},
            "history_seed": str(UUID(int=99)), "duplex_id": "duplex", "driver_overhang_id": "driver",
            "driven_overhang_id": "driven", "joint_ids": ["joint"], "driver_cluster_id": "driver-cluster",
            "driven_cluster_id": "driven-cluster", "duplex_cluster_id": "pair-cluster",
            "engine": {"id": "nadoc.duplex-relax-native.v1", "implementation_sha256": "0" * 64, "runtime_sha256": "0" * 64}}
    authored = {"base_keys": ["h:0:forward", "h:1:forward"], "history_seed": str(UUID(int=99))} if kind == "photoproduct-create" else {"photoproduct_id": "lesion"}
    return {"_proof_version": 1, "conversion_version": 1, "source": {"kind": "native"}, **authored,
        "template": {"product_id": "tt-cpd-cis-syn", "schema": "nadoc.photoproduct-coordinate-template.v1", "sha256": "a" * 64},
        "engine": {"id": "nadoc.cpd-native-engine.v1", "implementation_sha256": "0" * 64, "runtime_sha256": "0" * 64}}


def upgrade_action(params, **extra):
    return {"action": "upgrade_numerical_contract", "feature_id": "numerical",
        "expected_engine": deepcopy(params["engine"]), "expected_template": deepcopy(params.get("template")), **extra}


def current_pins(_kind, params):
    return {key: ({**value, "implementation_sha256": "1" * 64, "runtime_sha256": "2" * 64} if key == "engine" else value)
            for key, value in params.items() if key in {"engine", "template", "_proof_version", "conversion_version", "relaxation_version", "coating_version", "importer_version"}}


@pytest.mark.parametrize("kind", ["photoproduct-create", "photoproduct-relax", "duplex-relax", "nanoparticle-patch"])
def test_explicit_server_upgrade_changes_only_pins_and_reports_provenance(kind):
    design = source()
    params = numerical(kind)
    design.feature_log = [row("numerical", kind, params)]
    before = design.model_dump_json()
    received = []

    def native_double(_kind, current, inputs):
        received.append(inputs)
        if inputs["engine"]["implementation_sha256"] != "1" * 64:
            raise CommandContractError("Older numerical implementation", code="engine_mismatch")
        return current

    result = evaluate(design, request(upgrade_action(params)), numerical_provider=current_pins, executor=native_double)
    assert result["status"] == "ready", result
    updated = received[0]
    assert {key: value for key, value in updated.items() if key != "engine"} == {key: value for key, value in params.items() if key != "engine"}
    provenance = result["repair"]["numerical_upgrades"][0]
    assert provenance["changed"] and provenance["before"]["engine"] == params["engine"]
    assert provenance["after"]["engine"] == updated["engine"]
    assert result["candidate"].feature_log[0].id == "numerical"
    assert design.model_dump_json() == before


def test_ordinary_input_repair_does_not_refresh_numerical_pins():
    design = source()
    params = numerical("photoproduct-relax")
    design.feature_log = [row("numerical", "photoproduct-relax", params), design.feature_log[-1]]

    def old_engine(*_args):
        raise CommandContractError("Older numerical implementation", code="engine_mismatch")

    result = evaluate(design, request(set_input(feature="numerical", path=["photoproduct_id"], expected="lesion", value="other")),
        executor=old_engine, numerical_provider=lambda *_a: pytest.fail("Automatic numerical migration"))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "engine_mismatch"
    assert result["repair"]["completed_prefix"] == [] and result["repair"]["not_evaluated"] == ["later"]


@pytest.mark.parametrize("action", ["remove", "move", "source-free"])
def test_coating_upgrade_cannot_be_applied_to_nonpacking_particle_commands(action):
    params = ({"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 10.0}
              if action == "source-free" else {"_proof_version": 1, "coating_version": 1,
                                                "nanoparticle_id": "gold", "action": action})
    if action == "move":
        params["pose"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    design = source().copy_with(feature_log=[row("numerical", "nanoparticle-patch", params)])
    result = evaluate(design, request(upgrade_action(numerical("nanoparticle-patch"))),
        executor=lambda *_a: pytest.fail("Nonpacking upgrade executed"),
        numerical_provider=lambda *_a: pytest.fail("Nonpacking upgrade selected pins"))
    assert result["status"] in {"failed", "unverified"} and "candidate" not in result


@pytest.mark.parametrize("failure", ["expected_engine", "expected_template", "unknown_engine", "unknown_source", "qualification", "provider_fields"])
def test_numerical_upgrade_rejects_stale_or_unsupported_inputs_before_executor(failure):
    design = source()
    params = numerical("photoproduct-create")
    action = upgrade_action(params)
    if failure == "expected_engine":
        action["expected_engine"]["runtime_sha256"] = "f" * 64
    elif failure == "expected_template":
        action["expected_template"]["sha256"] = "f" * 64
    elif failure == "unknown_engine":
        params["engine"]["id"] = "unknown-solver"
    elif failure == "unknown_source":
        params["source"]["kind"] = "physical-snapshot"
    design.feature_log = [row("numerical", "photoproduct-create", params)]

    def provider(kind, inputs):
        if failure == "qualification":
            raise CommandContractError("Template no longer qualified", code="template_unavailable")
        pins = current_pins(kind, inputs)
        if failure == "provider_fields":
            pins["history_seed"] = str(UUID(int=123))
        return pins

    result = evaluate(design, request(action), numerical_provider=provider,
                      executor=lambda *_a: pytest.fail("Rejected upgrade reached solver"))
    assert result["status"] in {"failed", "unverified"} and "candidate" not in result
    if failure == "qualification":
        assert result["status"] == "unverified"
        assert result["issues"][0]["feature_id"] == "numerical"


def test_repair_uses_existing_recovery_budget_and_never_returns_incomplete_candidate(monkeypatch):
    monkeypatch.setattr("backend.api.part_recovery_budget.MAX_RECOVERY_BYTES", 1)
    result = evaluate(source())
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "command_limit"
    assert "candidate" not in result


@pytest.mark.parametrize("changes", [
    {"repair_version": True}, {"repair_version": 2}, {"expected_revision": True}, {"expected_revision": -1},
    {"actions": []}, {"actions": [set_input()] * 65}, {"new_engine": {}},
    {"actions": [set_input(path=["x", True])]}, {"actions": [set_input(path=["x", -1])]},
    {"actions": [set_input(path=["x"] * 17)]}, {"actions": [set_input(value=object())]},
    {"actions": [set_input(value=float("nan"))]}, {"actions": [set_input(value="x" * 256_000)]},
    {"actions": [set_input(value=[0] * 10_001)]},
    {"actions": [{**upgrade_action(numerical("duplex-relax")), "engine": {}}]},
])
def test_strict_bounded_request_rejects_arbitrary_pins_objects_and_ambiguous_paths(changes):
    with pytest.raises(ValidationError):
        repair.RepairRequest.model_validate(request(**changes))


def test_repairing_displayed_stale_geometry_does_not_preserve_it_as_authoring():
    design = source()
    result = evaluate(design)
    expected = create_empty_part("Repair source", "HONEYCOMB")
    expected.nanoparticles = [Nanoparticle(id="gold", diameter_nm=12), Nanoparticle(id="future", diameter_nm=8)]
    assert result["candidate"].model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
