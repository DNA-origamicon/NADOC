"""Private feature-stage previews derive native inputs without document mutation.

All fixtures are tiny owned models. There are no hosts, files, workers, routes,
or renderer claims in this first service checkpoint.
"""

from threading import Lock
from uuid import uuid4

import pytest

from backend.api import part_proof_commands
from backend.api.crud import BundleRequest
from backend.core.models import (
    ClusterCreateLogEntry,
    ClusterOpLogEntry,
    ClusterRigidTransform,
    DeformationLogEntry,
    DeformationOp,
    MinorMutationLogEntry,
    RoutingClusterLogEntry,
    SnapshotLogEntry,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_overlay_commands import command_input, edit_entry
from backend.core.part_verification_capture import capture


def _service():
    from backend.api import part_deformation_preview
    return part_deformation_preview


def _append(source, entry):
    kind, params = command_input(entry)
    updated = part_proof_commands.execute(kind, source, params)
    return updated.copy_with(
        id=source.id, recipe_root=source.recipe_root,
        feature_log=[*source.feature_log, entry],
    )


def native_source(kind="bend", *, grouped=False, scoped=False):
    source = create_empty_part("Private preview", "HONEYCOMB")
    params = BundleRequest(
        cells=[[0, 0], [0, 1]], length_bp=42, name="Private preview",
        history_seed=uuid4(),
    ).model_dump(mode="json")
    source = _append(source, SnapshotLogEntry(
        op_kind="bundle-create", label="Native bundle",
        params={**params, "_proof_version": 1},
        design_snapshot_gz_b64="poisoned-before", post_state_gz_b64="poisoned-after",
    ))
    cluster_ids = []
    if grouped:
        cluster = ClusterRigidTransform(
            id=str(uuid4()), name="Arm", helix_ids=[source.helices[0].id],
        )
        source = _append(source, ClusterCreateLogEntry(
            cluster_id=cluster.id, name=cluster.name, helix_ids=cluster.helix_ids,
            cluster_snapshot=cluster, proof_version=1,
        ))
        source = _append(source, ClusterOpLogEntry(
            cluster_id=cluster.id, translation=[2, 3, 1], rotation=[0, 0, 0, 1],
            pivot=[0, 0, 0], proof_version=1,
        ))
        cluster_ids = [cluster.id]
    targets = None
    if scoped:
        targets = [{"kind": "domain", "strand_id": source.strands[0].id, "domain_index": 0}]
    op = DeformationOp(
        id="preview-operation", type=kind, plane_a_bp=4, plane_b_bp=32,
        affected_helix_ids=[source.helices[0].id] if grouped else [h.id for h in source.helices],
        cluster_ids=cluster_ids, targets=targets,
        params={"kind": kind, **({"curvature_deg_per_bp": .25, "direction_deg": 0}
                               if kind == "bend" else {"total_degrees": 8})},
    )
    entry = DeformationLogEntry(
        id="edited-feature", deformation_id=op.id, op_snapshot=op, proof_version=1,
    )
    source = _append(source, entry)
    # Live recording retains the resolved native range definition.
    source.feature_log[-1] = entry.model_copy(update={"op_snapshot": source.deformations[-1]})
    return source


def owned_capture(source):
    # Mirror the future host requirement: capture while the source owner holds
    # its lock. prepare_from_capture itself must never reach live state.
    with Lock():
        return capture(source, preserve_entry_types=True)


def authoring(source):
    return source.model_dump(mode="json", include=AUTHORING_FIELDS)


def patch(kind):
    return {"type": kind, "plane_a_bp": 6, "plane_b_bp": 30,
            "params": {"kind": kind, **({"curvature_deg_per_bp": .5, "direction_deg": 20}
                                         if kind == "bend" else {"total_degrees": 16})}}


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_native_fixture_is_independently_reproducible_despite_poisoned_recovery(kind):
    source = native_source(kind)
    report = assess_part_history(source, execute=part_proof_commands.execute,
                                 dependencies=part_proof_commands.dependencies)
    assert report["status"] == "verified", report


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("grouped,scoped", [(False, False), (True, False), (False, True)])
def test_evaluation_matches_native_target_overlay_and_keeps_inputs_owned(kind, grouped, scoped):
    service = _service()
    source = native_source(kind, grouped=grouped, scoped=scoped)
    before = source.model_dump(mode="json")
    captured = owned_capture(source)
    prepared = service.prepare_from_capture(captured, "edited-feature")
    prefix = prepared.copy_prefix()
    assert prefix.feature_log == []
    assert prefix.deformations == []
    original = source.feature_log[-1]
    change = {**patch(kind), "cluster_ids": original.op_snapshot.cluster_ids}
    expected_entry = edit_entry(original, change)
    expected = part_proof_commands.execute(*_execution_args(prefix, expected_entry))
    expected_authoring = authoring(expected)
    evaluated = service.evaluate(prepared, change)
    assert authoring(evaluated.design) == expected_authoring
    assert evaluated.entry.id == original.id
    assert evaluated.entry.deformation_id == original.deformation_id
    assert evaluated.design.deformations[-1].id == original.deformation_id
    assert evaluated.stage == "feature"
    assert evaluated.source_equivalence_checked is False
    assert evaluated.downstream_evaluated is False
    assert source.model_dump(mode="json") == before
    assert captured.feature_log[-1].op_snapshot == original.op_snapshot
    # No derived preview result or returned control-context copy may corrupt the
    # retained prefix and alter the next slider evaluation.
    evaluated.design.helices[0].length_bp = 1
    evaluated.entry.op_snapshot.params = original.op_snapshot.params
    prefix.strands.clear()
    captured.feature_log[-1].op_snapshot.affected_helix_ids.clear()
    again = service.evaluate(prepared, change)
    assert authoring(again.design) == expected_authoring


def _execution_args(prefix, entry):
    kind, params = command_input(entry)
    return kind, prefix, params


def test_prepare_runs_prefix_once_and_sliders_never_prove_or_replay_suffix(monkeypatch):
    service = _service()
    source = native_source()
    suffix_op = source.deformations[-1].model_copy(update={"id": "later-operation"}, deep=True)
    source = _append(source, DeformationLogEntry(
        id="later-feature", deformation_id=suffix_op.id,
        op_snapshot=suffix_op, proof_version=1,
    ))
    calls = []
    original = service.execute

    def execute(kind, design, params):
        calls.append(kind)
        assert params.get("id") != "later-operation", "Preview evaluated unrelated suffix"
        return original(kind, design, params)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Preview entered full proof or recovery")

    from backend.api import part_recipe_edit, state
    import backend.core.part_history_contract as history
    monkeypatch.setattr(service, "execute", execute)
    monkeypatch.setattr(part_recipe_edit, "assess_part_history", forbidden)
    monkeypatch.setattr(history, "assess_part_history", forbidden)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    monkeypatch.setattr(state, "decode_design_snapshot", forbidden)
    prepared = service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert calls == ["bundle-create"]
    for angle in (1, 2, 3):
        service.evaluate(prepared, {"params": {"kind": "bend", "curvature_deg_per_bp": angle}})
    assert calls == ["bundle-create", "deformation", "deformation", "deformation"]


def test_preview_labels_unlogged_source_geometry_as_unchecked_and_does_not_use_it():
    service = _service()
    source = native_source()
    source.helices[0].length_bp = 43
    prepared = service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert prepared.copy_prefix().helices[0].length_bp == 42
    assert service.evaluate(prepared, {}).source_equivalence_checked is False
    assert source.helices[0].length_bp == 43


@pytest.mark.parametrize("change,code", [
    (lambda d: setattr(d, "recipe_root", None), "missing_recipe_root"),
    (lambda d: setattr(d, "recipe_root", d.recipe_root.model_copy(update={"source_json": "{}"})),
     "invalid_recipe_root"),
    (lambda d: setattr(d, "feature_log_cursor", 0), "historical_cursor"),
    (lambda d: setattr(d, "feature_log_sub_cursor", 0), "historical_cursor"),
    (lambda d: d.feature_log.append(d.feature_log[-1].model_copy(deep=True)), "ambiguous_feature"),
    (lambda d: setattr(d.feature_log[-1], "proof_version", None), "missing_proof_contract"),
    (lambda d: setattr(d.feature_log[-1], "deformation_id", "other-operation"), "invalid_preview_definition"),
    (lambda d: setattr(d.feature_log[-1], "op_snapshot", None), "invalid_preview_definition"),
])
def test_invalid_source_definition_refuses_before_native_execution(monkeypatch, change, code):
    service = _service()
    source = native_source()
    change(source)
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed refused prefix"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert caught.value.code == code


def test_unknown_suffix_refuses_before_any_prefix_replay(monkeypatch):
    service = _service()
    source = native_source()
    source.feature_log.append(SnapshotLogEntry.model_construct(
        id="unknown-suffix", op_kind="unknown-native-kind", label="Unknown",
        params={"_proof_version": 1},
    ))
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed refused prefix"))
    with pytest.raises(CommandContractError, match="unknown-suffix") as caught:
        service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert caught.value.code == "missing_proof_contract"


def test_missing_stable_feature_refuses(monkeypatch):
    service = _service()
    source = owned_capture(native_source())
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed missing selection"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(source, "missing-feature")
    assert caught.value.code == "missing_reference"


@pytest.mark.parametrize("collision", ["header", "child"])
def test_routing_identity_collision_refuses_before_replay(monkeypatch, collision):
    service = _service()
    captured = owned_capture(native_source())
    captured.feature_log.append(RoutingClusterLogEntry(
        id="edited-feature" if collision == "header" else "routing-parent",
        children=[MinorMutationLogEntry(
            id="edited-feature" if collision == "child" else "routing-child",
            op_subtype="nick", label="Ambiguous nick", params={"_proof_version": 1},
        )],
    ))
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed ambiguous history"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(captured, "edited-feature")
    assert caught.value.code == "ambiguous_feature"


def test_oversized_captured_input_refuses_before_replay(monkeypatch):
    service = _service()
    captured = owned_capture(native_source())
    captured.helices[0].id = "x" * 500_001
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed oversized capture"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(captured, "edited-feature")
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("change", [
    {"id": "replacement"}, {"targets": []}, {"affected_helix_ids": ["other"]},
    {"type": "twist"}, {"cluster_ids": ["missing-cluster"]},
    {"params": {"kind": "bend", "curvature_deg_per_bp": float("nan")}},
    {"params": {"kind": "bend", "unreviewed_field": 1}},
    {"plane_a_bp": 2, "plane_b_bp": 2},
])
def test_unsupported_or_malformed_patch_is_atomic_and_cannot_retarget(change):
    service = _service()
    prepared = service.prepare_from_capture(owned_capture(native_source()), "edited-feature")
    before = authoring(prepared.copy_prefix())
    with pytest.raises(CommandContractError):
        service.evaluate(prepared, change)
    assert authoring(prepared.copy_prefix()) == before
    assert service.evaluate(prepared, {}).design.deformations[-1].id == "preview-operation"


def test_prospective_bundle_allowance_refuses_before_allocation(monkeypatch):
    service = _service()
    source = owned_capture(native_source())
    source.feature_log[0].params["length_bp"] = 1_000_000
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Allocated oversized bundle"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(source, "edited-feature")
    assert caught.value.code == "preview_limit"


def test_deadline_is_cooperative_and_checked_before_native_work(monkeypatch):
    service = _service()
    source = owned_capture(native_source())
    clock = iter((0, 2))
    monkeypatch.setattr(service, "monotonic", lambda: next(clock, 2))
    monkeypatch.setattr(service, "execute", lambda *_args: pytest.fail("Executed after deadline"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(source, "edited-feature")
    assert caught.value.code == "preview_limit"


def test_native_failure_keeps_retained_prefix_usable(monkeypatch):
    service = _service()
    prepared = service.prepare_from_capture(owned_capture(native_source()), "edited-feature")
    original = service.execute

    def failed(_kind, private, _params):
        private.strands.clear()
        raise ValueError("Native endpoint fit refused")

    with monkeypatch.context() as fault:
        fault.setattr(service, "execute", failed)
        with pytest.raises(CommandContractError, match="Native endpoint fit refused"):
            service.evaluate(prepared, {})
    monkeypatch.setattr(service, "execute", original)
    assert service.evaluate(prepared, {}).design.strands
