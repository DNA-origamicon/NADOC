"""Typed replacement previews use a root-derived prefix, never saved geometry."""

from copy import deepcopy
import json

from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from backend.api import part_repair_selection as selection
from backend.api.part_nanoparticle_commands import build as gold_build
from backend.api.part_proof_commands import dependencies
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_dependencies import Dependencies
from backend.core.part_history_proof import command_rows, import_root
from tests.test_part_element_copy_commands import inputs as copy_inputs, source as rigid_source
from tests.test_part_recipe_repair import gold_params, row, source


def request(**changes):
    return {"selection_version": 1, "expected_design_id": "repair-part", "expected_revision": 7,
            "feature_id": "patch", "parameter_path": ["nanoparticle_id"], "expected_old": "missing", **changes}


def evaluate(design, body=None, **options):
    return selection.prepare_selection(design, request() if body is None else body,
        source_revision=options.pop("source_revision", 7), executor=options.pop("executor", gold_build),
        dependency_resolver=options.pop("dependency_resolver", dependencies), **options)


def imported(design, kind, params):
    design = design.copy_with(id="repair-part", recipe_root=None, feature_log=[])
    return design.copy_with(recipe_root=import_root(design), feature_log=[row("patch", kind, params)])


def identities(result):
    assert result["status"] == "preview", result
    assert "candidate" not in result and "validation" not in result
    return [item["identity"] for item in result["selection"]["candidates"]]


def protein_params(identity="missing", **changes):
    return {"_proof_version": 1, "protein_version": 1, "attachment_id": identity, **changes}


def test_broken_target_uses_only_replayed_prefix_without_old_proof_or_recovery(monkeypatch):
    from backend.api import state
    from backend.core import part_history_contract

    design = source()
    before = design.model_dump_json()
    monkeypatch.setattr(part_history_contract, "assess_part_history", lambda *_a, **_k: pytest.fail("Old proof gate"))
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_a: pytest.fail("Recovery decoded"))
    calls = []

    def execute(kind, current, params):
        calls.append(kind)
        assert kind == "nanoparticle-create", "Target or suffix executed during selection"
        return gold_build(kind, current, params)

    result = evaluate(design, executor=execute)
    assert identities(result) == ["gold"]
    assert result["selection"]["completed_prefix"] == ["create"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]
    assert calls == ["nanoparticle-create"] and not result["native_editable"]
    assert result["selection"]["prefix_only"] and result["selection"]["selection_supported"]
    assert not result["selection"]["whole_command_validated"]
    assert not result["selection"]["whole_recipe_validated"]
    assert design.model_dump_json() == before


def test_deleted_and_future_and_unlogged_objects_are_excluded():
    design = source()
    design.feature_log.insert(1, row("delete", "nanoparticle-delete", gold_params("gold")))
    design.nanoparticles.append(m.Nanoparticle(id="future", diameter_nm=8))
    result = evaluate(design)
    assert identities(result) == []
    assert result["selection"]["completed_prefix"] == ["create", "delete"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]


def test_unsupported_future_contract_does_not_gate_selection_from_a_healthy_prefix():
    design = source()
    design.feature_log[-1].params = {"legacy": "not replayable"}
    assert identities(evaluate(design)) == ["gold"]


@pytest.mark.parametrize("changes,revision", [({"expected_design_id": "other"}, 7),
    ({"expected_revision": 8}, 7), ({}, 8), ({}, True), ({"expected_old": "stale"}, 7)])
def test_expected_identity_revision_and_old_value_precede_replay(changes, revision):
    result = evaluate(source(), request(**changes), source_revision=revision,
                      executor=lambda *_a: pytest.fail("Stale selection executed"))
    assert result["status"] == "failed" and result["issues"][0]["code"] == "selection_conflict"
    assert result["selection"]["candidates"] == []


@pytest.mark.parametrize("failure,status,code", [("reference", "failed", "missing_reference"),
    ("source", "unverified", "source_unavailable"), ("engine", "unverified", "engine_mismatch"),
    ("validation", "failed", "invalid_command_inputs"), ("timeout", "unverified", "evaluation_rejected")])
def test_prefix_failure_reports_first_failure_and_later_not_evaluated(failure, status, code):
    design = source()
    design.feature_log.insert(1, row("broken-prefix", "nanoparticle-patch", gold_params("gone", diameter_nm=9.0)))
    before = design.model_dump_json()

    def execute(kind, current, params):
        if kind == "nanoparticle-create":
            return gold_build(kind, current, params)
        current.nanoparticles[0].diameter_nm = 777
        params["nanoparticle_id"] = "executor-mutated"
        if failure == "reference":
            raise ReferenceResolutionError("Missing input", references=[{
                "kind": "nanoparticle", "identity": "gone", "parameter_path": ["nanoparticle_id"]}])
        if failure in {"source", "engine"}:
            raise CommandContractError("Environment cannot reproduce prefix", code=code)
        if failure == "timeout":
            raise HTTPException(408, detail="deadline")
        raise ValueError("Invalid authored input")

    result = evaluate(design, executor=execute)
    assert result["status"] == status and result["issues"][0]["code"] == code
    assert result["issues"][0]["feature_id"] == "broken-prefix"
    assert result["selection"]["completed_prefix"] == ["create"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]
    assert result["selection"]["candidates"] == [] and "candidate" not in result
    assert design.model_dump_json() == before


def test_internal_executor_defect_is_not_disguised_as_repairable_reference():
    def broken(*_a):
        raise KeyError("internal defect")
    with pytest.raises(KeyError, match="internal defect"):
        evaluate(source(), executor=broken)


def test_unknown_prefix_is_unverified_without_running_it():
    result = evaluate(source(), dependency_resolver=lambda kind, _p: Dependencies(known=kind != "nanoparticle-create"),
                      executor=lambda *_a: pytest.fail("Unknown prefix executed"))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "missing_proof_contract"
    assert result["issues"][0]["feature_id"] == "create"
    assert result["selection"]["not_evaluated"] == ["patch", "later"]


@pytest.mark.parametrize("change,code", [
    (lambda d: setattr(d, "recipe_root", None), "missing_or_unsupported_recipe_root"),
    (lambda d: setattr(d, "recipe_root", d.recipe_root.model_copy(update={"version": 2})), "missing_or_unsupported_recipe_root"),
    (lambda d: setattr(d, "feature_log_cursor", 0), "historical_cursor"),
    (lambda d: setattr(d, "feature_log_sub_cursor", 0), "historical_cursor"),
    (lambda d: setattr(d.feature_log[1], "id", "create"), "ambiguous_feature_identity"),
])
def test_root_cursor_and_identity_admission_fail_before_replay(change, code):
    design = source()
    change(design)
    result = evaluate(design, executor=lambda *_a: pytest.fail("Unadmitted prefix executed"))
    assert result["issues"][0]["code"] == code and result["selection"]["candidates"] == []


@pytest.mark.parametrize("params,path", [
    ({"_generated_scope": {}}, ["nanoparticle_id"]),
    ({"coating_version": 1}, ["nanoparticle_id"]),
    ({"thiol_version": 1}, ["nanoparticle_id"]),
    ({"nanoparticle_version": 2}, ["nanoparticle_id"]),
    ({"_proof_version": 0}, ["nanoparticle_id"]),
    ({"_proof_version": True}, ["nanoparticle_id"]),
    ({}, ["_proof_version"]), ({}, ["diameter_nm"]), ({}, ["engine", "implementation"]),
    ({}, ["unknown"]), ({}, ["nanoparticle_id", 0]),
])
def test_unknown_protected_scoped_and_other_version_slots_are_explicitly_unsupported(params, path):
    design = source()
    design.feature_log[1].params.update(params)
    result = evaluate(design, request(parameter_path=path), executor=lambda *_a: pytest.fail("Unsupported selector replayed"))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "unsupported_reference_slot"
    assert not result["selection"]["selection_supported"]


def test_created_output_identity_cannot_be_picked_and_text_metadata_is_not_a_reference():
    design = source()
    result = evaluate(design, request(feature_id="create", expected_old="gold"))
    assert result["issues"][0]["code"] == "unsupported_reference_slot"
    design.feature_log[1].label = "missing"
    design.feature_log[1].params["_generator"] = {"missing": "missing", "label": "missing"}
    before = design.model_dump_json()
    assert identities(evaluate(design)) == ["gold"]
    assert design.model_dump_json() == before


def test_gold_and_quantum_dot_candidates_use_exact_kind_and_current_ownership(monkeypatch):
    from backend.core import quantum_dots
    design = rigid_source()
    base = design.nanoparticles[0]
    design.nanoparticles.extend(base.model_copy(deep=True, update={"id": identity})
                                for identity in ["coated", "biotin", "thiol", "connection"])
    design.nanoparticles[2].coating = m.StreptavidinCoating(target_count=1, protein=design.protein_assets[0])
    design.nanoparticles[3].biotin_dna = [m.BiotinDNA(strand_id="s", helix_id="h", chain="A")]
    design.nanoparticle_conjugations = [m.NanoparticleConjugation(nanoparticle_id="thiol", sequence="A",
        requested_count=1, estimated_capacity=1, density_per_nm2=0.1)]
    design.nanoparticle_connection_versions = [m.NanoparticleConnectionVersion(
        nanoparticle_id="connection", strand_id="s", overhang_id="o")]
    monkeypatch.setattr(quantum_dots, "catalog_entry", lambda *_a: pytest.fail("Selector read mutable catalog"))
    for kind in ["nanoparticle-patch", "nanoparticle-delete"]:
        assert identities(evaluate(imported(design, kind, gold_params("missing")))) == ["gold"]
        params = {"_proof_version": 1, "quantum_dot_version": 1, "nanoparticle_id": "missing"}
        assert identities(evaluate(imported(design, kind, params))) == ["dot"]


def test_free_asset_selection_checks_explicit_atom_and_returns_only_small_descriptors():
    design = rigid_source()
    asset = design.protein_assets[0]
    design.protein_assets.extend([
        asset.model_copy(deep=True, update={"id": "empty", "atoms": []}),
        asset.model_copy(deep=True, update={"id": "ambiguous-atom", "atoms": [*asset.atoms, asset.atoms[8]]}),
        asset.model_copy(deep=True, update={"id": "other", "name": "L" * 400}),
    ])
    params = protein_params(asset_id="missing", target={"kind": "free"}, conjugation_atom_serial=9,
                            handle_complement_bp=0, handle_spacer_nt=0)
    result = evaluate(imported(design, "protein-attach", params), request(parameter_path=["asset_id"]))
    assert identities(result) == ["asset", "other"]
    assert all(set(item) == {"kind", "identity", "label"} for item in result["selection"]["candidates"])
    assert len(result["selection"]["candidates"][1]["label"]) == 256
    encoded = json.dumps(result)
    assert all(key not in encoded for key in ['"atoms"', '"pose"', '"coordinates"', '"metadata"'])
    params["target"] = {"kind": "overhang", "overhang_id": "o", "attach_end": "free_end"}
    unsupported = evaluate(imported(design, "protein-attach", params), request(parameter_path=["asset_id"]))
    assert unsupported["issues"][0]["code"] == "unsupported_reference_slot"


@pytest.mark.parametrize("kind", ["protein-attach-patch", "protein-attach-delete"])
def test_free_attachment_filters_ownership_and_keeps_delete_independent_of_missing_asset(kind):
    design = rigid_source()
    template = design.protein_attachments[0]
    variants = [("missing-asset", {"asset_id": "gone"}), ("unselected", {"conjugation_atom_serial": None}),
        ("owned", {"binder_strand_id": "s"}), ("old-owned", {"azide_end": "5p"}),
        ("overhang", {"target": m.ProteinTargetDesign(overhang_id="o")})]
    design.protein_attachments.extend(template.model_copy(deep=True, update={"id": identity, **changes})
                                     for identity, changes in variants)
    result = evaluate(imported(design, kind, protein_params()), request(parameter_path=["attachment_id"]))
    assert identities(result) == (["protein", "missing-asset", "unselected"] if kind.endswith("delete") else ["protein"])
    conjugated = imported(design, kind, {**protein_params(), "conjugation_version": 1})
    assert evaluate(conjugated, request(parameter_path=["attachment_id"]))["issues"][0]["code"] == "unsupported_reference_slot"


def test_attachment_patch_can_offer_atom_reselection_but_final_command_remains_unvalidated():
    design = rigid_source()
    design.protein_attachments[0].conjugation_atom_serial = 999
    params = protein_params(conjugation_atom_serial=9)
    result = evaluate(imported(design, "protein-attach-patch", params), request(parameter_path=["attachment_id"]))
    assert identities(result) == ["protein"] and not result["selection"]["whole_command_validated"]


def test_copy_slot_filters_other_selected_outputs_and_respects_typed_namespaces():
    design = rigid_source()
    design.nanoparticles.extend(design.nanoparticles[0].model_copy(deep=True, update={"id": identity})
                                for identity in ["other", "output", "protein-copy"])
    params = copy_inputs(nanoparticle_ids=["missing", "gold"], nanoparticle_output_ids=["output", "new-output"])
    result = evaluate(imported(design, "element-paste", params), request(parameter_path=["nanoparticle_ids", 0]))
    assert identities(result) == ["dot", "other", "protein-copy"]
    params["protein_ids"] = ["missing"]
    result = evaluate(imported(design, "element-paste", params), request(parameter_path=["protein_ids", 0]))
    assert identities(result) == ["protein"]
    for path, code in [(["protein_output_ids", 0], "unsupported_reference_slot"),
                       (["protein_ids", "0"], "unsupported_reference_slot"),
                       (["protein_ids", 1], "invalid_parameter_path")]:
        result = evaluate(imported(design, "element-paste", params), request(parameter_path=path))
        assert result["issues"][0]["code"] == code


def test_candidate_descriptor_is_not_a_promise_that_the_complete_copy_will_succeed():
    from backend.api.part_element_copy_commands import build

    design = rigid_source()
    params = copy_inputs(protein_ids=["missing-other-input"], nanoparticle_ids=["missing"],
                         nanoparticle_output_ids=["new-output"])
    result = evaluate(imported(design, "element-paste", params), request(parameter_path=["nanoparticle_ids", 0]))
    assert identities(result) == ["gold", "dot"]
    assert not result["selection"]["whole_command_validated"]
    with pytest.raises(ReferenceResolutionError):
        build("element-paste", design, {**params, "nanoparticle_ids": ["gold"]})


def test_copy_protein_requires_explicit_atom_and_bounded_captured_asset():
    design = rigid_source()
    design.protein_attachments.extend([
        design.protein_attachments[0].model_copy(update={"id": "unselected", "conjugation_atom_serial": None}),
        design.protein_attachments[0].model_copy(update={"id": "large", "asset_id": "large-asset"}),
    ])
    asset = design.protein_assets[0]
    design.protein_assets.append(asset.model_copy(update={"id": "large-asset", "atoms": [
        asset.atoms[0].model_copy(update={"serial": index + 1}) for index in range(1001)]}))
    params = copy_inputs(protein_ids=["missing"])
    result = evaluate(imported(design, "element-paste", params), request(parameter_path=["protein_ids", 0]))
    assert identities(result) == ["protein"]


def test_cross_kind_equal_ids_are_legal_but_same_kind_ambiguity_is_reported():
    design = rigid_source()
    design.protein_assets[0].id = design.protein_attachments[0].asset_id = "gold"
    design.protein_attachments[0].id = "gold"
    assert identities(evaluate(imported(design, "nanoparticle-patch", gold_params("missing")))) == ["gold"]
    design.nanoparticles.append(deepcopy(design.nanoparticles[0]))
    result = evaluate(imported(design, "nanoparticle-patch", gold_params("missing")))
    assert result["status"] == "failed" and result["issues"][0]["code"] == "invalid_selection"
    assert result["issues"][0]["references"] == [{"kind": "nanoparticle", "identity": "gold",
                                                  "parameter_path": ["nanoparticle_id"]}]
    assert result["selection"]["candidates"] == []


@pytest.mark.parametrize("limit", [1, 100])
def test_preview_is_bounded_reports_truncation_and_preserves_source_order(limit):
    design = m.Design(nanoparticles=[m.Nanoparticle(id=f"gold-{i}", diameter_nm=10) for i in range(105)])
    result = evaluate(imported(design, "nanoparticle-delete", gold_params("missing")), request(limit=limit))
    assert identities(result) == [f"gold-{i}" for i in range(limit)]
    assert result["selection"]["eligible_count"] == 105 and result["selection"]["truncated"]
    assert result["selection"]["limit"] == limit


def test_mid_group_prefix_resolver_keeps_only_preceding_children_and_stable_ids():
    design = source()
    children = [m.MinorMutationLogEntry(id=f"child-{i}", op_subtype="nick", params={"ordinal": i}, label=f"Child {i}")
                for i in range(3)]
    group = m.RoutingClusterLogEntry(id="group", label="Routing", children=children,
                                   pre_state_gz_b64="poison", post_state_gz_b64="poison")
    design.feature_log.insert(1, group)
    before = design.model_dump_json()
    for child_index in range(3):
        target, log = selection.resolve_prefix(design, "group", f"child-{child_index}")
        assert target.id == f"child-{child_index}"
        assert [identity for identity, _, _ in command_rows(design.copy_with(feature_log=log), 2000)] == [
            "create", *(f"child-{i}" for i in range(child_index))]
        if child_index:
            assert log[-1].id == "group" and log[-1].label == "Routing"
    assert design.model_dump_json() == before
    # No admitted NP/protein/copy operation currently belongs to MinorOpSubtype.
    # Report that boundary honestly, rather than forging a child kind to pass.
    unsupported = evaluate(design, request(feature_id="group", child_id="child-1", parameter_path=["helix_id"]))
    assert unsupported["issues"][0]["code"] == "unsupported_reference_slot"


@pytest.mark.parametrize("body,code", [(request(feature_id="gone"), "missing_feature"),
    (request(child_id="child"), "invalid_selection_target"),
    (request(feature_id="group", child_id="gone"), "missing_feature")])
def test_missing_or_misbound_feature_and_child_ids_never_select_by_index(body, code):
    design = source()
    design.feature_log.append(m.RoutingClusterLogEntry(id="group", children=[]))
    result = evaluate(design, body, executor=lambda *_a: pytest.fail("Invalid stable target replayed"))
    assert result["issues"][0]["code"] == code


def test_recovery_and_command_limits_are_shared_and_checkpoint_can_stop_preview(monkeypatch):
    from backend.api import part_recovery_budget
    monkeypatch.setattr(part_recovery_budget, "MAX_RECOVERY_BYTES", 0)
    result = evaluate(source(), executor=lambda *_a: pytest.fail("Recovery limit ignored"))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "command_limit"
    design = source()
    design.feature_log.extend(row(f"later-{i}", "nanoparticle-delete", gold_params("future")) for i in range(2000))
    result = evaluate(design, executor=lambda *_a: pytest.fail("Command limit ignored"))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "entry_limit"

    def cancelled():
        raise HTTPException(408, detail="cancelled")
    result = evaluate(source(), checkpoint=cancelled)
    assert result["status"] == "unverified" and result["issues"][0]["http_status"] == 408
    assert result["selection"]["candidates"] == []


@pytest.mark.parametrize("changes", [{"selection_version": True}, {"selection_version": 2},
    {"expected_revision": True}, {"expected_revision": -1}, {"expected_old": 1}, {"feature_id": ""},
    {"parameter_path": [True]}, {"parameter_path": [-1]}, {"parameter_path": []},
    {"parameter_path": ["x"] * 17}, {"limit": 0}, {"limit": 101}, {"output_id": "forbidden"}])
def test_request_schema_is_strict_and_bounded(changes):
    with pytest.raises(ValidationError):
        selection.SelectionRequest.model_validate(request(**changes))


def test_request_uses_existing_operation_budget_before_expensive_validation():
    with pytest.raises(ValidationError, match="structural budget"):
        selection.SelectionRequest.model_validate(request(unexpected=[None] * 10001))
