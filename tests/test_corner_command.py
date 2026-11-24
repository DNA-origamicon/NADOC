"""Corner is authored through its public transaction and independently replayed."""

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import crud, headless_build as hb, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_corner_commands import preflight
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.core.corner_topology import corner_output_id
from backend.core.design_geometry import native_full_arrays_for_helix
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from tests.conftest import SIX_HB_CELLS


@pytest.mark.parametrize('direction', ['FORWARD', 'REVERSE'])
def test_corner_keeps_a_recorded_plane_nick_and_replays(direction):
    from backend.core.models import Design, Direction

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        helix_id = state.get_or_404().helices[0].id
        polarity = Direction(direction)
        hb.nick(helix_id, 83 if direction == 'FORWARD' else 84, polarity)
        hb.add_cluster('Nicked Corner source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Nicked Corner source')
        termini = {s.id for s in source.strands if any(
            d.helix_id == helix_id and d.direction == polarity for d in s.domains)}
        assert len(termini) == 2
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=84,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        result = state.get_or_404()
        assert {s.id for s in result.strands} == {s.id for s in source.strands}
        assert all(len(s.domains) == 1 for s in result.strands if s.id in termini)
        assert len(result.forced_ligations) == 11
        assert all(connection.three_prime_direction != polarity or
                   connection.three_prime_helix_id != helix_id for connection in result.forced_ligations)
        reopened = Design.model_validate_json(result.model_dump_json())
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof


def test_corner_preserves_native_continuous_scaffold_routing_and_existing_crossovers():
    from backend.core.models import Design, StrandType

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.auto_scaffold(seamless=True)
        hb.assign_scaffold_sequence(custom_sequence='ACGT' * 512)
        hb.assign_staple_sequences()
        hb.add_cluster('Routed Corner source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        assert len([s for s in source.strands if s.strand_type == StrandType.SCAFFOLD]) == 1
        assert source.crossovers
        owner = next(c for c in source.cluster_transforms if c.name == 'Routed Corner source')
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=84,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        result = state.get_or_404()
        assert [(s.id, s.strand_type) for s in result.strands] == [(s.id, s.strand_type) for s in source.strands]
        assert len(result.forced_ligations) == len(source.forced_ligations) + 12
        assert [c.id for c in result.crossovers] == [c.id for c in source.crossovers]
        old_ids = {h.id for h in source.helices}
        output_id = result.feature_log[-1].params['operation_id']
        originals = {corner_output_id(output_id, 'outgoing-helix', hid): hid for hid in old_ids}
        before_bases = {}
        for strand in source.strands:
            offset = 0
            for domain in strand.domains:
                step = 1 if domain.end_bp >= domain.start_bp else -1
                for bp in range(domain.start_bp, domain.end_bp + step, step):
                    before_bases[(domain.helix_id, bp, domain.direction)] = strand.sequence[offset]
                    offset += 1
        new_tips = 0
        for strand in result.strands:
            offset = 0
            for domain in strand.domains:
                incoming = domain.helix_id in old_ids
                old_id = domain.helix_id if incoming else originals[domain.helix_id]
                step = 1 if domain.end_bp >= domain.start_bp else -1
                for bp in range(domain.start_bp, domain.end_bp + step, step):
                    if incoming == (bp < 84):
                        expected = before_bases.get((old_id, bp, domain.direction), 'N')
                    else:
                        expected = 'N'
                        new_tips += 1
                    assert strand.sequence[offset] == expected
                    offset += 1
        assert new_tips > 0
        for old, new in zip(source.crossovers, result.crossovers):
            for name in ('half_a', 'half_b'):
                a, b = getattr(old, name), getattr(new, name)
                assert (a.index, a.strand) == (b.index, b.strand)
            assert result.find_helix(new.half_a.helix_id).lattice_frame_id == result.find_helix(new.half_b.helix_id).lattice_frame_id
        reopened = Design.model_validate_json(result.model_dump_json())
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof


def test_corner_keeps_owner_pose_and_uncut_members():
    from scipy.spatial.transform import Rotation

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        cut_ids = [h.id for h in state.get_or_404().helices]
        hb.extrude([[5, 5]], 28, 0, separate_fresh_extrusions=False)
        hb.add_cluster('Posed source', [h.id for h in state.get_or_404().helices], log=True)
        owner = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Posed source')
        hb.transform_cluster(owner.id, translation=[4, -3, 9], pivot=[2, 1, 7],
            rotation=Rotation.from_euler('xyz', [15, 32, -21], degrees=True).as_quat().tolist(),
            commit=True, log=True)
        source, revision = state.copy_for_persist()
        args = dict(cluster_id=owner.id, position_bp=84, angle_deg=90, direction_deg=15)
        guide, _ = preflight(source, args)
        create_corner(CreateCornerRequest(**args, expected_design_id=source.id, expected_revision=revision))
        result = state.get_or_404()
        owner_before = next(c for c in source.cluster_transforms if c.id == owner.id)
        owner_after = next(c for c in result.cluster_transforms if c.id == owner.id)
        for field in ('translation', 'rotation', 'pivot', 'parent_cluster_id'):
            assert getattr(owner_before, field) == getattr(owner_after, field)
        center, matrix = np.asarray(guide['center_nm']), np.asarray(guide['rotation'])
        operation_id = result.feature_log[-1].params['operation_id']
        for helix in source.helices:
            old = native_full_arrays_for_helix(helix, source)['positions']
            new = native_full_arrays_for_helix(result.find_helix(helix.id), result)['positions']
            np.testing.assert_allclose(new, old, atol=1e-9, rtol=0)
            if helix.id in cut_ids:
                hid = corner_output_id(operation_id, 'outgoing-helix', helix.id)
                moved = native_full_arrays_for_helix(result.find_helix(hid), result)['positions']
                np.testing.assert_allclose(moved, (old-center) @ matrix.T + center, atol=1e-9, rtol=0)
        proof = assess_part_history(result, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof


@pytest.mark.parametrize('lattice,cells', [
    (LatticeType.SQUARE, [[0, i] for i in range(8)]),
    (LatticeType.HONEYCOMB, SIX_HB_CELLS),
])
def test_recorded_corner_replays_geometry_and_undo_redo(lattice, cells):
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        cluster = next(c for c in source.cluster_transforms if c.name == 'Corner source')
        args = dict(cluster_id=cluster.id, position_bp=84, angle_deg=90, direction_deg=0)
        guide, _ = preflight(source, args)
        response = create_corner(CreateCornerRequest(**args, expected_design_id=source.id,
                                                     expected_revision=revision))
        result = state.get_or_404()
        entry = result.feature_log[-1]
        assert entry.op_kind == 'corner'
        assert response['corner']['feature_id'] == entry.id
        assert result.feature_log[:-1] == source.feature_log
        assert len(result.forced_ligations) == 2 * len(cells)
        assert all(link.extra_bases for link in result.forced_ligations)
        assert {s.strand_type.value for s in result.strands} == {'scaffold', 'staple'}
        center, rotation = np.asarray(guide['center_nm']), np.asarray(guide['rotation'])
        helix_map = {h.id: h for h in result.helices}
        for helix in source.helices:
            before = native_full_arrays_for_helix(helix, source)['positions']
            incoming = native_full_arrays_for_helix(helix_map[helix.id], result)['positions']
            outgoing_id = corner_output_id(entry.params['operation_id'], 'outgoing-helix', helix.id)
            outgoing = native_full_arrays_for_helix(helix_map[outgoing_id], result)['positions']
            np.testing.assert_allclose(incoming, before, atol=1e-9, rtol=0)
            np.testing.assert_allclose(outgoing, (before - center) @ rotation.T + center, atol=1e-9, rtol=0)
        proof = assess_part_history(result, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        state.undo()
        assert state.get_or_404().helices == source.helices
        assert state.get_or_404().strands == source.strands
        state.redo()
        assert state.get_or_404().helices == result.helices
        assert state.get_or_404().forced_ligations == result.forced_ligations
        before = state.get_or_404().model_dump()
        with pytest.raises(HTTPException) as caught:
            create_corner(CreateCornerRequest(**args, expected_design_id=source.id,
                                             expected_revision=revision))
        assert caught.value.status_code == 409
        assert state.get_or_404().model_dump() == before


def test_corner_on_twisted_bent_source_edits_and_deletes_with_stable_outputs():
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, i] for i in range(8)], 168, lattice=LatticeType.SQUARE,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        cluster = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Corner source')
        for kind, params in [('bend', {'kind': 'bend', 'curvature_deg_per_bp': .2, 'direction_deg': 30}),
                             ('twist', {'kind': 'twist', 'total_degrees': 45})]:
            add_deformation(AddDeformationBody(type=kind, plane_a_bp=7, plane_b_bp=140,
                cluster_ids=[cluster.id], params=params))
        source, revision = state.copy_for_persist()
        create_corner(CreateCornerRequest(cluster_id=cluster.id, position_bp=84, angle_deg=90,
            direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        corner = state.get_or_404()
        entry = corner.feature_log[-1]
        proof = assess_part_history(corner, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        crud.edit_feature(len(corner.feature_log) - 1, crud.EditFeatureBody(params={
            'angle_deg': 75, 'operation_id': 'cannot-replace-output-identities', '_proof_version': 999}))
        edited = state.get_or_404()
        assert edited.feature_log[-1].params['angle_deg'] == 75
        assert edited.feature_log[-1].params['operation_id'] == entry.params['operation_id']
        assert edited.feature_log[-1].params['_proof_version'] == entry.params['_proof_version'] == 3
        assert edited.feature_log[-1].id == entry.id
        assert [h.id for h in edited.helices] == [h.id for h in corner.helices]
        proof = assess_part_history(edited, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        crud.delete_feature(len(edited.feature_log) - 1)
        deleted = state.get_or_404()
        assert deleted.helices == source.helices
        assert deleted.strands == source.strands
        assert deleted.deformations == source.deformations
        assert deleted.forced_ligations == source.forced_ligations


def test_repeated_corners_follow_the_occupied_outgoing_path():
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 252, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        cluster = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Corner source')
        for position, direction in [(84, 0), (168, 90)]:
            source, revision = state.copy_for_persist()
            guide, _ = preflight(source, dict(cluster_id=cluster.id, position_bp=position,
                angle_deg=90, direction_deg=direction))
            from backend.core.corner_routing import occupied_duplex_spans
            spans = occupied_duplex_spans(source.strands)
            axes = {h.id: native_full_arrays_for_helix(h, source) for h in source.helices}
            for cut in guide['cuts']:
                sites = axes[cut['helix_id']]
                lo, _ = spans[cut['helix_id']]
                index = np.flatnonzero(sites['bp_indices'] == lo)[0]
                np.testing.assert_allclose(cut['incoming_path_nm'][0], sites['axis_points'][index], atol=1e-9)
            create_corner(CreateCornerRequest(cluster_id=cluster.id, position_bp=position,
                angle_deg=90, direction_deg=direction, expected_design_id=source.id,
                expected_revision=revision))
        result = state.get_or_404()
        assert len(result.helices) == 18
        assert len(result.forced_ligations) == 24
        assert sum(e.op_kind == 'corner' for e in result.feature_log if hasattr(e, 'op_kind')) == 2
        proof = assess_part_history(result, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof


@pytest.mark.parametrize('version,counts', [
    (1, [1, 2, 1, 2, 1, 1, 1, 2, 1, 1, 1, 2]),
    (2, [2, 3, 3, 3, 2, 3, 1, 5, 3, 3, 3, 4]),
    (3, [2, 3, 3, 3, 2, 3, 1, 5, 3, 3, 3, 4]),
])
def test_recorded_count_policy_survives_reopen_and_independent_replay(version, counts):
    from backend.api.part_corner_commands import CornerCommand, build
    from backend.core.models import Design
    from uuid import uuid4

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB, separate_fresh_extrusions=False)
        hb.add_cluster('Versioned Corner', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Versioned Corner')
        command = CornerCommand(cluster_id=owner.id, position_bp=84, angle_deg=90,
            direction_deg=15, operation_id=uuid4().hex, _proof_version=version)
        params = command.model_dump(mode='json', by_alias=True)
        # Same real recorder and regeneration path as POST /design/corner;
        # explicitly exercise the older saved command version as well.
        result, _, _ = state.mutate_with_feature_log(op_kind='corner',
            label='Corner: 90° at 84 bp', params=params,
            fn=lambda design: build(design, params), expected_revision=revision)
        assert [len(link.extra_bases) for link in result.forced_ligations] == counts
        reopened = Design.model_validate_json(result.model_dump_json())
        assert reopened.feature_log[-1].params['_proof_version'] == version
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
