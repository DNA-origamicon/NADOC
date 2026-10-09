"""End resizing must preserve the deformation frame of an inline tail's helix."""
import copy

import numpy as np
import pytest

from backend.core.deformation import (
    _apply_ovhg_rotations_to_axes,
    _rot_from_quaternion,
    deformed_helix_axes,
    deformed_nucleotide_arrays,
)
from backend.core.lattice import make_bundle_design, resize_strand_ends
from backend.core.models import BendParams, DeformationOp, Design, Direction, StrandType
from backend.core.sweep import SweepRequest, build_sweep


def fixture_design(kind):
    cells = [(0, 1), (1, 1)]
    if kind == 'sweep':
        return build_sweep(Design(), SweepRequest(
            cells=cells, points_nm=[(0, 0, 0), (10, 0, 10), (18, 0, 6)],
            ligate_adjacent=False,
        ))
    design = make_bundle_design(cells, 70)
    return design.copy_with(deformations=[DeformationOp(
        type='bend', plane_a_bp=0, plane_b_bp=69,
        affected_helix_ids=[h.id for h in design.helices],
        params=BendParams(curvature_deg_per_bp=.5),
    )])


def extend(design, strand, side, size=11):
    dom = strand.domains[0]
    end = '5p' if (side == 'low') == (dom.direction == Direction.FORWARD) else '3p'
    return resize_strand_ends(design, [dict(
        strand_id=strand.id, helix_id=dom.helix_id, end=end,
        delta_bp=-size if side == 'low' else size,
    )])


@pytest.mark.parametrize('kind', ['bend', 'sweep'])
@pytest.mark.parametrize('side', ['low', 'high'])
@pytest.mark.parametrize('direction', list(Direction))
def test_resize_preserves_existing_frames_and_continuous_tail(kind, side, direction):
    design = fixture_design(kind)
    strand = next(s for s in design.strands if s.strand_type == StrandType.STAPLE
                  and s.domains[0].direction == direction)
    old = {h.id: deformed_nucleotide_arrays(h, design) for h in design.helices}
    resized = extend(design, strand, side)
    assert resized.overhangs
    assert resized.forced_ligations == design.forced_ligations
    assert resized.crossovers == design.crossovers
    for h in resized.helices:
        actual = deformed_nucleotide_arrays(h, resized)
        previous = old[h.id]
        mask = np.isin(actual['bp_indices'], previous['bp_indices'])
        for field in ['positions', 'axis_points', 'axis_tangents']:
            np.testing.assert_allclose(actual[field][mask], previous[field], atol=1e-10)
        if h.id == strand.domains[0].helix_id:
            points = actual['positions'][actual['directions'] == (0 if direction == Direction.FORWARD else 1)]
            assert np.max(np.linalg.norm(np.diff(points, axis=0), axis=1)) < 1.0


@pytest.mark.parametrize('side', ['low', 'high'])
def test_long_sweep_extension_does_not_index_outside_arm(side):
    design = fixture_design('sweep')
    strand = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
    resized = extend(design, strand, side, size=200)
    helix = resized.find_helix(strand.domains[0].helix_id)
    actual = deformed_nucleotide_arrays(helix, resized)
    assert np.isfinite(actual['positions']).all()
    points = actual['axis_points'][actual['directions'] == 0]
    assert np.max(np.linalg.norm(np.diff(points, axis=0), axis=1)) < .5


@pytest.mark.parametrize('kind', ['bend', 'sweep'])
@pytest.mark.parametrize('side', ['low', 'high'])
@pytest.mark.parametrize('rotated', [False, True])
def test_overhang_axis_uses_deformed_domain_endpoints(kind, side, rotated):
    design = fixture_design(kind)
    strand = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
    resized = extend(design, strand, side)
    ovhg = resized.overhangs[0]
    if rotated:
        ovhg.rotation = [0., np.sin(.2), 0., np.cos(.2)]
        ovhg.translation = [1., -2., .5]
    axes = deformed_helix_axes(resized)
    ax = next(a for a in axes if a['helix_id'] == ovhg.helix_id)
    original = copy.deepcopy(ax)
    seg = next(s for s in original['segments'] if s.get('ovhg_id') == ovhg.id)
    _apply_ovhg_rotations_to_axes(resized, axes, nuc_lookup={})
    result = ax['ovhg_axes'][ovhg.id]
    rotation = _rot_from_quaternion(*ovhg.rotation)
    pivot = np.array(ovhg.pivot)
    for endpoint in ['start', 'end']:
        expected = rotation @ (np.array(seg[endpoint]) - pivot) + pivot + ovhg.translation
        np.testing.assert_allclose(result[endpoint], expected, atol=1e-10)
    np.testing.assert_array_equal(ax['samples'], original['samples'])
