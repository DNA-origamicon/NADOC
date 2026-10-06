"""Selection isolation, composition, history and representation parity for Bend/Twist."""
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.deformation import (
    apply_deformations_to_atoms, deformed_helix_axes,
    deformed_nucleotide_arrays, deformed_nucleotide_positions,
)
from backend.core.deformation_scope import resolve_deformation_targets
from backend.core.feature_log_edit import edit_deformation_entry
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    BendParams, ClusterRigidTransform, DeformationLogEntry, DeformationOp,
    Design, Direction, Domain, DomainRef, Strand, TwistParams,
)


@pytest.fixture
def design():
    d = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    a, b = [h.id for h in d.helices]
    strands = [Strand(id='forward', domains=[
        Domain(helix_id=a, start_bp=0, end_bp=20, direction=Direction.FORWARD),
        Domain(helix_id=a, start_bp=21, end_bp=41, direction=Direction.FORWARD)]),
        Strand(id='reverse', domains=[Domain(helix_id=a, start_bp=0, end_bp=41, direction=Direction.REVERSE)]),
        Strand(id='other', domains=[Domain(helix_id=b, start_bp=0, end_bp=41, direction=Direction.FORWARD)])]
    return d.copy_with(strands=strands, cluster_transforms=[ClusterRigidTransform(
        id='domain-cluster', helix_ids=[a], domain_ids=[DomainRef(strand_id='forward', domain_index=1)])])


def operation(d, targets, kind='bend'):
    ranges = resolve_deformation_targets(d, targets)
    return DeformationOp(type=kind, plane_a_bp=0, plane_b_bp=41,
                         params=BendParams(curvature_deg_per_bp=1.5, direction_deg=30) if kind == 'bend' else TwistParams(total_degrees=90),
                         targets=targets, target_ranges=ranges,
                         affected_helix_ids=sorted({r.helix_id for r in ranges}))


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_domain_isolation_overlap_and_representations(design, kind):
    targets = [{'kind': 'cluster', 'id': 'domain-cluster'},
               {'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1}]
    op = operation(design, targets, kind)
    assert len(op.target_ranges) == 1
    changed = design.copy_with(deformations=[op])
    h = design.helices[0]
    baseline = deformed_nucleotide_arrays(h, design)
    result = deformed_nucleotide_arrays(h, changed)
    mask = (result['directions'] == 0) & (result['bp_indices'] >= 21)
    full = deformed_nucleotide_arrays(h, design.copy_with(deformations=[op.model_copy(update={'target_ranges': None})]))
    for key in ('positions', 'base_positions', 'base_normals', 'axis_tangents', 'axis_points', 'radial_hats'):
        np.testing.assert_array_equal(result[key][~mask], baseline[key][~mask])
        np.testing.assert_allclose(result[key][mask], full[key][mask])
    assert np.max(abs(result['positions'][mask] - baseline['positions'][mask])) > 1
    scalar = deformed_nucleotide_positions(h, changed)
    np.testing.assert_allclose([n.position for n in scalar], result['positions'])
    np.testing.assert_allclose([n.base_normal for n in scalar], result['base_normals'])
    atoms = [SimpleNamespace(helix_id=h.id, bp_index=int(bp), direction='FORWARD' if direction == 0 else 'REVERSE',
                             x=float(p[0]), y=float(p[1]), z=float(p[2]))
             for bp, direction, p in zip(baseline['bp_indices'], baseline['directions'], baseline['positions'])]
    apply_deformations_to_atoms(atoms, changed)
    np.testing.assert_allclose([[a.x, a.y, a.z] for a in atoms], result['positions'], atol=1e-12)
    other = design.helices[1]
    np.testing.assert_array_equal(deformed_nucleotide_arrays(other, changed)['positions'],
                                  deformed_nucleotide_arrays(other, design)['positions'])


def test_disjoint_ops_on_same_helix_do_not_leak(design):
    a = operation(design, [{'kind': 'strand', 'id': 'forward'}])
    b = operation(design, [{'kind': 'strand', 'id': 'reverse'}], 'twist')
    h = design.helices[0]
    both = deformed_nucleotide_arrays(h, design.copy_with(deformations=[a, b]))
    for direction, op in enumerate((a, b)):
        single = deformed_nucleotide_arrays(h, design.copy_with(deformations=[op]))
        mask = both['directions'] == direction
        np.testing.assert_allclose(both['positions'][mask], single['positions'][mask])


def test_axis_segments_keep_unselected_partner_stationary(design):
    op = operation(design, [{'kind': 'strand', 'id': 'forward'}])
    before = deformed_helix_axes(design)[0]
    after = deformed_helix_axes(design.copy_with(deformations=[op]))[0]
    reverse = [s for s in after['segments'] if s['strand_id'] == 'reverse']
    assert reverse
    for segment in reverse:
        original = next(s for s in before['segments'] if s['bp_lo'] == segment['bp_lo'])
        np.testing.assert_array_equal(segment['start'], original['start'])
        np.testing.assert_array_equal(segment['end'], original['end'])
    assert any(s['strand_id'] == 'forward' and len(s['samples']) > 2 for s in after['segments'])


@pytest.mark.parametrize('targets', [[], [{'kind': 'strand', 'id': 'missing'}],
    [{'kind': 'domain', 'strandId': 'forward', 'domainIndex': 99}], [{'kind': 'base', 'key': 'x'}]])
def test_invalid_selection_rejected(design, targets):
    with pytest.raises(ValueError):
        resolve_deformation_targets(design, targets)


def test_persistence_and_parameter_edit_preserve_frozen_membership(design):
    op = operation(design, [{'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1}])
    entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
    d = Design.from_json(design.copy_with(deformations=[op], feature_log=[entry]).to_json())
    # Topology index changed after creation: tuning the angle must not retarget.
    strands = [s.model_copy(update={'domains': list(reversed(s.domains))}) if s.id == 'forward' else s for s in d.strands]
    d = d.copy_with(strands=strands)
    result = edit_deformation_entry(d, 0, d.feature_log[0], {
        'plane_a_bp': 0, 'plane_b_bp': 41, 'params': {'kind': 'bend', 'curvature_deg_per_bp': 2, 'direction_deg': 30}})
    assert result.deformations[0].target_ranges == op.target_ranges
    assert result.feature_log[0].op_snapshot.target_ranges == op.target_ranges


def test_api_preview_commit_and_empty_selection(design):
    client = TestClient(app)
    design_state.set_design(design)
    body = dict(type='twist', plane_a_bp=0, plane_b_bp=41,
                params={'kind': 'twist', 'total_degrees': 90},
                targets=[{'kind': 'strand', 'id': 'forward'}, {'kind': 'strand', 'id': 'other'}])
    assert client.post('/api/design/deformation', json={**body, 'targets': []}).status_code == 400
    assert not design_state.get_or_404().deformations
    assert client.post('/api/design/deformation/validate', json=body).status_code == 200
    response = client.post('/api/design/deformation', json={**body, 'preview': True})
    assert response.status_code == 200, response.text
    preview = design_state.get_or_404().deformations[-1]
    assert not design_state.get_or_404().feature_log
    client.delete(f'/api/design/deformation/{preview.id}?preview=true')
    response = client.post('/api/design/deformation', json=body)
    assert response.status_code == 200, response.text
    d = design_state.get_or_404()
    assert len(d.feature_log) == 1
    assert d.feature_log[0].op_snapshot.target_ranges == preview.target_ranges


def test_selection_composes_with_existing_bend_and_cluster_pose(design):
    from backend.core.models import LoopSkip
    # Include inserted/removed sites and a nonidentity parent pose.
    h = design.helices[0].model_copy(update={'loop_skips': [LoopSkip(bp_index=25, delta=1), LoopSkip(bp_index=8, delta=-1)]})
    pose = ClusterRigidTransform(helix_ids=[h.id], translation=(2, -3, 4), rotation=(0, 0, 0.3826834324, 0.9238795325))
    design = design.copy_with(helices=[h, design.helices[1]], cluster_transforms=[pose])
    old = operation(design, [{'kind': 'strand', 'id': 'forward'}], 'twist').model_copy(update={'targets': None, 'target_ranges': None})
    selected = operation(design, [{'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1}])
    baseline = deformed_nucleotide_arrays(h, design.copy_with(deformations=[old]))
    result = deformed_nucleotide_arrays(h, design.copy_with(deformations=[old, selected]))
    full = deformed_nucleotide_arrays(h, design.copy_with(deformations=[old, selected.model_copy(update={'target_ranges': None})]))
    mask = (result['bp_indices'] >= 21) & (result['directions'] == 0)
    for key in ('positions', 'base_normals', 'axis_tangents'):
        np.testing.assert_array_equal(result[key][~mask], baseline[key][~mask])
        np.testing.assert_allclose(result[key][mask], full[key][mask])


def test_feature_preview_uses_saved_scope_after_domain_reordering(design):
    client = TestClient(app)
    op = operation(design, [{'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1}])
    entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
    strands = [s.model_copy(update={'domains': list(reversed(s.domains))}) if s.id == 'forward' else s for s in design.strands]
    design_state.set_design(design.copy_with(strands=strands, feature_log=[entry]))
    response = client.post('/api/design/deformation', json={
        'type': 'bend', 'plane_a_bp': 0, 'plane_b_bp': 41, 'params': op.params.model_dump(),
        'targets': op.targets, 'source_operation_id': op.id, 'preview': True})
    assert response.status_code == 200, response.text
    assert design_state.get_or_404().deformations[-1].target_ranges == op.target_ranges


def test_validation_warns_at_selected_domain_boundary(design):
    design_state.set_design(design)
    response = TestClient(app).post('/api/design/deformation/validate', json={
        'type': 'twist', 'plane_a_bp': 0, 'plane_b_bp': 41,
        'params': {'kind': 'twist', 'total_degrees': 10},
        'targets': [{'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1}]})
    assert response.status_code == 200
    assert 'selection boundary' in response.json()['message']


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_measured_display_keeps_stationary_partner_exactly_unchanged(design, kind):
    from backend.core.design_geometry import _geometry_for_helices
    before = _geometry_for_helices(design, measured_positioning=True, junction_balance=True)
    op = operation(design, [{'kind': 'strand', 'id': 'forward'}], kind)
    after = _geometry_for_helices(design.copy_with(deformations=[op]), measured_positioning=True, junction_balance=True)
    stationary = lambda rows: [n for n in rows if n['strand_id'] != 'forward']
    assert stationary(after) == stationary(before)
    assert after != before


def test_new_scope_preserves_existing_legacy_arm_composition(design):
    # Preserve legacy frame composition even when old per-helix operations share
    # one arm: introducing a scoped operation must not rewrite stationary geometry.
    design = design.copy_with(cluster_transforms=[])
    a, b = [h.id for h in design.helices]
    old_a = DeformationOp(type='twist', plane_a_bp=0, plane_b_bp=41,
                          affected_helix_ids=[a], params=TwistParams(total_degrees=20))
    old_b = DeformationOp(type='bend', plane_a_bp=0, plane_b_bp=41,
                          affected_helix_ids=[b], params=BendParams(curvature_deg_per_bp=0.2))
    before = design.copy_with(deformations=[old_a, old_b])
    added = operation(design, [{'kind': 'strand', 'id': 'other'}])
    after = before.copy_with(deformations=[old_a, old_b, added])
    np.testing.assert_array_equal(deformed_nucleotide_arrays(design.helices[0], before)['positions'],
                                  deformed_nucleotide_arrays(design.helices[0], after)['positions'])


def test_mixed_targets_on_disconnected_rotated_arms(design):
    from backend.core.models import Vec3
    h = design.helices[1].model_copy(update={'grid_pos': None,
        'axis_start': Vec3(x=20, y=10, z=6), 'axis_end': Vec3(x=34.028, y=10, z=6)})
    design = design.copy_with(helices=[design.helices[0], h])
    refs = [{'kind': 'cluster', 'id': 'domain-cluster'},
            {'kind': 'domain', 'strandId': 'forward', 'domainIndex': 1},
            {'kind': 'strand', 'id': 'other'}]
    combined = operation(design, refs)
    assert set(combined.affected_helix_ids) == {x.id for x in design.helices}
    for helix, targets in [(design.helices[0], refs[:2]), (h, refs[2:])]:
        actual = deformed_nucleotide_arrays(helix, design.copy_with(deformations=[combined]))
        independent = deformed_nucleotide_arrays(helix, design.copy_with(deformations=[operation(design, targets)]))
        np.testing.assert_allclose(actual['positions'], independent['positions'])
        assert not np.array_equal(actual['positions'], deformed_nucleotide_arrays(helix, design)['positions'])
