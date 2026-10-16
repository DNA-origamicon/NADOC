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


def _append_command(source, kind, params):
    """Author real native rows; recovery bytes are deliberately unusable."""
    params = {**params, "_proof_version": 1}
    if kind in part_proof_commands.PROOF_MINOR_KINDS:
        child = MinorMutationLogEntry(
            op_subtype=kind, label=kind, params=params,
            diff_added_b64="poison", diff_removed_b64="poison", diff_modified_b64="poison",
        )
        updated = part_proof_commands.execute(kind, source, params)
        row = RoutingClusterLogEntry(
            children=[child], pre_state_gz_b64="poison", post_state_gz_b64="poison",
        )
        return updated.copy_with(id=source.id, recipe_root=source.recipe_root,
                                 feature_log=[*source.feature_log, row])
    return _append(source, SnapshotLogEntry(
        op_kind=kind, label=kind, params=params,
        design_snapshot_gz_b64="poison", post_state_gz_b64="poison",
    ))


PREFIX_CASES = [
    "extrude-segment", "circle-segment", "extrude-continuation",
    "extrude-deformed-continuation", "extrude-frame", "sweep",
    "nick", "nick-batch", "strand-end-resize", "domain-shift", "ligate",
    "forced-ligation-create", "forced-ligation-delete", "forced-ligation-delete-batch",
    "crossover-place", "crossover-place-batch", "crossover-move", "crossover-move-batch",
    "crossover-delete", "crossover-delete-batch", "auto-crossover",
    "loop-skip-insert", "loop-skip-twist", "loop-skip-bend", "loop-skip-clear",
    "loop-skip-clear-all", "apply-loop-skips",
]


def _prefix_case(kind):
    from backend.api import crud
    from backend.api.routes_frame_extrusion import FrameExtrusionRequest
    from backend.core.sweep import SweepRequest

    source = native_source()
    entry = source.feature_log[-1]
    source = source.copy_with(feature_log=source.feature_log[:-1], deformations=[])
    helix = source.helices[0]
    strand = source.strands[0]
    domain = strand.domains[0]
    nick = dict(helix_id=domain.helix_id, bp_index=12, direction=domain.direction.value)

    def append(operation, values):
        nonlocal source
        source = _append_command(source, operation, values)

    if kind in {"extrude-segment", "circle-segment", "extrude-continuation",
                "extrude-deformed-continuation", "extrude-frame"}:
        values = dict(cells=[[4, 4]], history_seed=uuid4())
        if kind == "circle-segment":
            request = crud.CircleSegmentRequest(**values, cell_lengths=[21])
        elif kind == "extrude-deformed-continuation":
            request = crud.BundleDeformedContinuationRequest(
                **values, length_bp=21, grid_origin=[0, 0, 0], axis_dir=[0, 0, 1],
                frame_right=[1, 0, 0], frame_up=[0, 1, 0],
            )
        elif kind == "extrude-frame":
            request = FrameExtrusionRequest(
                **values, length_bp=21, plane="XY", expected_design_id=source.id,
                expected_revision=0,
            )
        else:
            schema = crud.BundleSegmentRequest if kind == "extrude-segment" else crud.BundleContinuationRequest
            request = schema(**values, length_bp=21)
        append(kind, request.model_dump(mode="json"))
    elif kind == "sweep":
        append(kind, SweepRequest(cells=[(4, 4)], points_nm=[(0, 0, 0), (0, 0, 10)],
                                  ligate_adjacent=False).model_dump(mode="json"))
    elif kind in {"nick", "nick-batch", "ligate"}:
        append("nick-batch" if kind == "nick-batch" else "nick",
               {"nicks": [nick]} if kind == "nick-batch" else nick)
        if kind == "ligate":
            append(kind, nick)
    elif kind in {"strand-end-resize", "domain-shift"}:
        values = dict(strand_id=strand.id, delta_bp=-2 if kind == "strand-end-resize" else 2)
        values.update(helix_id=domain.helix_id, end="3p") if kind == "strand-end-resize" else values.update(domain_index=0)
        append(kind, {"entries": [values]})
    elif kind.startswith("forced-ligation"):
        staples = [item for item in source.strands if item.strand_type == "staple"]
        append("forced-ligation-create", dict(three_prime_strand_id=staples[0].id,
            five_prime_strand_id=staples[1].id, _fl_id="preview-prefix-ligation"))
        if kind != "forced-ligation-create":
            append(kind, {"forced_ligation_ids": ["preview-prefix-ligation"]}
                   if kind.endswith("-batch") else {"fl_id": "preview-prefix-ligation"})
    elif kind.startswith("crossover-") or kind == "apply-loop-skips":
        first, second = source.helices
        # Existing honeycomb staple bow-right fixture: reverse nick 7, forward 6.
        request = crud.PlaceCrossoverRequest(
            half_a=dict(helix_id=first.id, index=7, strand="REVERSE"),
            half_b=dict(helix_id=second.id, index=7, strand="FORWARD"),
            nick_bp_a=7, nick_bp_b=6,
        ).model_dump(mode="json")
        append("crossover-place-batch" if kind == "crossover-place-batch" else "crossover-place",
               {"placements": [request]} if kind == "crossover-place-batch" else request)
        if kind.startswith("crossover-move"):
            values = dict(crossover_id=request["crossover_id"], new_index=28)
            append(kind, {"moves": [values]} if kind.endswith("-batch") else values)
        elif kind.startswith("crossover-delete"):
            append(kind, {"crossover_ids": [request["crossover_id"]]}
                   if kind.endswith("-batch") else {"crossover_id": request["crossover_id"]})
        elif kind == "apply-loop-skips":
            prior_op = entry.op_snapshot.model_copy(update={
                "id": "earlier-operation", "params": entry.op_snapshot.params.model_copy(
                    update={"curvature_deg_per_bp": 2}, deep=True),
            }, deep=True)
            prior = entry.model_copy(update={"id": "earlier-bend", "deformation_id": "earlier-operation",
                "op_snapshot": prior_op})
            source = _append(source, prior)
            append(kind, {})
    elif kind == "auto-crossover":
        append(kind, {"history_seed": str(uuid4())})
    else:
        if kind in {"loop-skip-insert", "loop-skip-clear", "loop-skip-clear-all"}:
            append("loop-skip-insert", dict(helix_id=helix.id, bp_index=10, delta=1))
        if kind != "loop-skip-insert":
            values = dict(helix_ids=[helix.id], plane_a_bp=0, plane_b_bp=35)
            if kind == "loop-skip-twist":
                values["target_twist_deg"] = 20
            elif kind == "loop-skip-bend":
                values.update(helix_ids=[item.id for item in source.helices], radius_nm=20)
            append(kind, {} if kind == "loop-skip-clear-all" else values)
    prefix = source
    source = _append(source, entry)
    source.feature_log[-1] = entry.model_copy(update={"op_snapshot": source.deformations[-1]})
    return source, prefix


@pytest.mark.parametrize("kind", PREFIX_CASES)
def test_ordinary_prefix_fixture_is_native_and_preview_preserves_full_authoring(kind):
    source, native_prefix = _prefix_case(kind)
    # The independent full recipe is the fixture control, not a saved snapshot.
    report = assess_part_history(source, execute=part_proof_commands.execute,
                                 dependencies=part_proof_commands.dependencies)
    assert report["status"] == "verified", report
    before = source.model_dump(mode="json")
    service = _service()
    prepared = service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert authoring(prepared.copy_prefix()) == authoring(native_prefix)
    expected = part_proof_commands.execute(*_execution_args(native_prefix, edit_entry(
        source.feature_log[-1], patch("bend"),
    )))
    assert authoring(service.evaluate(prepared, patch("bend")).design) == authoring(expected)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind,change", [
    ("extrude-segment", {"length_bp": 500}),  # aggregate source+new material exceeds 1024 sites
    ("circle-segment", {"cell_lengths": [1_000_000]}),
    ("extrude-continuation", {"length_bp": 1_000_000}),
    ("extrude-continuation", {"cells": [[0, 0]], "offset_nm": 1_000_000}),
    ("extrude-deformed-continuation", {"length_bp": 1_000_000}),
    ("extrude-frame", {"length_bp": 1_000_000}),
    ("sweep", {"points_nm": [[0, 0, 0], [0, 0, 10_000]]}),
    ("loop-skip-twist", {"plane_b_bp": 1_000_000}),
    ("loop-skip-bend", {"plane_b_bp": 1_000_000}),
])
def test_growing_prefix_refuses_prospective_work_before_shared_executor(monkeypatch, kind, change):
    source, _ = _prefix_case(kind)
    row = source.feature_log[-2]
    target = row.children[-1] if row.feature_type == "routing-cluster" else row
    target.params.update(change)
    service, original = _service(), part_proof_commands.execute

    def guarded(operation, design, params):
        assert operation != kind, "Oversized prefix entered its native builder"
        return original(operation, design, params)

    monkeypatch.setattr(service, "execute", guarded)
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("kind", ["strand-end-resize", "domain-shift", "crossover-move", "crossover-move-batch"])
def test_routing_growth_refuses_before_native_allocation(monkeypatch, kind):
    source, _ = _prefix_case(kind)
    params = source.feature_log[-2].children[0].params
    if kind in {"strand-end-resize", "domain-shift"}:
        params["entries"][0]["delta_bp"] = 1_000_000
    elif kind == "crossover-move":
        params["new_index"] = 1_000_000
    else:
        params["moves"][0]["new_index"] = 1_000_000
    service, original = _service(), part_proof_commands.execute

    def guarded(operation, design, values):
        assert operation != kind, "Unbounded routing growth reached the native builder"
        return original(operation, design, values)

    monkeypatch.setattr(service, "execute", guarded)
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("clear", [False, True])
def test_unscoped_cluster_edit_records_native_group_membership(clear):
    from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope

    source = native_source(grouped=True)
    service = _service()
    prepared = service.prepare_from_capture(owned_capture(source), "edited-feature")
    prefix = prepared.copy_prefix()
    original = source.feature_log[-1]
    other = next(cluster.id for cluster in prefix.cluster_transforms
                 if cluster.id not in original.op_snapshot.cluster_ids)
    change = {"cluster_ids": [] if clear else [other]}
    expected_scope = resolve_cluster_scope(prefix, change["cluster_ids"], helices_crossing_planes(
        prefix, original.op_snapshot.plane_a_bp, original.op_snapshot.plane_b_bp))
    expected_entry = original.model_copy(update={"op_snapshot": original.op_snapshot.model_copy(
        update={"cluster_ids": expected_scope["cluster_ids"], "affected_helix_ids": expected_scope["helix_ids"]})})
    expected = part_proof_commands.execute(*_execution_args(prefix, expected_entry))
    result = service.evaluate(prepared, change)
    assert authoring(result.design) == authoring(expected)
    assert result.entry.op_snapshot.cluster_ids == change["cluster_ids"]
    assert result.entry.op_snapshot.affected_helix_ids == expected_scope["helix_ids"]
    assert result.entry.deformation_id == original.deformation_id


def test_explicit_target_membership_remains_protected_when_cluster_controls_expand():
    source = native_source(scoped=True)
    prepared = _service().prepare_from_capture(owned_capture(source), "edited-feature")
    before = prepared._entry.model_dump(mode="json")
    with pytest.raises(CommandContractError):
        _service().evaluate(prepared, {"cluster_ids": [prepared.copy_prefix().cluster_transforms[0].id]})
    assert prepared._entry.model_dump(mode="json") == before
    assert _service().evaluate(prepared, {}).entry.op_snapshot.target_ranges


def test_negative_global_resize_growth_refuses_before_native_work(monkeypatch):
    source, _ = _prefix_case("strand-end-resize")
    source.feature_log[-2].children[0].params["entries"][0].update(end="5p", delta_bp=-1_000_000)
    service, original = _service(), part_proof_commands.execute

    def guarded(operation, design, values):
        assert operation != "strand-end-resize", "Negative global endpoint growth escaped admission"
        return original(operation, design, values)

    monkeypatch.setattr(service, "execute", guarded)
    with pytest.raises(CommandContractError) as caught:
        service.prepare_from_capture(owned_capture(source), "edited-feature")
    assert caught.value.code == "preview_limit"


def test_finite_extreme_retained_sweep_refuses_with_typed_path_limit():
    import json
    from math import isfinite

    _, prefix = _prefix_case("sweep")
    sweep = next(op for op in prefix.deformations if op.type == "sweep")
    # Retained SweepParams accepts finite coordinates beyond the ordinary
    # request range. Their distance can overflow despite valid JSON scalars.
    sweep.params.points_nm = [(-1e308, 0.0, 0.0), (1e308, 0.0, 0.0)]
    assert all(isfinite(value) for point in sweep.params.points_nm for value in point)
    json.dumps(sweep.params.points_nm, allow_nan=False)
    with pytest.raises(CommandContractError) as caught:
        _service()._work(prefix, lambda: None)
    assert caught.value.code == "preview_limit"


def _bounded_bundle(cells, length):
    source = create_empty_part("Bounded prefix control", "HONEYCOMB")
    return _append_command(source, "bundle-create", BundleRequest(
        cells=cells, length_bp=length, name=source.metadata.name, history_seed=uuid4(),
    ).model_dump(mode="json"))


def _append_selected_bend(prefix):
    op = DeformationOp(id="preview-operation", type="bend", plane_a_bp=4, plane_b_bp=18,
        affected_helix_ids=[prefix.helices[0].id],
        params={"kind": "bend", "curvature_deg_per_bp": .25, "direction_deg": 0})
    return _append(prefix, DeformationLogEntry(id="edited-feature", deformation_id=op.id,
        op_snapshot=op, proof_version=1))


def _assert_prefix_matches_native(prefix):
    source = _append_selected_bend(prefix)
    report = assess_part_history(source, execute=part_proof_commands.execute,
                                 dependencies=part_proof_commands.dependencies)
    assert report["status"] == "verified", report
    prepared = _service().prepare_from_capture(owned_capture(source), "edited-feature")
    assert authoring(prepared.copy_prefix()) == authoring(prefix)


def test_native_in_place_continuation_at_helix_limit_remains_previewable():
    from backend.api.crud import BundleContinuationRequest
    from backend.core.constants import BDNA_RISE_PER_BP

    before = _bounded_bundle([[0, col] for col in range(16)], 21)
    prefix = _append_command(before, "extrude-continuation", BundleContinuationRequest(
        cells=[[0, 0]], length_bp=7, offset_nm=21 * BDNA_RISE_PER_BP,
        source_frame_id=before.lattice_frames[0].id, extend_inplace=True,
        history_seed=uuid4(),
    ).model_dump(mode="json"))
    assert {h.id for h in prefix.helices} == {h.id for h in before.helices}
    assert prefix.helices[0].length_bp == 28
    assert sum(2 * h.length_bp for h in prefix.helices) == 686
    _assert_prefix_matches_native(prefix)


def test_complementary_resize_batch_charges_one_actual_helix_extent():
    before = _bounded_bundle([[0, 0]], 492)
    entries = []
    for strand in before.strands:
        domain = strand.domains[0]
        entries.append(dict(strand_id=strand.id, helix_id=domain.helix_id,
            end="3p" if domain.direction.value == "FORWARD" else "5p", delta_bp=20))
    prefix = _append_command(before, "strand-end-resize", {"entries": entries})
    assert len(entries) == 2 and len(prefix.helices) == 1
    assert prefix.helices[0].length_bp == 512
    assert sum(abs(d.end_bp - d.start_bp) + 1 for s in prefix.strands for d in s.domains) == 1024
    _assert_prefix_matches_native(prefix)
