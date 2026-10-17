"""Reference-only receipts preserve authored native connector orientation."""

from copy import deepcopy

import pytest

from backend.core.models import (
    Design, Direction, Domain, FlexibleAnchor, FlexibleConnection, Helix, Strand, Vec3,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_flexible_choices import (
    apply_flexible_choices, capture_flexible_choices,
)


def _anchor(strand_id, domain_index, bp_index):
    return FlexibleAnchor(
        strand_id=strand_id, domain_index=domain_index, bp_index=bp_index,
        direction=Direction.FORWARD,
    )


@pytest.fixture
def design():
    helices = [Helix(
        id=identity, length_bp=10,
        axis_start=Vec3(x=index, y=0, z=0), axis_end=Vec3(x=index, y=0, z=3),
    ) for index, identity in enumerate("abcd")]
    strands, connections = [], []
    for index, (first, second) in enumerate((("a", "b"), ("c", "d"))):
        strand_id = f"strand-{index}"
        strands.append(Strand(id=strand_id, domains=[
            Domain(helix_id=identity, start_bp=0, end_bp=9, direction=Direction.FORWARD)
            for identity in (first, second)
        ]))
        connections.append(FlexibleConnection(
            id=f"native-{index}", cluster_a_id=f"cluster-{first}",
            cluster_b_id=f"cluster-{second}",
            anchor_a=_anchor(strand_id, 0, 6), anchor_b=_anchor(strand_id, 1, 3),
            n_ss_bases=6, contour_length_nm=3.6,
            segment_bead_keys=[
                *[_anchor(strand_id, 0, bp) for bp in (7, 8, 9)],
                *[_anchor(strand_id, 1, bp) for bp in (0, 1, 2)],
            ],
        ))
    return Design(helices=helices, strands=strands, flexible_connections=connections)


def _reverse(connection):
    return connection.model_copy(update={
        "cluster_a_id": connection.cluster_b_id,
        "cluster_b_id": connection.cluster_a_id,
        "anchor_a": connection.anchor_b, "anchor_b": connection.anchor_a,
        "segment_bead_keys": list(reversed(connection.segment_bead_keys)),
    })


def test_capture_contains_only_nucleotide_references_and_component_identity(design):
    choices = capture_flexible_choices(design)
    assert choices == [
        {
            "anchor_a": {"helix_id": first, "bp_index": 6, "direction": "FORWARD"},
            "anchor_b": {"helix_id": second, "bp_index": 3, "direction": "FORWARD"},
            "component_helix_ids": [first, second],
        }
        for first, second in (("a", "b"), ("c", "d"))
    ]


def test_alternate_native_orientation_and_list_order_restore_exact_preview(design):
    choices = capture_flexible_choices(design)
    alternate = design.copy_with(flexible_connections=[
        _reverse(connection) for connection in reversed(design.flexible_connections)
    ])
    before = alternate.model_dump_json()
    result = apply_flexible_choices(alternate, choices)
    assert result.model_dump() == design.model_dump()
    assert alternate.model_dump_json() == before


def test_native_new_hash_and_length_remain_native_when_anchors_still_resolve(design):
    choices = capture_flexible_choices(design)
    # Replay may change connector length/hash; the receipt must never restore
    # saved geometry, count, or connection identity from the earlier preview.
    changed = design.flexible_connections[0].model_copy(update={
        "id": "new-native-hash", "n_ss_bases": 5, "contour_length_nm": 3.0,
        "segment_bead_keys": design.flexible_connections[0].segment_bead_keys[:-1],
    })
    native = design.copy_with(flexible_connections=[
        _reverse(design.flexible_connections[1]), _reverse(changed),
    ])
    result = apply_flexible_choices(native, choices)
    assert result.flexible_connections == [changed, design.flexible_connections[1]]
    assert result.model_dump(exclude={"flexible_connections"}) == native.model_dump(
        exclude={"flexible_connections"}
    )


@pytest.mark.parametrize("change", [
    lambda choices: None,
    lambda choices: {"connections": choices},
    lambda choices: [dict(choices[0], positions=[[0, 0, 0]])],
    lambda choices: [dict(choices[0], anchor_a=dict(choices[0]["anchor_a"], bp_index=True))],
    lambda choices: [dict(choices[0], anchor_a=dict(choices[0]["anchor_a"], direction="bad"))],
    lambda choices: [dict(choices[0], component_helix_ids=["a", "a"])],
    lambda choices: [dict(choices[0], component_helix_ids=[""])],
])
def test_malformed_choices_fail_with_structured_issue_without_mutation(design, change):
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        apply_flexible_choices(design, change(capture_flexible_choices(design)))
    issue = caught.value.as_issue()
    assert issue["code"] == "invalid_selection"
    assert issue["references"]
    assert all(ref["parameter_path"][0] == "flexible_choices" for ref in issue["references"])
    assert design.model_dump_json() == before


@pytest.mark.parametrize("change,code", [
    (lambda choices: choices[:-1], "missing_reference"),
    (lambda choices: choices + [choices[0]], "invalid_selection"),
    (lambda choices: [dict(choices[0], component_helix_ids=["missing"])], "missing_reference"),
    (lambda choices: [dict(choices[0], anchor_a=dict(choices[0]["anchor_a"], helix_id="missing"))],
     "missing_reference"),
])
def test_missing_repeated_or_incomplete_choices_are_not_silently_repaired(design, change, code):
    with pytest.raises(ReferenceResolutionError) as caught:
        apply_flexible_choices(design, change(capture_flexible_choices(design)))
    assert caught.value.as_issue()["code"] == code


def test_component_references_disambiguate_shared_rigid_anchor_pair(design):
    first, second = design.flexible_connections
    same_anchors = second.model_copy(update={
        "anchor_a": first.anchor_a, "anchor_b": first.anchor_b,
    })
    candidate = design.copy_with(flexible_connections=[first, same_anchors])
    choices = capture_flexible_choices(candidate)
    assert apply_flexible_choices(candidate, choices).flexible_connections == [first, same_anchors]
    choices[0].pop("component_helix_ids")
    with pytest.raises(ReferenceResolutionError, match="ambiguous"):
        apply_flexible_choices(candidate, choices)


def test_ambiguous_native_components_cannot_mint_receipt(design):
    first = design.flexible_connections[0]
    candidate = design.copy_with(flexible_connections=[
        first, first.model_copy(update={"id": "duplicate"}),
    ])
    with pytest.raises(ReferenceResolutionError, match="ambiguous"):
        capture_flexible_choices(candidate)


def test_choices_do_not_need_component_ids_when_endpoints_are_unique(design):
    choices = deepcopy(capture_flexible_choices(design))
    for choice in choices:
        choice.pop("component_helix_ids")
    assert apply_flexible_choices(design, choices) == design


def test_empty_native_connections_require_explicit_empty_choices():
    design = Design()
    assert capture_flexible_choices(design) == []
    assert apply_flexible_choices(design, []) == design
    with pytest.raises(ReferenceResolutionError):
        apply_flexible_choices(design, None)


def test_unresolved_native_anchor_does_not_mint_receipt(design):
    first = design.flexible_connections[0]
    candidate = design.copy_with(flexible_connections=[first.model_copy(update={
        "anchor_a": first.anchor_a.model_copy(update={"strand_id": "missing"}),
    })])
    with pytest.raises(ReferenceResolutionError) as caught:
        capture_flexible_choices(candidate)
    assert caught.value.as_issue()["references"] == [{
        "kind": "strand", "identity": "missing",
        "parameter_path": ["flexible_choices", 0, "anchor_a"],
    }]
