"""Recognized gold definitions remain repairable without certifying bad inputs.

These tests exercise the public metadata/draft adapters and registered native
repair path. No permissive dependency fake can confer command authority.
"""

from copy import deepcopy
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import create_model
import pytest

from backend.api import doc_context, part_repair_input_metadata as metadata, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_repair import prepare_repair
from backend.api.routes_feature_log import router
from backend.core.models import MinorMutationLogEntry, Nanoparticle, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import describe
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft_evaluation import compile_draft_evaluation
from backend.core.part_repair_expectations import encode_expected_old


POSE = [1.0, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
PATH = "/api/design/features/repair-draft"


def params(**values):
    return {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", **values}


def row(identity, kind, values):
    return SnapshotLogEntry(id=identity, op_kind=kind, label=f"Keep {identity}", timestamp="2026-10-15T12:00:00Z",
        params=values, design_snapshot_gz_b64="poisoned before", post_state_gz_b64="poisoned after")


def broken(case="patch-diameter", old=-1.0):
    design = create_empty_part("Recognized invalid gold", "HONEYCOMB")
    design.id = "invalid-gold-part"
    target = "create" if case == "create-diameter" else "edit"
    field = "pose" if case == "patch-pose" else "diameter_nm"
    invalid = [1.0, 2.0, 3.0] if case == "patch-pose" else old
    fixed = list(POSE) if field == "pose" else 14.25
    design.feature_log = [row("create", "nanoparticle-create", params(diameter_nm=10.0))]
    if target == "create":
        design.feature_log[0].params[field] = invalid
    else:
        design.feature_log.append(row("edit", "nanoparticle-patch", params(**{field: invalid})))
    # The consumer must execute after the repaired producer. Its complementary
    # field leaves the repaired geometry visible in the final result.
    downstream = {"diameter_nm": 14.25} if field == "pose" else {"pose": list(POSE)}
    design.feature_log.append(row("later", "nanoparticle-patch", params(**downstream)))
    design.nanoparticles = [Nanoparticle(id="unlogged-output", diameter_nm=999.0)]
    action = {"action": "set_input", "feature_id": target, "parameter_path": [field],
        "expected_old": deepcopy(invalid), "expected_old_json": encode_expected_old(invalid), "value": fixed}
    return design, action


def repaired(design, *actions, executor=execute):
    return prepare_repair(design, {"repair_version": 1, "expected_design_id": design.id,
        "expected_revision": 7, "actions": list(actions)}, source_revision=7,
        executor=executor, dependency_resolver=dependencies,
        numerical_provider=lambda *_a: pytest.fail("Gold scalar repair selected numerical pins"))


@pytest.mark.parametrize("case", ["create-diameter", "patch-diameter", "patch-pose"])
def test_invalid_existing_gold_input_regenerates_from_root_and_reexecutes_downstream(case):
    source, action = broken(case)
    target = next(entry for entry in source.feature_log if entry.id == action["feature_id"])
    assert not dependencies(target.op_kind, target.params).known
    original, calls = source.model_dump_json(), []

    def native(kind, current, values):
        calls.append((kind, values))
        assert not any(particle.id == "unlogged-output" for particle in current.nanoparticles)
        return execute(kind, current, values)

    result = repaired(source, action, executor=native)
    assert result["status"] == "ready", result
    candidate = result["candidate"]
    assert result["repair"]["completed_prefix"] == [entry.id for entry in source.feature_log]
    assert len(calls) == len(source.feature_log) and not result["repair"]["old_state_verified"]
    assert [(item.id, item.diameter_nm, item.pose.values) for item in candidate.nanoparticles] == [("gold", 14.25, POSE)]
    assert candidate.id == source.id and candidate.recipe_root == source.recipe_root
    assert source.model_dump_json() == original
    oracle = create_empty_part(source.recipe_root.initial_name, source.lattice_type)
    for old, new in zip(source.feature_log, candidate.feature_log):
        assert (new.id, new.label, new.timestamp) == (old.id, old.label, old.timestamp)
        assert new.design_snapshot_gz_b64 and new.design_snapshot_gz_b64 != "poisoned before"
        assert new.post_state_gz_b64 and new.post_state_gz_b64 != "poisoned after"
        assert dependencies(new.op_kind, new.params).known
        oracle = execute(new.op_kind, oracle, new.params)
        new.design_snapshot_gz_b64 = new.post_state_gz_b64 = "poisoned again"
    assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == oracle.model_dump(mode="json", include=AUTHORING_FIELDS)
    proof = assess_part_history(candidate, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof


@pytest.mark.parametrize("old", [0.0, 1001.0, "too large", True, None])
def test_existing_invalid_diameter_values_are_editable_without_default_substitution(old):
    source, action = broken("create-diameter", old)
    result = repaired(source, action)
    assert result["status"] == "ready", result
    assert result["candidate"].feature_log[0].params["diameter_nm"] == 14.25
    assert source.feature_log[0].params["diameter_nm"] == old


@pytest.mark.parametrize("case", ["create-diameter", "patch-diameter", "patch-pose"])
def test_invalid_gold_metadata_exposes_actual_value_but_no_unusable_reference_search(case, monkeypatch):
    source, action = broken(case)
    entry = next(entry for entry in source.feature_log if entry.id == action["feature_id"])
    monkeypatch.setattr("backend.api.part_proof_commands.execute", lambda *_a: pytest.fail("Input inspection executed geometry"))
    monkeypatch.setattr("backend.core.part_history_proof.digest", lambda *_a: pytest.fail("Input inspection performed proof hashing"))
    result = metadata.describe_inputs(entry.op_kind, entry.params)
    assert result["definition_supported"] and result["inputs_valid"] is False and result["reason"]
    field = next(field for field in result["fields"] if field["parameter_path"] == action["parameter_path"])
    assert field["expected_old"] == action["expected_old"]
    assert field["expected_old_json"] == action["expected_old_json"]
    assert not any(field["input_type"] == "reference" for field in result["fields"])
    assert not any(field["parameter_path"] == ["nanoparticle_id"] for field in result["fields"])


@pytest.mark.parametrize("field,value", [
    ("_proof_version", None), ("_proof_version", True), ("_proof_version", "1"), ("_proof_version", 2),
    ("nanoparticle_version", None), ("nanoparticle_version", True), ("nanoparticle_version", 1.0),
    ("nanoparticle_version", 2), ("nanoparticle_id", None), ("nanoparticle_id", True),
    ("nanoparticle_id", ""), ("nanoparticle_id", "x" * 257),
    ("_generated_scope", {}), ("coating_version", None), ("thiol_version", 1),
    ("quantum_dot_version", 1), ("unknown", "value"), ("engine", {}), ("source", {}),
    ("gizmo_move", {"rotation": [0, 0, 0, 0]}), ("coating", {"seed": 1}),
])
def test_invalid_input_recognition_cannot_promote_missing_or_forged_envelopes(field, value):
    source, action = broken("patch-diameter" if field in {"gizmo_move", "coating"} else "create-diameter")
    entry = next(entry for entry in source.feature_log if entry.id == action["feature_id"])
    values = entry.params
    if value is None and field in {"_proof_version", "nanoparticle_version", "nanoparticle_id"}:
        values.pop(field)
    else:
        values[field] = value
    assert not dependencies(entry.op_kind, values).known
    result = repaired(source, action, executor=lambda *_a: pytest.fail("Unrecognized definition executed"))
    assert result["issues"][0]["code"] == "missing_proof_contract" and "candidate" not in result
    assert not metadata.describe_inputs(entry.op_kind, values)["definition_supported"]


@pytest.mark.parametrize("value", [-2.0, 1001.0, "14.25", True, None])
def test_repaired_final_schema_is_checked_before_any_native_execution(value):
    source, action = broken("create-diameter")
    result = repaired(source, {**action, "value": value}, executor=lambda *_a: pytest.fail("Invalid final inputs executed"))
    assert result["issues"][0]["code"] == "invalid_repaired_contract" and "candidate" not in result


@pytest.mark.parametrize("field,new", [("nanoparticle_id", "replacement"), ("_proof_version", 2), ("nanoparticle_version", 2)])
def test_recognized_invalid_inputs_keep_existing_output_and_version_protection(field, new):
    source, action = broken("create-diameter")
    old = source.feature_log[0].params[field]
    protected = {**action, "parameter_path": [field], "expected_old": old,
                 "expected_old_json": encode_expected_old(old), "value": new}
    result = repaired(source, action, protected, executor=lambda *_a: pytest.fail("Protected identity edit executed"))
    assert result["issues"][0]["code"] == "protected_recipe_identity" and "candidate" not in result


def test_invalid_input_recognition_does_not_substitute_current_values_for_stale_expectations():
    source, action = broken()
    action.update(expected_old=-2.0, expected_old_json="-2.0")
    result = repaired(source, action, executor=lambda *_a: pytest.fail("Stale input expectation executed"))
    assert result["issues"][0]["code"] == "repair_conflict" and "candidate" not in result


def test_generator_metadata_is_inert_and_cannot_supply_missing_output_identity():
    from backend.api.part_repair_contracts import recognizes_invalid_inputs
    from backend.core.part_repair_inputs import SetInput
    from backend.core.part_repair_planning import plan_actions

    source, action = broken("create-diameter")
    generator = {"description": "gold", "editable": ["nanoparticle_id"], "nanoparticle_id": "invented"}
    source.feature_log[0].params["_generator"] = generator
    planned = plan_actions(source, [SetInput.model_validate(action)], dependencies=dependencies,
                           recognize_invalid=recognizes_invalid_inputs)
    assert planned["create"].params["_generator"] == generator
    assert planned["create"].params["nanoparticle_id"] == "gold"
    result = repaired(source, action)
    assert result["status"] == "ready", result
    assert result["candidate"].feature_log[0].params["_generator"] == generator
    assert result["candidate"].nanoparticles[0].id == "gold"
    source.feature_log[0].params.pop("nanoparticle_id")
    result = repaired(source, action, executor=lambda *_a: pytest.fail("Generator annotation supplied native authority"))
    assert result["issues"][0]["code"] == "missing_proof_contract" and "candidate" not in result


def test_valid_scalar_correction_does_not_certify_missing_native_target():
    source, action = broken()
    source.feature_log[1].params["nanoparticle_id"] = "missing"
    result = repaired(source, action)
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["code"] == "missing_reference"
    assert result["issues"][0]["feature_id"] == "edit"
    assert result["repair"]["completed_prefix"] == ["create"]
    assert result["repair"]["not_evaluated"] == ["later"]


def test_generic_registered_kind_cannot_add_missing_nested_output_identity():
    source, _ = broken()
    old = [{"helix_a": "a", "helix_b": "b", "bp_a": 1, "bp_b": 1}]
    child = MinorMutationLogEntry(id="child", op_subtype="crossover-place-batch", label="Incomplete IDs",
        params={"_proof_version": 1, "placements": old})
    source.feature_log = [RoutingClusterLogEntry(id="group", label="Routing", children=[child])]
    assert not dependencies(child.op_subtype, child.params).known
    action = {"action": "set_input", "feature_id": "group", "child_id": "child",
        "parameter_path": ["placements"], "expected_old": old, "expected_old_json": encode_expected_old(old),
        "value": [{**old[0], "crossover_id": "invented-output"}]}
    result = repaired(source, action, executor=lambda *_a: pytest.fail("A generic recognition shortcut executed"))
    assert result["issues"][0]["code"] == "missing_proof_contract" and "candidate" not in result


def test_gold_schema_expansion_requires_a_new_recognition_review(monkeypatch):
    from backend.api import part_repair_contracts as contracts

    expanded = create_model("FutureGoldCreate", __base__=contracts._GOLD["nanoparticle-create"],
                            auxiliary_output_id=(str | None, None))
    monkeypatch.setitem(contracts._GOLD, "nanoparticle-create", expanded)
    source, action = broken("create-diameter")
    result = repaired(source, action, executor=lambda *_a: pytest.fail("Unreviewed envelope executed"))
    assert result["issues"][0]["code"] == "missing_proof_contract" and "candidate" not in result


def test_recognition_cannot_synthesize_a_missing_required_editable_field():
    source, action = broken("create-diameter")
    source.feature_log[0].params.pop("diameter_nm")
    result = repaired(source, action, executor=lambda *_a: pytest.fail("Missing input was synthesized"))
    assert result["issues"][0]["code"] == "missing_proof_contract" and "candidate" not in result


@pytest.fixture
def document():
    identity = f"__invalid_gold_repair__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    source, action = broken()
    state.load_design(source)
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            yield client, {"X-NADOC-Doc": identity}, action
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def draft_request(operation, **extra):
    source, revision = state.get_design_with_revision()
    draft = source.repair_draft
    return {"draft_version": 1, "operation": operation,
        "expected_design_id": source.id, "expected_revision": revision,
        "expected_draft_id": None if draft is None else draft.draft_id,
        "expected_generation": None if draft is None else draft.generation, **extra}


def test_invalid_gold_draft_save_rebase_and_prepare_share_native_recognition(document, monkeypatch):
    client, headers, action = document
    source, revision = state.get_design_with_revision()
    original = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    with monkeypatch.context() as guard:
        guard.setattr("backend.api.part_proof_commands.execute", lambda *_a: pytest.fail("Draft planning executed geometry"))
        guard.setattr(state, "_snapshot_copy", lambda *_a: pytest.fail("Draft planning copied the whole source"))
        saved = client.post(PATH, headers=headers, json=draft_request("create", actions=[action]))
        assert saved.status_code == 200, saved.text
        rebased = client.post(PATH, headers=headers, json=draft_request("rebase"))
        assert rebased.status_code == 200, rebased.text
    current = state.get_or_404()
    assert state.revision() == revision + 2 and state.undo_depth() == 0
    assert current.feature_log is source.feature_log and current.nanoparticles is source.nanoparticles
    assert current.model_dump(mode="json", include=AUTHORING_FIELDS) == original
    assert current.repair_draft.actions[0].expected_old == -1.0
    assert current.repair_draft.actions[0].expected_old_json == "-1.0"
    body = draft_request("evaluate")
    body.pop("operation")
    captured = capture_draft_inputs(current, source_revision=state.revision(), draft=current.repair_draft)
    request = compile_draft_evaluation(captured, body)
    result = prepare_repair(current, request.model_dump(mode="json"), source_revision=state.revision(),
        executor=execute, dependency_resolver=dependencies)
    assert result["status"] == "ready", result
    assert result["candidate"].nanoparticles[0].diameter_nm == 14.25
    assert state.get_or_404() is current and state.undo_depth() == 0


def test_invalid_gold_and_explicit_source_replacement_share_draft_planning(document, monkeypatch):
    client, headers, action = document
    old = describe(b"HEADER missing original source\n", format="pdb", media_type="chemical/x-pdb")
    new = describe(b"HEADER selected replacement\n", format="pdb", media_type="chemical/x-pdb")
    source, revision = state.get_design_with_revision()
    source.feature_log.append(row("import", "protein-import", {
        "_proof_version": 1, "protein_version": 1, "importer_version": 1,
        "source": old.model_dump(mode="json"), "asset_id": "asset", "name": "Protein",
        "source_filename": "protein.pdb", "exclude_dna": True}))
    replacement = {"action": "set_input", "feature_id": "import", "parameter_path": ["source"],
        "expected_old": old.model_dump(mode="json"), "value": new.model_dump(mode="json")}
    monkeypatch.setattr("backend.api.part_proof_commands.execute", lambda *_a: pytest.fail("Source inspection executed geometry"))
    saved = client.post(PATH, headers=headers, json=draft_request("create", actions=[action, replacement]))
    assert saved.status_code == 200, saved.text
    current = state.get_or_404()
    inspected = client.post(f"{PATH}/source/inspect", headers=headers, json={
        "source_repair_version": 1, "operation": "stage_proposed",
        "expected_design_id": current.id, "expected_revision": state.revision(),
        "expected_draft_id": current.repair_draft.draft_id,
        "expected_generation": current.repair_draft.generation,
        "feature_id": "import", "parameter": "source", "source": new.model_dump(mode="json")})
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["expected_blob"]["state"] == "missing"
    assert current.input_sources == {} and current.feature_log[-1].params["source"] == old.model_dump(mode="json")
    assert current.feature_log[1].params["diameter_nm"] == -1.0
    assert state.revision() == revision + 1 and state.undo_depth() == 0
