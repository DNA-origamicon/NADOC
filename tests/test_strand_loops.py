"""Strand-specific loops preserve topology, sequence register and recorded process."""
from uuid import UUID

import numpy as np
import pytest

from experiments.recorded_review_process import Process, verify
from backend.core.models import Design
from backend.core.sequences import (
    strand_nucleotide_count, build_scaffold_base_map, strand_partner_bases)
from backend.core.strand_loops import set_loop, strand_entries
from backend.core.strand_loop_geometry import ellipse_points
from scripts.agent_structure_guard import publish, audit


def process():
    result = Process('Loop test')
    result.append('bundle-create', {'_proof_version': 1, 'history_seed': str(UUID(int=124)),
        'cells': [[0, 0]], 'length_bp': 21, 'name': 'Loop test',
        'lattice_type': 'HONEYCOMB', 'ligate_adjacent': False}, 'Create helix')
    return result


def params(strand, length=30):
    d = strand.domains[0]
    return dict(_proof_version=1, strand_id=strand.id, helix_id=d.helix_id, bp_index=10,
                direction=d.direction.value, length=length, aspect_ratio=3.0)


def test_saved_loop_process_independently_replays(tmp_path):
    p = process()
    p.append('strand-loop-set', params(p.design.strands[0]), 'Add 30 unpaired bases')
    assert verify(p.design)['commands'] == 2
    destination = tmp_path / '__e2e__loop.nadoc'
    publish(p.design, destination)
    reopened = Design.model_validate_json(destination.read_text())
    assert audit(reopened)['status'] == 'verified'
    assert reopened.strands[0].loops[0].length == 30


@pytest.mark.parametrize('scaffold_loop', [True, False])
def test_sequence_consumption_and_unpaired_partners(scaffold_loop):
    p = process()
    strand = next(s for s in p.design.strands if s.is_scaffold == scaffold_loop)
    p.append('strand-loop-set', params(strand), 'Add loop')
    design = p.design
    target = next(s for s in design.strands if s.id == strand.id)
    assert strand_nucleotide_count(target, design) == 51
    partner = next(s for s in design.strands if s.id != target.id)
    assert strand_nucleotide_count(partner, design) == 21
    p.append('assign-scaffold-sequence', {'_proof_version': 1, 'scaffold_name': 'M13mp18'}, 'Assign scaffold')
    p.append('assign-staple-sequences', {'_proof_version': 1}, 'Assign complements')
    design = p.design
    scaffold = design.scaffolds()[0]
    staple = next(s for s in design.strands if not s.is_scaffold)
    assert len(scaffold.sequence) == (51 if scaffold_loop else 21)
    assert len(staple.sequence) == (21 if scaffold_loop else 51)
    entries = list(strand_entries(design, scaffold))
    mapping = build_scaffold_base_map(design)
    for index, entry in enumerate(entries):
        if entry[3] == 0:
            assert mapping[entry[:3]] == [scaffold.sequence[index]]
    partners = strand_partner_bases(design, staple)
    assert sum(base is None for base in partners) == (0 if scaffold_loop else 30)


def test_resize_preserves_manual_bases_and_remove_restores_register():
    p = process()
    strand = next(s for s in p.design.strands if not s.is_scaffold)
    p.append('strand-loop-set', params(strand, 6), 'Add six-base loop')
    strand = next(s for s in p.design.strands if s.id == strand.id)
    entries = list(strand_entries(p.design, strand))
    start = next(i for i, entry in enumerate(entries) if entry[3] == 1)
    sequence = 'A' * start + 'CGTACG' + 'T' * (len(entries) - start - 6)
    p.append('strand-sequence', {'_proof_version': 1, 'strand_id': strand.id, 'sequence': sequence}, 'Edit loop sequence')
    p.append('strand-loop-set', params(strand, 8), 'Resize loop')
    updated = next(s for s in p.design.strands if s.id == strand.id)
    assert updated.sequence[start:start + 8] == 'CGTACGNN'
    p.append('strand-loop-set', params(strand, 0), 'Remove loop')
    updated = next(s for s in p.design.strands if s.id == strand.id)
    assert updated.sequence == 'A' * start + 'T' * (21 - start)
    assert not updated.loops
    verify(p.design)


def test_terminal_anchor_refused_without_mutation():
    design = process().design
    strand = design.strands[0]
    request = params(strand)
    request['bp_index'] = strand.domains[-1].end_bp
    before = design.model_dump_json()
    with pytest.raises(ValueError, match='following nucleotide'):
        set_loop(design, request)
    assert design.model_dump_json() == before


@pytest.mark.parametrize('length', [2, 6, 30, 80])
def test_ellipse_fixed_roots_contour_and_axial_preference(length):
    points = ellipse_points([1, 0, 0], [1, 0, .34], [0, 0, 1], [1, 0, 0], length)
    np.testing.assert_array_equal(points[0], [1, 0, 0])
    np.testing.assert_allclose(points[-1], [1, 0, .34], atol=1e-12)
    assert np.isfinite(points).all()
    assert np.linalg.norm(np.diff(points, axis=0), axis=1).max() < .8
    if length >= 6:
        assert np.ptp(points[:, 2]) > np.ptp(points[:, 0])


def test_geometry_adds_only_owned_loop_nucleotides():
    from backend.core.design_geometry import _geometry_for_design, _compact_geometry_from_nucleotides
    p = process()
    before = _geometry_for_design(p.design)
    target = next(s for s in p.design.strands if not s.is_scaffold)
    p.append('strand-loop-set', params(target), 'Add reverse strand loop')
    after = _geometry_for_design(p.design)
    assert len(after) == len(before) + 30
    for old, new in zip(before, after):
        assert new['backbone_position'] == old['backbone_position']
    extra = after[len(before):]
    assert all(n['strand_id'] == target.id and n['is_unpaired'] for n in extra)
    assert [n['loop_order'] for n in extra] == list(range(1, 31))
    compact = _compact_geometry_from_nucleotides(after)
    assert sum(v is not None for h in compact.values() for b in h.values() for v in b.get('looporder', [])) == 31


def test_real_route_records_undo_and_replay():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state, doc_context
    from backend.api.routes_loop_skip import router
    token = doc_context.set_current_doc('__e2e__strand_loop_route')
    try:
        state.load_design(process().design)
        app = FastAPI()
        app.include_router(router)
        target = state.get_or_404().strands[0]
        request = params(target)
        request.pop('_proof_version')
        response = TestClient(app).post('/design/strand-loop', json=request)
        assert response.status_code == 200, response.text
        assert state.get_or_404().strands[0].loops[0].length == 30
        verify(state.get_or_404())
        assert state.undo_depth() == 1
    finally:
        state.close_session()
        doc_context.reset_current_doc(token)


def test_loop_moves_with_nicked_fragment_and_ligates_without_sequence_loss():
    p = process()
    strand = p.design.strands[0]
    p.append('strand-loop-set', params(strand), 'Add loop')
    original = p.design.strands[0].sequence
    p.append('nick', {'_proof_version': 1, 'helix_id': strand.domains[0].helix_id,
        'bp_index': 5, 'direction': 'FORWARD'}, 'Nick before loop')
    owners = [s for s in p.design.strands if s.loops]
    assert len(owners) == 1
    assert owners[0].domains[0].start_bp == 6
    assert len(owners[0].sequence) == 45
    p.append('ligate', {'_proof_version': 1, 'helix_id': strand.domains[0].helix_id,
        'bp_index': 5, 'direction': 'FORWARD'}, 'Ligate nick')
    owner = next(s for s in p.design.strands if s.loops)
    assert owner.sequence == original
    verify(p.design)


def test_staple_loop_manual_sequence_survives_scaffold_reassignment():
    p = process()
    strand = next(s for s in p.design.strands if not s.is_scaffold)
    p.append('strand-loop-set', params(strand, 6), 'Add loop')
    p.append('strand-sequence', {'_proof_version': 1, 'strand_id': strand.id,
        'sequence': 'A' * 27}, 'Set manual bases')
    p.append('assign-scaffold-sequence', {'_proof_version': 1, 'scaffold_name': 'M13mp18'}, 'Assign scaffold')
    p.append('assign-staple-sequences', {'_proof_version': 1}, 'Assign complements')
    design = p.design
    staple = next(s for s in design.strands if s.id == strand.id)
    for i, entry in enumerate(strand_entries(design, staple)):
        if entry[3]:
            assert staple.sequence[i] == 'A'


def test_loop_orientation_rotates_plane_and_preserves_roots():
    original = ellipse_points([1, 0, 0], [1, 0, .34], [0, 0, 1], [1, 0, 0], 30)
    rotated = ellipse_points([1, 0, 0], [1, 0, .34], [0, 0, 1], [1, 0, 0], 30, rotation_deg=90)
    np.testing.assert_allclose(original[:, 0] - 1, rotated[:, 1], atol=1e-12)
    np.testing.assert_allclose(original[:, 2], rotated[:, 2], atol=1e-12)
    np.testing.assert_allclose(rotated[:, 0], 1, atol=1e-12)


@pytest.mark.parametrize('length', [1, 2, 6, 30, 80])
@pytest.mark.parametrize('scaffold', [True, False])
def test_loop_bases_flip_with_quarter_turn_at_major_axis_tips(length, scaffold):
    from scipy.spatial.transform import Rotation
    from backend.core.constants import BASE_DISPLACEMENT, SSDNA_CONTOUR_PER_NT_NM
    from backend.core.design_geometry import _geometry_for_design
    p = process()
    s = next(s for s in p.design.strands if s.is_scaffold == scaffold)
    old = _geometry_for_design(p.design)
    p.append('strand-loop-set', params(s, length), 'Add loop')
    geometry = _geometry_for_design(p.design)
    inserted = [n for n in geometry if n.get('loop_order', 0) > 0]
    anchor = next(n for n in geometry if n['strand_id'] == s.id and n['bp_index'] == 10
                  and not n.get('loop_order', 0))
    axis = np.array(anchor['axis_tangent'])
    axial = np.array([n['backbone_position'] for n in inserted]) @ axis
    for i, n in enumerate(inserted):
        tangent = np.array(n['axis_tangent'])
        original = np.array(anchor['base_normal'])
        original -= tangent * np.dot(original, tangent)
        if np.linalg.norm(original) < 1e-8:
            original = np.cross(tangent, np.eye(3)[np.argmin(np.abs(tangent))])
        original /= np.linalg.norm(original)
        tip = min(axial[i] - axial.min(), axial.max() - axial[i]) <= SSDNA_CONTOUR_PER_NT_NM + 1e-9
        expected = np.cross(tangent, original) if tip else -original
        np.testing.assert_allclose(n['base_normal'], expected, atol=1e-12)
        np.testing.assert_allclose(np.array(n['base_position'])-n['backbone_position'],
                                   BASE_DISPLACEMENT * expected, atol=1e-12)
        np.testing.assert_allclose(Rotation.from_quat(n['slab_quaternion']).as_matrix()[:, 2], expected, atol=1e-12)
        assert n['placement_source'] == (('strand-loop-ellipse-v4-ring-priority' if length < 40 else 'strand-loop-ellipse-v3-bond-optimum') if length >= 6 else 'strand-loop-ellipse-v2')
    for before, after in zip(old, geometry):
        for field in ('backbone_position', 'base_position', 'slab_position', 'slab_quaternion'):
            assert after[field] == before[field]


def test_tip_selection_tracks_rotated_major_axis_and_symmetric_pairs():
    from scipy.spatial.transform import Rotation
    from backend.core.strand_loop_geometry import loop_base_rotation_angles
    points = np.array([[0,0,0], [1,0,2], [2,0,2], [3,0,0], [2,0,-2], [1,0,-2], [0,0,0]])
    expected = [90,90,180,90,90]
    np.testing.assert_array_equal(loop_base_rotation_angles(points, [0,0,1]), expected)
    rotate = Rotation.from_euler('xyz', [37,19,-52], degrees=True)
    np.testing.assert_array_equal(loop_base_rotation_angles(rotate.apply(points)+[5,8,13], rotate.apply([0,0,1])), expected)


@pytest.mark.parametrize('length', [6, 30, 80])
@pytest.mark.parametrize('scaffold', [True, False])
def test_tip_turns_do_not_intersect_other_loop_bases(length, scaffold):
    from backend.core.design_geometry import _geometry_for_design
    from experiments.loop_orientation_comparison import context, measure
    p = process()
    strand = next(s for s in p.design.strands if s.is_scaffold == scaffold)
    p.append('strand-loop-set', params(strand, length), 'Add loop')
    records = _geometry_for_design(p.design)
    ctx = context(records)
    report = measure(records, ctx, ctx['centers'], ctx['mats'])
    assert report['by_group']['loop'] == 0
