"""Native slice metadata and committed axes must describe the same lattice."""
import math
import numpy as np
import pytest

from backend.core.models import Design, LatticeType, ClusterRigidTransform
from backend.core.lattice import make_bundle_design
from backend.core.lattice_frames import append_independent_bundle, append_frame_bundle
from backend.core.legacy_plane_extrusion import append_legacy_plane_bundle
from backend.core.deformation import deformed_helix_axes
from backend.core.vr_lattice_context import lattice_plane_context, lattice_context_records, PLANE_AXES
from backend.core.vr_scene_contract import parse_scene_contract


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('lattice', list(LatticeType))
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('length', [24, -24])
def test_slice_neighbors_match_committed_axes_after_view_and_placement(plane, lattice, legacy, length):
    cells = [(4, col) for col in range(-3, 5)]
    design = (make_bundle_design(cells, 24, plane=plane, lattice_type=lattice) if legacy else
              append_independent_bundle(Design(lattice_type=lattice), [list(c) for c in cells], 24, plane=plane))
    if legacy:
        for helix, cell in zip(design.helices, cells):
            helix.grid_pos = cell
            # Imported lattice rest coordinates are often centered elsewhere.
            for endpoint in [helix.axis_start, helix.axis_end]:
                for axis, delta in zip(PLANE_AXES[plane][:2], [12, -7]):
                    attr = 'xyz'[axis]
                    setattr(endpoint, attr, getattr(endpoint, attr)+delta)
        design.cluster_transforms = [ClusterRigidTransform(helix_ids=[h.id for h in design.helices])]
    placement = design.cluster_transforms[0]
    placement.rotation = [0, math.sin(.3), 0, math.cos(.3)]
    placement.translation = [3, -2, 8]
    placement.pivot = [5, 1, -4]
    view = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
    before = design.to_json()
    context = lattice_plane_context(design, plane, view)
    assert context['cells'] == cells
    assert design.to_json() == before
    # One adjacent column and one known distant row/column, including negatives.
    additions = [[4, 5], [-2, -8]]
    candidate = (append_legacy_plane_bundle(design, additions, length, plane=plane) if legacy else
                 append_frame_bundle(design, design.lattice_frames[0].id, additions, length, plane=plane))
    axes = {a['helix_id']: a for a in deformed_helix_axes(candidate)}
    for h, (row, col) in zip(candidate.helices[-2:], additions):
        # Independent formula matching the native cell helper, including signed HC parity.
        u = col*2.25 if lattice == LatticeType.SQUARE else col*1.125*math.sqrt(3)
        v = row*2.25 if lattice == LatticeType.SQUARE else row*3.375+((row+col) % 2)*1.125
        origin = context['origin'] + context['basis'][0]*u + context['basis'][1]*v
        for key, axial in [('start', min(0, length*.334)), ('end', max(0, length*.334))]:
            expected = origin+context['basis'][2]*axial
            np.testing.assert_allclose(view @ axes[h.id][key], expected, atol=1e-6)
    refreshed = lattice_plane_context(candidate, plane, view)
    assert set(refreshed['cells']) == set(cells+list(map(tuple, additions)))


def test_metadata_does_not_merge_independent_same_plane_frames():
    design = append_independent_bundle(Design(), [[0, 0]], 21)
    design = append_independent_bundle(design, [[0, 0]], 21, translation_nm=[20, 0, 0])
    assert lattice_plane_context(design, 'XY') is None
    design = append_independent_bundle(design, [[2, 3]], 21, plane='YZ')
    assert lattice_plane_context(design, 'YZ')['cells'] == [(2, 3)]


def test_metadata_contract_roundtrip_and_invalid_basis_cells():
    from pathlib import Path
    records = lattice_context_records(append_independent_bundle(Design(), [[-2, 7], [0, 0]], 21))
    fixture = Path('native/vr_viewer/examples/tool_scope_v12.nadocvr').read_text()
    header, geometry = fixture.replace('NADOCVR 12', 'NADOCVR 16', 1).split('\n', 1)
    scene = header+'\n'+'\n'.join(records)+'\n'+geometry
    assert parse_scene_contract(scene) == parse_scene_contract(fixture)
    record = records[0].split()
    bad_basis = record.copy(); bad_basis[5] = '2'
    duplicate_cell = record.copy(); duplicate_cell[-2:] = duplicate_cell[-4:-2]
    bad_count = record.copy(); bad_count[14] = '3'
    for bad in [bad_basis, duplicate_cell, bad_count]:
        with pytest.raises(ValueError):
            parse_scene_contract('NADOCVR 16 full strand\n'+' '.join(bad)+'\nR full\n')
    with pytest.raises(ValueError):
        parse_scene_contract('NADOCVR 16 full strand\n'+records[0]+'\n'+records[0]+'\nR full\n')
