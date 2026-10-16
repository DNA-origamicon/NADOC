"""Native crossover construction/motion retains organizational descendants.

The unchanged native builders provide the geometry oracle. Tests create only
small in-memory DNA; no route installation, numerical solver or stored geometry
is needed. Growth metadata loss is characterized separately, not corrected here.
"""

from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.api import crud
from backend.api.part_crossover_moves import batch_move, move
from backend.api.part_proof_commands import dependencies, execute
from backend.core import lattice, models as m
from backend.core.cluster_reconcile import reconcile_cluster_membership
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part


PLACEMENTS = ("crossover-place", "crossover-place-batch")
MOVES = ("crossover-move", "crossover-move-batch")


def bundle(lattice_type=m.LatticeType.HONEYCOMB, cells=((0, 0), (0, 1)), length=96):
    design = lattice.make_bundle_design(list(cells), length, lattice_type=lattice_type)
    return design.copy_with(
        helices=[
            helix.model_copy(update={"grid_pos": cell})
            for helix, cell in zip(design.helices, cells)
        ]
    )


def placement(design, index=None, *, pair=(0, 1), identity=1):
    # These are existing lattice-table positions and native nick conventions.
    # HC 7 and SQ 32 are bow-right; HC 6/13 are bow-left.
    index = (
        (7 if design.lattice_type == m.LatticeType.HONEYCOMB else 32)
        if index is None
        else index
    )
    a, b = (design.helices[offset] for offset in pair)
    da, db = (
        next(
            strand.domains[0].direction
            for strand in design.strands
            if strand.strand_type == m.StrandType.STAPLE
            and strand.domains[0].helix_id == helix.id
        )
        for helix in (a, b)
    )
    bow_right = (
        index % 21 in {0, 7, 14}
        if design.lattice_type == m.LatticeType.HONEYCOMB
        else index % 32 in {0, 8, 16, 24}
    )
    lower = index - 1 if bow_right else index
    return {
        "crossover_id": str(UUID(int=identity)),
        "half_a": {"helix_id": a.id, "index": index, "strand": da.value},
        "half_b": {"helix_id": b.id, "index": index, "strand": db.value},
        "nick_bp_a": lower + (da == m.Direction.REVERSE),
        "nick_bp_b": lower + (db == m.Direction.REVERSE),
        "process_id": "manual",
    }


def finish(before, candidate):
    return lattice.retry_pending_ligations(
        before, reconcile_cluster_membership(before, candidate)
    )


def native(kind, design, inputs):
    values = {key: value for key, value in inputs.items() if key != "_proof_version"}
    if kind == "crossover-place":
        result = crud._build_place_crossover(
            design, crud.PlaceCrossoverRequest(**values)
        )[0]
    elif kind == "crossover-place-batch":
        result = crud._build_place_crossover_batch(
            design, crud.PlaceCrossoverBatchRequest(**values)
        )[0]
    elif kind == "crossover-move":
        result = move(design, crud.MoveCrossoverRequest(**values))[0]
    else:
        result = batch_move(design, crud.BatchMoveCrossoversRequest(**values))[0]
    return finish(design, result)


def organized(design, selections):
    current = execute(
        "group-organize",
        design,
        {
            "_proof_version": 1,
            "expected_placement_ids": [group.id for group in design.cluster_transforms],
        },
    )
    for index, members in enumerate(selections):
        current = execute(
            "group-create",
            current,
            {
                "_proof_version": 1,
                "group": {
                    "id": f"selected-{index}",
                    "name": f"Selection {index}",
                    "helix_ids": [helix.id for helix in current.helices],
                    "domain_ids": [
                        {"strand_id": sid, "domain_index": ordinal}
                        for sid, ordinal in members
                    ],
                    "color": "#123456",
                    "opacity": 0.5,
                    "is_default": False,
                    "auto_created": False,
                },
            },
        )
    return current


def refs(design, index=0):
    group = next(
        group
        for group in design.group_organization.groups
        if group.id == f"selected-{index}"
    )
    return [(ref.strand_id, ref.domain_index) for ref in group.domain_ids]


def parity(actual, expected):
    assert actual.model_dump(exclude={"group_organization"}) == expected.model_dump(
        exclude={"group_organization"}
    )
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)


def moved_source(lattice_type=m.LatticeType.HONEYCOMB):
    design = bundle(lattice_type)
    request = placement(design)
    placed = native("crossover-place", design, request)
    joined = next(strand for strand in placed.strands if len(strand.domains) == 2)
    return placed, request, joined


@pytest.mark.parametrize("lattice_type", list(m.LatticeType))
def test_native_controls_really_place_and_move_without_organization(lattice_type):
    design, placed, joined = moved_source(lattice_type)
    period = 21 if lattice_type == m.LatticeType.HONEYCOMB else 32
    target = placed["half_a"]["index"] + period
    after = native(
        "crossover-move",
        design,
        {"crossover_id": placed["crossover_id"], "new_index": target},
    )
    current = after.find_strand(joined.id)
    assert len(current.domains) == 2
    assert current.domains[0].end_bp == current.domains[1].start_bp == target
    assert after.group_organization is None
    assert m.Design.model_validate_json(after.model_dump_json()) == after


@pytest.mark.parametrize("kind", PLACEMENTS)
@pytest.mark.parametrize("lattice_type", list(m.LatticeType))
def test_placement_follows_both_fragments_without_adopting_other_helix(
    kind, lattice_type
):
    source = bundle(lattice_type)
    request = placement(source)
    selected = next(
        strand
        for strand in source.strands
        if strand.domains[0].helix_id == request["half_a"]["helix_id"]
        and strand.domains[0].direction.value == request["half_a"]["strand"]
    )
    source = organized(source, [[(selected.id, 0)], [(selected.id, 0)]])
    before = source.model_dump(mode="json")
    inputs = {"placements": [request]} if kind.endswith("-batch") else request
    expected = native(kind, source, inputs)
    actual = execute(kind, source, {**inputs, "_proof_version": 1})
    old = selected.domains[0]
    descendants = [
        (strand.id, index)
        for strand in expected.strands
        for index, domain in enumerate(strand.domains)
        if domain.helix_id == old.helix_id and domain.direction == old.direction
    ]
    assert len(descendants) == 2
    assert refs(actual) == refs(actual, 1) == descendants
    parity(actual, expected)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", PLACEMENTS)
def test_inline_cleanup_preserves_selected_tail_identity_after_tag_removal(kind):
    from tests.test_crossover_edge_cases import _design_overhang_boundary

    source = organized(_design_overhang_boundary(), [[("sA", 2)], [("sB", 0)]])
    request = {
        "crossover_id": str(UUID(int=3)),
        "half_a": {"helix_id": "hB", "index": 0, "strand": "FORWARD"},
        "half_b": {"helix_id": "hA", "index": 0, "strand": "REVERSE"},
        "nick_bp_a": -1,
        "nick_bp_b": 0,
    }
    inputs = {"placements": [request]} if kind.endswith("-batch") else request
    expected = native(kind, source, inputs)
    actual = execute(kind, source, {**inputs, "_proof_version": 1})
    for index in (0, 1):
        selected = refs(actual, index)
        assert len(selected) == 1
        sid, ordinal = selected[0]
        domain = actual.find_strand(sid).domains[ordinal]
        assert domain.start_bp == domain.end_bp == -1 and domain.overhang_id is None
    parity(actual, expected)


@pytest.mark.parametrize("kind", MOVES)
@pytest.mark.parametrize("lattice_type", list(m.LatticeType))
@pytest.mark.parametrize("swap_halves", [False, True])
def test_motion_retains_each_native_domain_entity_and_exact_native_output(
    kind, lattice_type, swap_halves
):
    source, placed, strand = moved_source(lattice_type)
    if swap_halves:
        source = source.copy_with(
            crossovers=[
                item.model_copy(update={"half_a": item.half_b, "half_b": item.half_a})
                for item in source.crossovers
            ]
        )
    unrelated = next(item for item in source.strands if item.id != strand.id)
    source = organized(
        source,
        [[(strand.id, 0)], [(strand.id, 1)], [(strand.id, 0)], [(unrelated.id, 0)]],
    )
    before = source.model_dump(mode="json")
    period = 21 if lattice_type == m.LatticeType.HONEYCOMB else 32
    request = {
        "crossover_id": placed["crossover_id"],
        "new_index": placed["half_a"]["index"] + period,
    }
    inputs = {"moves": [request]} if kind.endswith("-batch") else request
    expected = native(kind, source, inputs)
    actual = execute(kind, source, {**inputs, "_proof_version": 1})
    assert refs(actual) == refs(actual, 2) == [(strand.id, 0)]
    assert refs(actual, 1) == [(strand.id, 1)]
    assert refs(actual, 3) == [(unrelated.id, 0)]
    assert actual.find_strand(strand.id).domains != strand.domains
    parity(actual, expected)
    assert source.model_dump(mode="json") == before


def middle_domain_source():
    source = bundle(cells=((0, 0), (0, 1), (1, 1)))
    first = placement(source, 7, identity=11)
    second = placement(source, 13, pair=(1, 2), identity=12)
    placed = native("crossover-place-batch", source, {"placements": [first, second]})
    joined = next(strand for strand in placed.strands if len(strand.domains) == 3)
    # Keep this actual native routed strand. Removing unrelated same-direction
    # precursors makes room for the whole-domain translation under test.
    placed = placed.copy_with(strands=[joined])
    return (
        placed,
        joined,
        {
            "moves": [
                {"crossover_id": first["crossover_id"], "new_index": 28},
                {"crossover_id": second["crossover_id"], "new_index": 34},
            ]
        },
    )


def test_native_middle_domain_control_translates_both_ends_to_disjoint_interval():
    source, strand, inputs = middle_domain_source()
    actual = native("crossover-move-batch", source, inputs)
    assert (strand.domains[1].start_bp, strand.domains[1].end_bp) == (7, 13)
    after = actual.find_strand(strand.id).domains[1]
    assert (after.start_bp, after.end_bp) == (28, 34)
    assert m.Design.model_validate_json(actual.model_dump_json()) == actual


def test_batch_atomic_original_to_final_transport_does_not_lose_disjoint_middle_domain():
    source, strand, inputs = middle_domain_source()
    source = organized(
        source, [[(strand.id, 1)], [(strand.id, 1)], [(strand.id, 0)], [(strand.id, 2)]]
    )
    expected = native("crossover-move-batch", source, inputs)
    actual = execute("crossover-move-batch", source, {**inputs, "_proof_version": 1})
    assert refs(actual) == refs(actual, 1) == [(strand.id, 1)]
    assert refs(actual, 2) == [(strand.id, 0)] and refs(actual, 3) == [(strand.id, 2)]
    assert (
        actual.find_strand(strand.id).domains[1].start_bp,
        actual.find_strand(strand.id).domains[1].end_bp,
    ) == (28, 34)
    parity(actual, expected)


@pytest.mark.parametrize("kind", MOVES)
def test_noop_move_keeps_organization_and_source_values(kind):
    source, placed, strand = moved_source()
    source = organized(source, [[(strand.id, 1)]])
    inputs = {"crossover_id": placed["crossover_id"], "new_index": 7}
    inputs = {"moves": [inputs]} if kind.endswith("-batch") else inputs
    original = source.model_dump(mode="json")
    actual = execute(kind, source, {**inputs, "_proof_version": 1})
    assert actual.model_dump(mode="json") == original
    assert source.model_dump(mode="json") == original


@pytest.mark.parametrize("failure", ["missing", "invalid-site", "inverted", "overlap"])
def test_invalid_native_motion_refuses_without_mutating_input(failure):
    source, placed, strand = moved_source()
    source = organized(source, [[(strand.id, 0)]])
    request = {"crossover_id": placed["crossover_id"], "new_index": 28}
    if failure == "missing":
        request["crossover_id"] = "missing"
    elif failure == "invalid-site":
        request["new_index"] = 10
    elif failure == "inverted":
        request["new_index"] = 112  # valid HC site, past the unchanged 5'/3' ends
    else:
        request["new_index"] = 6  # valid HC site, overlaps the untouched 0..6 pieces
    original = source.model_dump(mode="json")
    with pytest.raises((CommandContractError, HTTPException, ValueError)) as error:
        execute(
            "crossover-move-batch", source, {"_proof_version": 1, "moves": [request]}
        )
    if isinstance(error.value, CommandContractError):
        assert error.value.code not in {
            "unsupported_group_lineage_command",
            "unsupported_group_organization_command",
        }
    assert source.model_dump(mode="json") == original


def growth_source():
    source = bundle(length=42)
    request = placement(source, 6, identity=21)
    placed = native("crossover-place", source, request)
    strand = next(item for item in placed.strands if len(item.domains) == 2)
    return (
        placed.copy_with(strands=[strand]),
        strand,
        {"crossover_id": request["crossover_id"], "new_index": 48},
    )


def test_legacy_growth_control_documents_dropped_helix_metadata_without_blessing_it():
    source, _, inputs = growth_source()
    assert all(helix.direction is not None for helix in source.helices)
    after = native("crossover-move", source, inputs)
    assert all(helix.length_bp == 49 for helix in after.helices)
    # Existing native constructor behavior, deliberately not a new expected
    # organization capability. The active contract below must refuse it.
    assert all(helix.direction is None for helix in after.helices)


@pytest.mark.parametrize("kind", MOVES)
def test_active_growth_that_would_drop_native_metadata_refuses_before_builder(
    kind, monkeypatch
):
    from backend.api import part_crossover_moves

    source, strand, inputs = growth_source()
    source = organized(source, [[(strand.id, 0)]])
    original = source.model_dump(mode="json")

    def unexpected(*args, **kwargs):
        raise AssertionError("Lossy native growth must be refused before construction")

    monkeypatch.setattr(part_crossover_moves, "build", unexpected)
    with pytest.raises(CommandContractError) as error:
        execute(
            kind,
            source,
            {
                "_proof_version": 1,
                **({"moves": [inputs]} if kind.endswith("-batch") else inputs),
            },
        )
    assert error.value.code not in {
        "unsupported_group_lineage_command",
        "unsupported_group_organization_command",
    }
    assert source.model_dump(mode="json") == original


def test_batch_partial_growth_refuses_metadata_loss_even_when_final_domain_fits(
    monkeypatch,
):
    from backend.api import part_crossover_moves

    source, strand, inputs = middle_domain_source()
    middle_id = strand.domains[1].helix_id
    source = source.copy_with(
        helices=[
            helix.model_copy(
                update={
                    "bp_start": 28,
                    "length_bp": 7,
                    "label": "Retain native owner metadata",
                }
            )
            if helix.id == middle_id
            else helix
            for helix in source.helices
        ]
    )
    legacy = native("crossover-move-batch", source, inputs)
    moved_domain = legacy.find_strand(strand.id).domains[1]
    assert (moved_domain.start_bp, moved_domain.end_bp) == (28, 34)
    affected = next(helix for helix in legacy.helices if helix.id == middle_id)
    # Native batch growth uses each original opposite endpoint, not solely the
    # final 28..34 interval. This documents the unchanged constructor defect.
    assert affected.bp_start < 28 and affected.label is None

    source = organized(source, [[(strand.id, 1)]])
    original = source.model_dump(mode="json")

    def unexpected(*args, **kwargs):
        raise AssertionError(
            "Partial native growth must be refused before construction"
        )

    monkeypatch.setattr(part_crossover_moves, "build", unexpected)
    with pytest.raises(CommandContractError) as error:
        execute("crossover-move-batch", source, {"_proof_version": 1, **inputs})
    assert error.value.code not in {
        "unsupported_group_lineage_command",
        "unsupported_group_organization_command",
    }
    assert source.model_dump(mode="json") == original


def test_complete_converted_recipe_replays_without_recovery_and_edits_upstream_length():
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture

    design = create_empty_part("Crossover lineage", "HONEYCOMB")
    rows = []

    def snapshot(kind, inputs):
        nonlocal design
        params = {**inputs, "_proof_version": 1}
        design = execute(kind, design, params)
        rows.append(
            m.SnapshotLogEntry(
                id=f"row-{len(rows)}",
                op_kind=kind,
                label=kind,
                params=params,
                design_snapshot_gz_b64="poisoned pre",
                post_state_gz_b64="poisoned post",
            )
        )
        design = design.copy_with(feature_log=list(rows))

    snapshot(
        "bundle-create",
        crud.BundleRequest(
            cells=[[0, 0], [0, 1]],
            length_bp=96,
            history_seed="94016b09-1ea4-47c6-a1e7-50c2b6a89a45",
        ).model_dump(mode="json"),
    )
    request = placement(design)
    selected = next(
        strand
        for strand in design.strands
        if strand.domains[0].helix_id == request["half_a"]["helix_id"]
        and strand.domains[0].direction.value == request["half_a"]["strand"]
    )
    snapshot(
        "group-organize",
        {"expected_placement_ids": [item.id for item in design.cluster_transforms]},
    )
    snapshot(
        "group-create",
        {
            "group": {
                "id": "selected-0",
                "name": "Follow crossover",
                "helix_ids": [],
                "domain_ids": [{"strand_id": selected.id, "domain_index": 0}],
                "color": None,
                "opacity": 1.0,
                "is_default": False,
                "auto_created": False,
            }
        },
    )
    children = []
    for kind, inputs in (
        ("crossover-place", request),
        ("crossover-move", {"crossover_id": request["crossover_id"], "new_index": 28}),
    ):
        params = {**inputs, "_proof_version": 1}
        design = execute(kind, design, params)
        children.append(
            m.MinorMutationLogEntry(
                id=f"child-{len(children)}",
                op_subtype=kind,
                label=kind,
                params=params,
                diff_modified_b64="poisoned diff",
            )
        )
        design = design.copy_with(
            feature_log=[
                *rows,
                m.RoutingClusterLogEntry(
                    id="routing",
                    children=list(children),
                    pre_state_gz_b64="poisoned pre",
                    post_state_gz_b64="poisoned post",
                ),
            ]
        )
    report = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    edited, _ = prepare_change(
        design,
        capture(design, preserve_entry_types=True),
        0,
        lambda: None,
        params={"length_bp": 126},
    )
    report = assess_part_history(edited, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    assert edited.crossovers[0].half_a.index == 28
    assert refs(edited) == refs(design)
