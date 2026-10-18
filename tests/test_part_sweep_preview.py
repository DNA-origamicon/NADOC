"""Owned native Sweep previews; no state, recovery reads, files or workers."""

from copy import deepcopy
from uuid import uuid4

import numpy as np
import pytest

from backend.api import part_proof_commands as commands
from backend.api.crud import BundleRequest
from backend.core import models as m
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.sweep import SweepRequest, sweep_preview
from tests.test_part_deformation_preview import _append, authoring, owned_capture

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



FEATURE = "selected-sweep"
SWEEP_ID = "8e07a099-ceef-401c-b80c-fcc922aaadf0"
TAIL_SEED = "81a0df68-d434-4ba7-a61b-992fae431fb2"


def service():
    from backend.api import part_sweep_preview
    return part_sweep_preview


def snapshot(source, kind, params, identity):
    return _append(source, m.SnapshotLogEntry(id=identity, op_kind=kind, label=kind,
        params={**params, "_proof_version": 1}, evicted=True,
        design_snapshot_gz_b64="poisoned-pre", post_state_gz_b64="poisoned-post"))


def source_recipe(*, attached=False, end="end", posed=False, organized=False, suffix=True):
    source = create_empty_part("Sweep preview", "HONEYCOMB")
    source = snapshot(source, "bundle-create", BundleRequest(cells=[[0, 0], [0, 1]],
        length_bp=12, ligate_adjacent=False, history_seed=uuid4()).model_dump(mode="json"), "bundle")
    if posed:
        owner = source.cluster_transforms[0]
        source = _append(source, m.ClusterOpLogEntry(cluster_id=owner.id,
            translation=[2, 3, 1], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], proof_version=1))
    if organized:
        source = snapshot(source, "group-organize", {"expected_placement_ids": [
            owner.id for owner in source.cluster_transforms]}, "organize")
    direction = -1 if attached and end == "start" else 1
    request = SweepRequest(sweep_id=SWEEP_ID,
        cells=[[0, 0], [0, 1]] if attached else [[4, 4]],
        points_nm=[[0, 0, 0], [0, 0, 4 * direction]], ligate_adjacent=False,
        source_helix_id=source.helices[0].id if attached else None, source_end=end)
    source = snapshot(source, "sweep", request.model_dump(mode="json"), FEATURE)
    if suffix:
        source = snapshot(source, "extrude-segment", {"cells": [[8, 8]], "length_bp": 5,
            "plane": "XY", "history_seed": TAIL_SEED}, "later-extrusion")
    return source


def prepared(**kwargs):
    source = source_recipe(**kwargs)
    return source, service().prepare_from_capture(owned_capture(source), FEATURE)


@pytest.mark.parametrize("attached", [False, True])
def test_native_fixture_reproduces_independently_with_poisoned_evicted_recovery(attached):
    source = source_recipe(attached=attached)
    proof = assess_part_history(source, execute=commands.execute, dependencies=commands.dependencies)
    assert proof["status"] == "verified", proof


@pytest.mark.parametrize("attached,end,posed,organized", [
    (False, "end", False, False), (False, "end", False, True),
    (True, "end", False, False), (True, "start", False, False),
    (True, "end", True, False), (True, "end", True, True),
])
def test_native_feature_stage_parity_and_isolation(attached, end, posed, organized):
    source, owner = prepared(attached=attached, end=end, posed=posed, organized=organized)
    original = source.model_dump(mode="json")
    prefix = owner.copy_prefix()
    change = {"points_nm": [[0, 0, 0], [0, 0, -5 if end == "start" and attached else 5]]}
    selected = next(row for row in source.feature_log if row.id == FEATURE)
    inputs = {**selected.params, **change}
    expected = commands.execute("sweep", prefix.model_copy(deep=True), inputs)
    expected_authoring = authoring(expected)
    expected_preview, _ = sweep_preview(prefix, SweepRequest.model_validate(inputs), include_geometry=True)
    result = service().evaluate(owner, change)
    assert authoring(result.design) == expected_authoring
    assert result.sweep == expected_preview
    assert result.params == result.entry.params
    assert result.entry.id == FEATURE
    assert owner.deformation_id == result.design.deformations[-1].id == "sweep_" + SWEEP_ID
    assert prefix.feature_log == [] and all(op.type != "sweep" for op in prefix.deformations)
    assert result.stage == "feature"
    assert result.source_equivalence_checked is False and result.downstream_evaluated is False
    for helix in expected.helices:
        a = deformed_nucleotide_arrays(helix, expected)
        b = deformed_nucleotide_arrays(result.design.find_helix(helix.id), result.design)
        for field in ("positions", "base_normals", "axis_tangents"):
            np.testing.assert_array_equal(a[field], b[field])
    result.design.strands.clear()
    result.entry.params["cells"].clear()
    result.sweep["points_nm"].clear()
    prefix.helices.clear()
    change["points_nm"][1][2] = 500
    again = service().evaluate(owner, {"points_nm": [[0, 0, 0], [0, 0, -5 if end == "start" and attached else 5]]})
    assert authoring(again.design) == expected_authoring
    assert source.model_dump(mode="json") == original


def test_prepare_ignores_recovery_and_suffix_execution_but_checks_suffix_coverage(monkeypatch):
    from backend.api import part_deformation_preview as shared, state

    source = source_recipe()
    actual = shared.execute

    def prefix_only(kind, design, params):
        assert params.get("history_seed") != TAIL_SEED, "executed suffix"
        assert kind != "sweep", "prepare executed selected command"
        return actual(kind, design, params)

    monkeypatch.setattr(shared, "execute", prefix_only)
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_: pytest.fail("decoded recovery"))
    owner = service().prepare_from_capture(owned_capture(source), FEATURE)
    assert len(owner.copy_prefix().helices) == 2
    source.feature_log[-1].params["_proof_version"] = 99
    with pytest.raises(CommandContractError):
        service().prepare_from_capture(owned_capture(source), FEATURE)


def test_each_evaluation_reuses_prefix_without_source_proof_or_replay(monkeypatch):
    from backend.api import part_deformation_preview as shared
    from backend.core import part_history_contract

    _, owner = prepared()
    actual = shared.execute

    def selected_only(kind, design, params):
        assert kind == "sweep"
        return actual(kind, design, params)

    monkeypatch.setattr(shared, "execute", selected_only)
    monkeypatch.setattr(part_history_contract, "assess_part_history", lambda *_a, **_k: pytest.fail("source proof during slider"))
    service().evaluate(owner, {})
    service().evaluate(owner, {"points_nm": [[0, 0, 0], [0, 0, 5]]})


def test_all_native_authoring_controls_normalize_without_mutating_prior_or_patch():
    previous = {**SweepRequest(sweep_id=SWEEP_ID, cells=[[0, 0]],
        points_nm=[[0, 0, 0], [0, 0, 4]], expected_design_id="part", expected_revision=7).model_dump(mode="json"),
        "_proof_version": 1}
    patch = {"cells": [[1, 2], [2, 2]], "points_nm": [[1, 0, 0], [0, 5, 0]],
        "orientations_deg": [None, [1, 2, 3]], "plane": "XZ", "strand_filter": "staples",
        "ligate_adjacent": False, "source_helix_id": "source", "source_end": "start", "detach_source": True}
    prior_copy, patch_copy = deepcopy(previous), deepcopy(patch)
    result = service().normalize(previous, patch)
    for key, value in patch.items():
        assert result[key] == value
    for key in ("sweep_id", "_proof_version", "expected_design_id", "expected_revision"):
        assert result[key] == previous[key]
    result["cells"].clear()
    assert previous == prior_copy and patch == patch_copy


@pytest.mark.parametrize("field,value", [
    ("sweep_id", "f3464727-1e6b-4678-8a50-1fa870ec8a50"), ("_proof_version", 2),
    ("expected_design_id", "other"), ("expected_revision", 8),
])
def test_identity_and_saved_transport_cannot_be_edited(field, value):
    previous = {**SweepRequest(sweep_id=SWEEP_ID, cells=[[0, 0]], points_nm=[[0, 0, 0], [0, 0, 4]],
        expected_design_id="part", expected_revision=7).model_dump(mode="json"), "_proof_version": 1}
    with pytest.raises(CommandContractError):
        service().normalize(previous, {field: value})


@pytest.mark.parametrize("patch", [
    {"cells": []}, {"cells": [[0, 0], [0, 0]]}, {"cells": [[True, 0]]},
    {"points_nm": [[0, 0, 0], [0, 0, float("nan")]]},
    {"points_nm": [[0, 0, 0], [0, 0, "5"]]},
    {"orientations_deg": [[0, 0, 0]]}, {"orientations_deg": [None, [0, 0, 361]]},
    {"ligate_adjacent": 1}, {"detach_source": "false"},
    {"source_helix_id": ""}, {"source_end": "middle"}, {"plane": "ZX"},
    {"unknown": 1},
])
def test_closed_native_inputs_refuse_malformed_changes(patch):
    previous = next(row.params for row in source_recipe().feature_log if row.id == FEATURE)
    with pytest.raises(CommandContractError):
        service().normalize(previous, patch)


@pytest.mark.parametrize("field,value", [("_generator", {"version": 1}),
    ("_generated_scope", {"version": 1}), ("unreviewed", 1)])
def test_ordinary_preview_does_not_strip_unknown_or_generated_saved_inputs(field, value):
    previous = next(row.params for row in source_recipe().feature_log if row.id == FEATURE)
    with pytest.raises(CommandContractError):
        service().normalize({**previous, field: value}, {})


def test_missing_source_is_a_typed_authored_reference_and_failure_keeps_prefix():
    _, owner = prepared()
    before = owner.copy_prefix().model_dump(mode="json")
    with pytest.raises(CommandContractError) as caught:
        service().evaluate(owner, {"source_helix_id": "missing", "cells": [[0, 0]]})
    assert caught.value.code == "missing_reference"
    assert caught.value.as_issue()["references"] == [{"kind": "helix", "identity": "missing",
        "parameter_path": ["source_helix_id"]}]
    assert owner.copy_prefix().model_dump(mode="json") == before
    assert service().evaluate(owner, {}).entry.id == FEATURE


@pytest.mark.parametrize("patch", [{"cells": [[i, 0] for i in range(17)]},
    {"points_nm": [[0, 0, 0], [0, 0, 100]]}])
def test_prospective_expansion_is_refused_before_native_builder(monkeypatch, patch):
    from backend.core import sweep

    _, owner = prepared()
    monkeypatch.setattr(sweep, "build_sweep", lambda *_: pytest.fail("native allocation before budget"))
    with pytest.raises(CommandContractError) as caught:
        service().evaluate(owner, patch)
    assert caught.value.code == "preview_limit"


def test_native_builder_failure_does_not_contaminate_next_evaluation(monkeypatch):
    from backend.core import sweep

    _, owner = prepared()
    expected = authoring(service().evaluate(owner, {}).design)
    actual = sweep.build_sweep

    def failing(design, _body):
        design.strands.clear()
        raise ValueError("native refusal after local mutation")

    monkeypatch.setattr(sweep, "build_sweep", failing)
    with pytest.raises(CommandContractError, match="native refusal"):
        service().evaluate(owner, {})
    monkeypatch.setattr(sweep, "build_sweep", actual)
    assert authoring(service().evaluate(owner, {}).design) == expected


def test_attached_origin_move_uses_native_detachment_and_orientation_rules():
    _, owner = prepared(attached=True)
    result = service().evaluate(owner, {"points_nm": [[1, 0, 0], [1, 0, 5]]})
    assert result.params["detach_source"] is True and result.sweep["source_detached"] is True
    with pytest.raises(CommandContractError):
        service().evaluate(owner, {"orientations_deg": [[10, 0, 0], None]})


@pytest.mark.parametrize("fault", ["missing_feature", "historical", "duplicate_feature", "wrong_kind"])
def test_selection_header_refuses_before_any_native_prefix_execution(monkeypatch, fault):
    from backend.api import part_deformation_preview as shared

    source = source_recipe()
    identity = FEATURE
    if fault == "missing_feature":
        identity = "missing"
    elif fault == "historical":
        source.feature_log_cursor = 0
    elif fault == "duplicate_feature":
        source.feature_log[-1].id = FEATURE
    else:
        identity = "bundle"
    monkeypatch.setattr(shared, "execute", lambda *_: pytest.fail("executed before header admission"))
    with pytest.raises(CommandContractError):
        service().prepare_from_capture(owned_capture(source), identity)
