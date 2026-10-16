"""Closed ordinary pose inputs; no live state, geometry or publication."""

from copy import deepcopy

import pytest

from backend.core.part_command_errors import CommandContractError


SEED = "8107c358-a2a4-4434-a6fe-3092fe3b2434"


def service():
    from backend.api import part_transform_inputs
    return part_transform_inputs


def pose(**values):
    return {"kind": "base", "helix_id": "helix", "bp_index": 4,
        "direction": "FORWARD", "copy_k": 0, "crossover_id": None,
        "extra_base_k": None, "pivot": [0, 0, 0], "translation": [1, 2, 3],
        "rotation": [0, 0, 0, 1], "compose": False, **values}


def inputs(kind):
    metadata = {"_proof_version": 1}
    if kind == "cluster_op":
        return {**metadata, "cluster_id": "placement", "translation": [1, 2, 3],
            "rotation": [0, 0, 0, 1], "pivot": [4, 5, 6], "name": "Arm",
            "helix_ids": ["helix"], "domain_ids": [{"strand_id": "strand", "domain_index": 0}],
            "color": "#123456", "opacity": .5}
    if kind == "nucleotide-transform-delete":
        return {**metadata, "transform_id": "old-pose", "target": ["base", "helix", 4, "FORWARD", 0]}
    return {**metadata, "history_seed": SEED,
            **({"transforms": [pose()]} if kind.endswith("-batch") else pose())}


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"])
def test_untouched_complete_inputs_are_independently_owned(kind):
    previous = inputs(kind)
    original = deepcopy(previous)
    result = service().normalize(kind, previous, {})
    assert result == original
    for value in result.values():
        if isinstance(value, list):
            value.clear()
    assert previous == original


def test_complete_placement_controls_and_target_are_authored_inputs():
    previous = inputs("cluster_op")
    patch = {"cluster_id": "other", "translation": [-1, 4, 2], "rotation": [0, 0, 1, 0],
        "pivot": [3, 2, 1], "name": "Renamed", "helix_ids": [], "domain_ids": [],
        "color": None, "opacity": .25}
    original = deepcopy(patch)
    result = service().normalize("cluster_op", previous, patch)
    assert all(result[key] == value for key, value in patch.items())
    result["translation"].clear()
    assert patch == original and previous == inputs("cluster_op")


@pytest.mark.parametrize("batch", [False, True])
def test_all_residue_target_and_pose_controls_preserve_exact_saved_namespace(batch):
    kind = "nucleotide-transform-batch" if batch else "nucleotide-transform"
    changed = pose(kind="extra_base", helix_id=None, bp_index=None, direction=None,
        crossover_id="junction", extra_base_k=2, pivot=[1, 2, 3], translation=[3, 2, 1],
        rotation=[0, 1, 0, 0], compose=True)
    patch = {"transforms": [changed]} if batch else changed
    result = service().normalize(kind, inputs(kind), patch)
    assert result["history_seed"] == SEED and result["_proof_version"] == 1
    assert (result["transforms"][0] if batch else {k: result[k] for k in changed}) == changed


@pytest.mark.parametrize("kind,patch", [
    ("cluster_op", {"translation": [True, 0, 0]}),
    ("cluster_op", {"rotation": [0, 0, 0, 0]}),
    ("cluster_op", {"pivot": [0, float("inf"), 0]}),
    ("cluster_op", {"helix_ids": [""]}),
    ("cluster_op", {"domain_ids": [{"strand_id": "s", "domain_index": True}]}),
    ("cluster_op", {"domain_ids": [{"strand_id": "s", "domain_index": -1}]}),
    ("cluster_op", {"domain_ids": [{"strand_id": "s", "domain_index": 0, "extra": 1}]}),
    ("cluster_op", {"opacity": True}),
    ("cluster_op", {"name": 4}),
    ("nucleotide-transform", {"bp_index": False}),
    ("nucleotide-transform", {"bp_index": "3"}),
    ("nucleotide-transform", {"copy_k": -1}),
    ("nucleotide-transform", {"copy_k": True}),
    ("nucleotide-transform", {"direction": "sideways"}),
    ("nucleotide-transform", {"direction": []}),
    ("nucleotide-transform", {"kind": {}}),
    ("nucleotide-transform", {"compose": 1}),
    ("nucleotide-transform", {"rotation": [0, 0, 0, 0]}),
    ("nucleotide-transform", {"crossover_id": "contradictory"}),
    ("nucleotide-transform", {"translation": [0, 0, "1"]}),
    ("nucleotide-transform-batch", {"transforms": []}),
    ("nucleotide-transform-batch", {"transforms": [pose(), pose()]}),
    ("nucleotide-transform-batch", {"transforms": [{**pose(), "unknown": 4}]}),
    ("nucleotide-transform-delete", {"transform_id": ""}),
    ("nucleotide-transform-delete", {"target": ["base", "helix", True, "FORWARD", 0]}),
    ("nucleotide-transform-delete", {"target": ["base", "helix", 1, {}, 0]}),
])
def test_closed_strict_native_inputs_reject_malformed_values(kind, patch):
    previous = inputs(kind)
    before = deepcopy(previous)
    with pytest.raises(CommandContractError):
        service().normalize(kind, previous, patch)
    assert previous == before


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"])
@pytest.mark.parametrize("key,value", [("_generator", {}), ("_generated_scope", {}), ("unknown", 1)])
def test_unknown_or_generated_saved_fields_are_not_silently_removed(kind, key, value):
    with pytest.raises(CommandContractError):
        service().normalize(kind, {**inputs(kind), key: value}, {})


@pytest.mark.parametrize("key,value", [("_proof_version", 2), ("history_seed", "other"),
    ("expected_revision", 5), ("expected_design_id", "other")])
def test_contract_and_transport_cannot_be_patched(key, value):
    previous = {**inputs("nucleotide-transform"), "expected_revision": 4, "expected_design_id": "design"}
    with pytest.raises(CommandContractError):
        service().normalize("nucleotide-transform", previous, {key: value})


def test_bounded_repeated_batch_refuses_before_native_body_parsing(monkeypatch):
    from backend.api.routes_nucleotide_transforms import NucleotideTransformBody
    monkeypatch.setattr(NucleotideTransformBody, "model_validate", lambda *_a, **_k: pytest.fail("parsed oversized body"))
    with pytest.raises(CommandContractError):
        service().normalize("nucleotide-transform-batch", inputs("nucleotide-transform-batch"),
            {"transforms": [pose()] * 10_001})


def test_extra_base_input_role_is_not_the_protected_crossover_output_namespace():
    from backend.core.part_edit_identity import preserve_proof_identity
    previous = {**inputs("nucleotide-transform"), "kind": "extra_base", "crossover_id": "old"}
    changed = {**previous, "crossover_id": "new", "history_seed": "forged"}
    assert preserve_proof_identity(previous, changed, kind="nucleotide-transform")["crossover_id"] == "new"
    assert preserve_proof_identity(previous, changed, kind="nucleotide-transform")["history_seed"] == SEED
    assert preserve_proof_identity(previous, changed, kind="crossover-place")["crossover_id"] == "old"


def test_cluster_overlay_rejects_transport_it_cannot_represent_in_its_typed_row():
    with pytest.raises(CommandContractError):
        service().normalize("cluster_op", {**inputs("cluster_op"), "expected_revision": 1}, {})


def _reset_fixture():
    from backend.core.models import Design, NucleotideTransform, SnapshotLogEntry

    body = {key: value for key, value in pose().items() if key != "compose"}
    first = NucleotideTransform(id="first-pose", **body)
    second = NucleotideTransform(id="second-pose", **{**body, "bp_index": 5})
    prefix = Design(nucleotide_transforms=[first, second])
    entry = SnapshotLogEntry(id="reset", op_kind="nucleotide-transform-delete", label="Reset",
        params={"_proof_version": 1, "transform_id": first.id, "target": list(first.target_key())})
    return prefix, entry, first, second


@pytest.mark.parametrize("retarget", [False, True])
def test_explicit_reset_target_must_agree_with_selected_prefix_transform(retarget):
    prefix, entry, first, second = _reset_fixture()
    patch = ({"transform_id": second.id, "target": list(first.target_key())} if retarget else
             {"target": list(second.target_key())})
    original_prefix, original_entry = prefix.model_dump_json(), entry.model_dump_json()
    original_patch = deepcopy(patch)
    with pytest.raises(CommandContractError) as caught:
        service().edit_transform_entry(entry, patch, prefix)
    assert caught.value.code == "invalid_transform_input"
    assert prefix.model_dump_json() == original_prefix and entry.model_dump_json() == original_entry
    assert patch == original_patch


@pytest.mark.parametrize("explicit_target", [False, True])
def test_reset_id_retarget_recomputes_receipt_and_accepts_matching_explicit_receipt(explicit_target):
    prefix, entry, first, second = _reset_fixture()
    patch = {"transform_id": second.id}
    if explicit_target:
        patch["target"] = list(second.target_key())
    result = service().edit_transform_entry(entry, patch, prefix)
    assert result.params == {"_proof_version": 1, "transform_id": second.id, "target": list(second.target_key())}
    assert entry.params["target"] == list(first.target_key())
