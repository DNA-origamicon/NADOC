"""Resize/shift grouping through real native inputs and private history.

No active document is installed or public rollout gate enabled. The unchanged
native command pipeline supplies the model/geometry oracle; group expectations
come from the explicit core/tail entities in the fixture. Recovery stays in
memory and is poisoned separately to prove it is not regeneration input.
"""

import pytest

from backend.api import crud, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change
from backend.core import models as m
from backend.core.deformation import deformed_helix_axes
from backend.core.design_diff import encode_child_diff
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture


SEED = "ad137c24-65af-45db-9f59-703bf7e69df7"


def snapshot(design, kind, params):
    params = {**params, "_proof_version": 1}
    after = execute(kind, design, params)
    pre, pre_size = state.encode_design_snapshot(design)
    post, post_size = state.encode_design_snapshot(after)
    entry = m.SnapshotLogEntry(
        id=f"snapshot-{len(design.feature_log)}",
        op_kind=kind,
        label=kind,
        params=params,
        design_snapshot_gz_b64=pre,
        snapshot_size_bytes=pre_size,
        post_state_gz_b64=post,
        post_state_size_bytes=post_size,
    )
    return after.copy_with(feature_log=[*design.feature_log, entry])


def minor(design, kind, params):
    params = {**params, "_proof_version": 1}
    after = execute(kind, design, params)
    added, removed, modified, size = encode_child_diff(design, after)
    log = list(design.feature_log)
    if log and log[-1].feature_type == "routing-cluster":
        row = log.pop()
    else:
        pre, pre_size = state.encode_design_snapshot(design)
        row = m.RoutingClusterLogEntry(
            id=f"routing-{len(log)}",
            pre_state_gz_b64=pre,
            pre_state_size_bytes=pre_size,
        )
    child = m.MinorMutationLogEntry(
        id=f"{row.id}-child-{len(row.children)}",
        op_subtype=kind,
        label=kind,
        params=params,
        diff_added_b64=added,
        diff_removed_b64=removed,
        diff_modified_b64=modified,
        diff_size_bytes=size,
    )
    post, post_size = state.encode_design_snapshot(after)
    row = row.model_copy(
        update={
            "children": [*row.children, child],
            "post_state_gz_b64": post,
            "post_state_size_bytes": post_size,
        }
    )
    return after.copy_with(feature_log=[*log, row])


def resize(strand_id, helix_id, delta, end="5p"):
    return {
        "entries": [
            {
                "strand_id": strand_id,
                "helix_id": helix_id,
                "end": end,
                "delta_bp": delta,
            }
        ]
    }


def shift(strand_id, delta, index=0):
    return {
        "entries": [{"strand_id": strand_id, "domain_index": index, "delta_bp": delta}]
    }


def group(design, identity):
    return next(
        item for item in design.group_organization.groups if item.id == identity
    )


def refs(design, identity):
    return [
        (item.strand_id, item.domain_index)
        for item in group(design, identity).domain_ids
    ]


def primitive_prefix():
    current = create_empty_part("Resize lineage", "HONEYCOMB")
    current = snapshot(
        current,
        "bundle-create",
        crud.BundleRequest(
            cells=[[0, 0]],
            length_bp=21,
            name="Resize lineage",
            history_seed=SEED,
        ).model_dump(mode="json"),
    )
    strand = next(s for s in current.strands if s.strand_type == m.StrandType.STAPLE)
    helix_id = strand.domains[0].helix_id
    current = minor(current, "strand-end-resize", resize(strand.id, helix_id, 4))
    # The real native operation creates reverse tail24..21 + core20..0.
    return current, strand.id, helix_id


def prefix():
    current, strand_id, helix_id = primitive_prefix()
    current = snapshot(
        current,
        "group-organize",
        {"expected_placement_ids": [item.id for item in current.cluster_transforms]},
    )
    for identity, ordinal in (("core", 1), ("core-overlap", 1), ("tail", 0)):
        current = snapshot(
            current,
            "group-create",
            {
                "group": {
                    "id": identity,
                    "name": identity,
                    "helix_ids": [helix_id],
                    "domain_ids": [{"strand_id": strand_id, "domain_index": ordinal}],
                    "color": "#aabbcc",
                    "opacity": 0.6,
                }
            },
        )
    return current, strand_id, helix_id


def pipeline(*, padding=0):
    current, strand_id, helix_id = prefix()
    states = [current]
    current = minor(current, "strand-end-resize", resize(strand_id, helix_id, -6))
    states.append(current)
    current = minor(current, "domain-shift", shift(strand_id, 4))
    states.append(current)
    for index in range(padding):
        # Real edits, not duplicate/no-op padding: change the low terminal of
        # the retained core between 4 and 5 while leaving its tagged 5' tail.
        current = minor(
            current,
            "strand-end-resize",
            resize(strand_id, helix_id, 1 if index % 2 == 0 else -1, end="3p"),
        )
        states.append(current)
    return current, states, strand_id, helix_id


def topology_equal(actual, expected):
    for field in (
        "helices",
        "strands",
        "overhangs",
        "crossovers",
        "forced_ligations",
        "cluster_transforms",
        "lattice_frames",
        "deformations",
        "group_organization",
    ):
        assert getattr(actual, field) == getattr(expected, field), field
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)


def native_parity(before, kind, params):
    original = before.model_dump(mode="json")
    legacy = before.copy_with(group_organization=None)
    expected = execute(kind, legacy, {**params, "_proof_version": 1})
    actual = execute(kind, before, {**params, "_proof_version": 1})
    assert actual.model_dump(
        mode="json", exclude={"group_organization"}
    ) == expected.model_dump(mode="json", exclude={"group_organization"})
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)
    assert before.model_dump(mode="json") == original
    return actual


def poisoned(design):
    private = m.Design.model_validate_json(design.model_dump_json())
    for entry in private.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = "poisoned snapshot"
            entry.post_state_gz_b64 = "poisoned post"
        elif entry.feature_type == "routing-cluster":
            entry.pre_state_gz_b64 = "poisoned routing pre"
            entry.post_state_gz_b64 = "poisoned routing post"
            for child in entry.children:
                child.diff_added_b64 = child.diff_removed_b64 = (
                    child.diff_modified_b64
                ) = "poisoned diff"
    return private


def verified(design):
    report = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    assert report["native_editable"] is True


def deform(design, kind, *, explicit=False):
    selected = refs(design, "core")
    params = {
        "_proof_version": 1,
        "id": "downstream-deformation",
        "type": kind,
        "plane_a_bp": 4,
        "plane_b_bp": 18,
        "cluster_ids": [],
        "affected_helix_ids": [],
        "target_ranges": None,
        "targets": (
            [
                {"kind": "domain", "strand_id": sid, "domain_index": ordinal}
                for sid, ordinal in selected
            ]
            if explicit
            else [{"kind": "part_group", "id": "core"}]
        ),
        "params": (
            {"kind": "bend", "curvature_deg_per_bp": 0.5, "direction_deg": 25}
            if kind == "bend"
            else {"kind": "twist", "total_degrees": 30}
        ),
    }
    result = execute("deformation", design, params)
    op = result.deformations[-1]
    return result.copy_with(
        feature_log=[
            *design.feature_log,
            m.DeformationLogEntry(
                id="deformation-feature",
                deformation_id=op.id,
                op_snapshot=op,
                proof_version=1,
            ),
        ]
    )


def test_native_control_really_merges_trimmed_tail_then_splits_shifted_core():
    current, sid, hid = primitive_prefix()
    domains = current.find_strand(sid).domains
    assert [(d.start_bp, d.end_bp) for d in domains] == [(24, 21), (20, 0)]
    assert domains[0].overhang_id and domains[1].overhang_id is None
    trimmed = execute(
        "strand-end-resize", current, {"_proof_version": 1, **resize(sid, hid, -6)}
    )
    assert [(d.start_bp, d.end_bp) for d in trimmed.find_strand(sid).domains] == [
        (18, 0)
    ]
    shifted = execute("domain-shift", trimmed, {"_proof_version": 1, **shift(sid, 4)})
    assert [(d.start_bp, d.end_bp) for d in shifted.find_strand(sid).domains] == [
        (22, 21),
        (20, 4),
    ]
    assert m.Design.model_validate_json(shifted.model_dump_json()) == shifted


def test_registered_resize_drops_only_removed_tail_group_and_preserves_overlapping_core():
    source, sid, hid = prefix()
    result = native_parity(source, "strand-end-resize", resize(sid, hid, -6))
    assert refs(result, "core") == refs(result, "core-overlap") == [(sid, 0)]
    assert refs(result, "tail") == [] and group(result, "tail").helix_ids == []
    assert (
        group(result, "tail").name == "tail"
        and group(result, "tail").color == "#aabbcc"
    )
    assert result.cluster_transforms == source.cluster_transforms
    assert m.Design.model_validate_json(result.model_dump_json()) == result


def test_registered_shift_follows_both_new_descendants_without_resurrecting_removed_group():
    source, sid, hid = prefix()
    trimmed = execute(
        "strand-end-resize", source, {"_proof_version": 1, **resize(sid, hid, -6)}
    )
    result = native_parity(trimmed, "domain-shift", shift(sid, 4))
    assert refs(result, "core") == refs(result, "core-overlap") == [(sid, 0), (sid, 1)]
    assert refs(result, "tail") == [] and group(result, "tail").helix_ids == []
    assert [(d.start_bp, d.end_bp) for d in result.find_strand(sid).domains] == [
        (22, 21),
        (20, 4),
    ]
    assert result.cluster_transforms == source.cluster_transforms


def test_failed_shift_of_removed_ordinal_keeps_source_and_does_not_poison_next_trace():
    source, sid, hid = prefix()
    trimmed = execute(
        "strand-end-resize", source, {"_proof_version": 1, **resize(sid, hid, -6)}
    )
    original = trimmed.model_dump(mode="json")
    with pytest.raises(CommandContractError) as error:
        execute(
            "domain-shift", trimmed, {"_proof_version": 1, **shift(sid, 4, index=1)}
        )
    assert error.value.code == "missing_reference"
    assert error.value.references[0]["parameter_path"] == ["entries", 0, "domain_index"]
    assert trimmed.model_dump(mode="json") == original
    result = execute("domain-shift", trimmed, {"_proof_version": 1, **shift(sid, 4)})
    assert refs(result, "core") == [(sid, 0), (sid, 1)]


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_poisoned_input_only_replay_and_upstream_edit_reresolve_named_deformation(kind):
    current, _, sid, _ = pipeline()
    explicit = deform(current, kind, explicit=True)
    named = deform(current, kind)
    assert (
        named.deformations[-1].target_ranges == explicit.deformations[-1].target_ranges
    )
    assert _geometry_for_design(named) == _geometry_for_design(explicit)
    assert deformed_helix_axes(named) == deformed_helix_axes(explicit)
    private = poisoned(named)
    original = private.model_dump(mode="json")
    verified(private)
    edited, _ = prepare_change(
        private,
        capture(private, preserve_entry_types=True),
        0,
        lambda: None,
        params={"length_bp": 24},
    )
    assert [e.id for e in edited.feature_log] == [e.id for e in named.feature_log]
    assert refs(edited, "core") == refs(edited, "core-overlap") == [(sid, 0), (sid, 1)]
    assert refs(edited, "tail") == [] and group(edited, "tail").helix_ids == []
    op = edited.deformations[-1]
    assert op.targets == [{"kind": "part_group", "id": "core"}]
    assert op.target_ranges != named.deformations[-1].target_ranges
    assert [(r.strand_id, r.domain_index) for r in op.target_ranges] == refs(
        edited, "core"
    )
    assert {(r.start_bp, r.end_bp) for r in op.target_ranges} == {(24, 25), (4, 23)}
    loaded = m.Design.model_validate_json(edited.model_dump_json())
    topology_equal(loaded, edited)
    verified(poisoned(loaded))
    assert private.model_dump(mode="json") == original


@pytest.mark.parametrize(
    "optimized", [False, True], ids=["ordinary", "composed-child-diffs"]
)
def test_fine_routing_seek_and_private_undo_restore_each_native_membership_boundary(
    optimized,
):
    # Eight actual routing children cross evaluate_child_prefix's composition
    # threshold, independent of the top-level snapshot-scan optimization.
    current, states, _, _ = pipeline(padding=6 if optimized else 0)
    routing_index = len(current.feature_log) - 1
    children = current.feature_log[-1].children
    assert len(children) == (8 if optimized else 2)
    original = current.model_dump(mode="json")
    active = m.Design.model_validate_json(current.model_dump_json())
    for sub_index in [-2, 0, len(children) - 1, 1, 0, -2, -1]:
        active = crud._seek_feature_log(
            active, routing_index, sub_index, optimized=optimized
        )
        expected = states[
            0 if sub_index == -2 else -1 if sub_index == -1 else sub_index + 1
        ]
        topology_equal(active, expected)
        active = m.Design.model_validate_json(active.model_dump_json())
    # Exercise the actual undo restoration helper on independently decoded
    # pre-state. No public active-mode installation/undo rollout is implied.
    pre = state.decode_design_snapshot(current.feature_log[-1].pre_state_gz_b64)
    restored = state._restore_edit_snapshot(pre, current)
    topology_equal(restored, states[0])
    assert current.model_dump(mode="json") == original
    verified(poisoned(current))


def test_deleting_last_routing_child_regenerates_earlier_membership_without_saved_geometry():
    current, states, sid, _ = pipeline()
    private = poisoned(current)
    original = private.model_dump(mode="json")
    edited, _ = prepare_change(
        private,
        capture(private, preserve_entry_types=True),
        len(private.feature_log) - 1,
        lambda: None,
        sub_index=1,
    )
    assert len(edited.feature_log[-1].children) == 1
    assert refs(edited, "core") == refs(edited, "core-overlap") == [(sid, 0)]
    assert refs(edited, "tail") == []
    topology_equal(edited, states[1])
    verified(poisoned(edited))
    assert private.model_dump(mode="json") == original
