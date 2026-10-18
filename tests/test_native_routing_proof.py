"""Native routing commands preserve complete authoring state through replay."""

import pytest
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-routing-proof-test")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=42))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def assert_verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize(
    "operation",
    ["nick", "nick-batch", "strand-delete", "strand-delete-batch", "domain-delete"],
)
def test_native_routing_replay(operation):
    d = state.get_or_404()
    strand = d.strands[0]
    dom = strand.domains[0]
    if operation == "nick":
        crud.add_nick(
            crud.NickRequest(
                helix_id=dom.helix_id, bp_index=20, direction=dom.direction
            )
        )
    elif operation == "nick-batch":
        crud.add_nick_batch(
            crud.NickBatchRequest(
                nicks=[
                    dict(helix_id=dom.helix_id, bp_index=20, direction=dom.direction)
                ]
            )
        )
    elif operation == "strand-delete":
        crud.delete_strand(strand.id)
    elif operation == "strand-delete-batch":
        crud.delete_strands_batch(crud.StrandBatchDeleteRequest(strand_ids=[strand.id]))
    else:
        crud.delete_domain(strand.id, 0)
    assert_verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert_verified()
    assert state.get_or_404().helices[0].length_bp == 48


def test_nick_child_parameter_edit_and_delete_rebuild_strands():
    d = state.get_or_404()
    dom = d.strands[0].domains[0]
    original_count = len(d.strands)
    crud.add_nick(
        crud.NickRequest(helix_id=dom.helix_id, bp_index=20, direction=dom.direction)
    )
    child_id = state.get_or_404().feature_log[1].children[0].id
    crud.edit_feature(1, crud.EditFeatureBody(params={"bp_index": 10}), sub_index=0)
    current = state.get_or_404()
    assert current.feature_log[1].children[0].id == child_id
    assert len(current.strands) == original_count + 1
    assert_verified()
    crud.delete_feature(1, sub_index=0)
    assert len(state.get_or_404().strands) == original_count
    assert_verified()


@pytest.mark.parametrize("operation", ["strand-end-resize", "domain-shift"])
def test_resize_and_domain_shift(operation):
    d = state.get_or_404()
    s = d.strands[0]
    if operation == "strand-end-resize":
        crud.strand_end_resize(
            crud.StrandEndResizeRequest(
                entries=[
                    dict(
                        strand_id=s.id,
                        helix_id=s.domains[0].helix_id,
                        end="3p",
                        delta_bp=-3,
                    )
                ]
            )
        )
    else:
        crud.domain_shift(
            crud.DomainShiftRequest(
                entries=[dict(strand_id=s.id, domain_index=0, delta_bp=3)]
            )
        )
    assert_verified()


@pytest.mark.parametrize(
    "operation", ["loop-skip-insert", "loop-skip-twist", "loop-skip-bend"]
)
def test_loop_skip_commands(operation):
    from backend.api.routes_loop_skip import (
        insert_loop_skip,
        LoopSkipInsertRequest,
        apply_twist_loop_skips,
        apply_bend_loop_skips,
    )

    hid = state.get_or_404().helices[0].id
    if operation == "loop-skip-insert":
        insert_loop_skip(LoopSkipInsertRequest(helix_id=hid, bp_index=10, delta=-1))
    elif operation == "loop-skip-twist":
        apply_twist_loop_skips(
            dict(helix_ids=[hid], plane_a_bp=0, plane_b_bp=35, target_twist_deg=20)
        )
    else:
        apply_bend_loop_skips(
            dict(helix_ids=[hid], plane_a_bp=0, plane_b_bp=35, radius_nm=100)
        )
    assert_verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert_verified()


def test_sequence_commands_regenerate_after_length_edit():
    from backend.api.routes_assign_sequences import (
        assign_scaffold_sequence_endpoint,
        assign_staple_sequences_endpoint,
        _ScaffoldSeqBody,
    )

    assign_scaffold_sequence_endpoint(_ScaffoldSeqBody(custom_sequence="ACGT" * 30))
    assign_staple_sequences_endpoint()
    assert_verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert_verified()
    assert all(len(s.sequence) == 48 for s in state.get_or_404().strands)


@pytest.mark.parametrize("kind", ["circular-pattern", "linear-pattern"])
def test_pattern_identity_and_regeneration(kind):
    from backend.api.routes_clusters import _create_pattern
    from backend.api.pattern_features import CircularPatternBody, LinearPatternBody

    cid = state.get_or_404().cluster_transforms[0].id
    if kind == "circular-pattern":
        body = CircularPatternBody(
            cluster_id=cid,
            instances=3,
            total_angle=180,
            axis_point=[0, 0, 0],
            axis_direction=[0, 0, 1],
        )
    else:
        body = LinearPatternBody(cluster_ids=[cid], instances=3, spacing=10)
    _create_pattern(kind, body)
    assert_verified()
    ids = [h.id for h in state.get_or_404().helices]
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert [h.id for h in state.get_or_404().helices] == ids
    assert_verified()


def test_sweep_regenerates_and_keeps_identity():
    from backend.api.routes_sweep import create_sweep
    from backend.core.sweep import SweepRequest

    create_sweep(
        SweepRequest(
            cells=[(4, 4)], points_nm=[(0, 0, 0), (0, 0, 10)], ligate_adjacent=False
        )
    )
    assert_verified()
    ids = [h.id for h in state.get_or_404().helices]
    crud.edit_feature(
        1, crud.EditFeatureBody(params={"points_nm": [(0, 0, 0), (0, 0, 12)]})
    )
    assert [h.id for h in state.get_or_404().helices] == ids
    assert_verified()


@pytest.mark.parametrize(
    "operation",
    [
        "helix-update",
        "helix-reorder",
        "strands-color-bulk",
        "strands-reference",
        "strand-update",
        "domain-add",
    ],
)
def test_structural_native_commands(operation):
    d = state.get_or_404()
    h, s = d.helices[0], d.strands[0]
    if operation == "helix-update":
        crud.update_helix(
            h.id,
            crud.HelixRequest(
                axis_start=h.axis_start,
                axis_end=h.axis_end,
                length_bp=h.length_bp,
                phase_offset=0.2,
            ),
        )
    elif operation == "helix-reorder":
        crud.reorder_helices(crud.ReorderHelicesBody(ordered_ids=[h.id]))
    elif operation == "strands-color-bulk":
        crud.patch_strands_color(
            crud.BulkColorRequest(strand_ids=[s.id], color="#123456")
        )
    elif operation == "strands-reference":
        crud.patch_strands_reference(
            crud.BulkReferenceRequest(strand_ids=[s.id], is_reference=True)
        )
    elif operation == "strand-update":
        crud.update_strand(
            s.id,
            crud.StrandRequest(
                domains=[dom.model_dump() for dom in s.domains],
                strand_type=s.strand_type,
            ),
        )
    else:
        crud.add_domain(
            s.id,
            crud.DomainRequest(
                helix_id=h.id, start_bp=45, end_bp=46, direction="FORWARD"
            ),
        )
    assert_verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert_verified()


def test_add_helix_strand_then_delete_producer_requires_cascade():
    crud.add_helix(
        crud.HelixRequest(
            axis_start=dict(x=10, y=0, z=0), axis_end=dict(x=10, y=0, z=7), length_bp=21
        )
    )
    hid = state.get_or_404().helices[-1].id
    crud.add_strand(
        crud.StrandRequest(
            domains=[dict(helix_id=hid, start_bp=0, end_bp=20, direction="FORWARD")],
            strand_type="staple",
        )
    )
    assert_verified()
    result = crud.delete_feature(1, sub_index=0)
    assert result["needs_cascade_decision"]
    crud.delete_feature(1, sub_index=0, cascade=True)
    assert hid not in {h.id for h in state.get_or_404().helices}
    assert_verified()


def test_delete_unreferenced_helix_replays():
    crud.add_helix(
        crud.HelixRequest(
            axis_start=dict(x=10, y=0, z=0), axis_end=dict(x=10, y=0, z=7), length_bp=21
        )
    )
    crud.delete_helix(state.get_or_404().helices[-1].id)
    assert_verified()


@pytest.mark.parametrize("batch", [False, True])
def test_crossover_ids_are_recorded_before_construction(batch):
    from tests.test_crossover_placement import _nick_positions

    crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=42))
    a, b = state.get_or_404().helices
    na, nb = _nick_positions(7, "REVERSE", "FORWARD")
    request = crud.PlaceCrossoverRequest(
        half_a=dict(helix_id=a.id, index=7, strand="REVERSE"),
        half_b=dict(helix_id=b.id, index=7, strand="FORWARD"),
        nick_bp_a=na,
        nick_bp_b=nb,
    )
    if batch:
        crud.place_crossover_batch(
            crud.PlaceCrossoverBatchRequest(placements=[request])
        )
    else:
        crud.place_crossover(request)
    assert_verified()
    identity = state.get_or_404().crossovers[0].id
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert state.get_or_404().crossovers[0].id == identity == str(request.crossover_id)
    assert_verified()


def test_first_helix_from_empty_root_is_reproducible():
    from backend.core.part_history_contract import create_empty_part

    state.load_design(create_empty_part("Empty", "HONEYCOMB"))
    crud.add_helix(
        crud.HelixRequest(
            axis_start=dict(x=0, y=0, z=0), axis_end=dict(x=0, y=0, z=7), length_bp=21
        )
    )
    assert_verified()


@pytest.mark.parametrize("batch", [False, True])
def test_junction_delete_and_extra_bases(batch):
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=42))
    crud.auto_crossover()
    cid = state.get_or_404().crossovers[0].id
    if batch:
        crud.batch_patch_crossover_extra_bases(
            crud.BatchCrossoverExtraBasesRequest(
                entries=[dict(crossover_id=cid, sequence="AC")]
            )
        )
    else:
        crud.patch_crossover_extra_bases(
            cid, crud.CrossoverExtraBasesRequest(sequence="AC")
        )
    assert_verified()
    if batch:
        crud.batch_delete_crossovers(
            crud.BatchDeleteCrossoversRequest(crossover_ids=[cid])
        )
    else:
        crud.delete_crossover(cid)
    assert_verified()


@pytest.mark.parametrize("repair", ["ligate", "forced", "forced-batch"])
def test_native_ligation_repair_and_deletion(repair):
    d = state.get_or_404()
    strand = d.strands[0]
    dom = strand.domains[0]
    request = crud.NickRequest(
        helix_id=dom.helix_id, bp_index=20, direction=dom.direction
    )
    crud.add_nick(request)
    if repair == "ligate":
        crud.ligate_strand(request)
    else:
        parts = [
            s for s in state.get_or_404().strands if s.strand_type == strand.strand_type
        ]
        a = next(s for s in parts if s.domains[-1].end_bp == 20)
        b = next(s for s in parts if s.id != a.id)
        crud.forced_ligation(
            crud.ForcedLigationRequest(
                three_prime_strand_id=a.id, five_prime_strand_id=b.id
            )
        )
        assert_verified()
        fid = state.get_or_404().forced_ligations[0].id
        crud.patch_forced_ligation_extra_bases(
            fid, crud.CrossoverExtraBasesRequest(sequence="AC")
        )
        assert_verified()
        if repair == "forced-batch":
            crud.batch_delete_forced_ligations(
                crud.BatchDeleteForcedLigationsRequest(forced_ligation_ids=[fid])
            )
        else:
            crud.delete_forced_ligation(fid)
    assert_verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert_verified()


def test_strand_sequence_records_combined_metadata_edits():
    sid = state.get_or_404().strands[0].id
    crud.patch_strand(
        sid,
        crud.StrandPatchRequest(
            name="Selected",
            notes="sequence note",
            color="#123456",
            sequence="ACGT" * 10 + "AC",
        ),
    )
    assert_verified()
    crud.patch_strand(sid, crud.StrandPatchRequest(sequence=None, name="Cleared"))
    assert_verified()


@pytest.mark.parametrize("batch", [False, True])
def test_crossover_move_native_recipe_and_upstream_edit(batch):
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=63))
    d = state.get_or_404()
    a, b = d.helices
    from tests.test_crossover_placement import _nick_positions

    na, nb = _nick_positions(7, "REVERSE", "FORWARD", False)
    crud.place_crossover(
        crud.PlaceCrossoverRequest(
            half_a=dict(helix_id=a.id, index=7, strand="REVERSE"),
            half_b=dict(helix_id=b.id, index=7, strand="FORWARD"),
            nick_bp_a=na,
            nick_bp_b=nb,
        )
    )
    identity = state.get_or_404().crossovers[0].id
    request = crud.MoveCrossoverRequest(crossover_id=identity, new_index=28)
    if batch:
        crud.batch_move_crossovers(crud.BatchMoveCrossoversRequest(moves=[request]))
    else:
        crud.move_crossover_endpoint(request)
    result = verify_current_part()
    assert result["status"] == "verified", result
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 84}))
    result = verify_current_part()
    assert result["status"] == "verified", result
    assert state.get_or_404().crossovers[0].half_a.index == 28
    assert state.get_or_404().crossovers[0].id == identity
