import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import headless_build as hb, state
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.core.corner_wedge_paths import corner_bundle_paths, corner_wedge_paths
from backend.core.deformation import _bundle_centroid_and_tangent, effective_helix_for_geometry
from backend.core.design_geometry import native_full_arrays_for_helix, native_full_phase_roll_rad
from backend.core.geometry import nucleotide_positions_arrays
from backend.core.models import LatticeType
from backend.core.native_full_placement import place_native_full
from backend.core.sweep_path import sweep_frames


@pytest.mark.parametrize('operations', [(), ('bend',), ('twist',), ('bend', 'twist')])
def test_wedge_paths_preserve_current_native_full_geometry(operations):
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, i] for i in range(8)], 112, lattice=LatticeType.SQUARE,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Source', [h.id for h in state.get_or_404().helices], log=True)
        cluster = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Source')
        for kind in operations:
            params = ({'kind': 'bend', 'curvature_deg_per_bp': .5, 'direction_deg': 15}
                      if kind == 'bend' else {'kind': 'twist', 'total_degrees': 70})
            add_deformation(AddDeformationBody(type=kind, plane_a_bp=7, plane_b_bp=84,
                                               cluster_ids=[cluster.id], params=params))
        hb.transform_cluster(cluster.id, translation=[3, 8, -2],
            rotation=Rotation.from_euler('xyz', [12, 21, -16], degrees=True).as_quat().tolist(),
            pivot=[0, 0, 0], commit=True, log=True)
        source = state.get_or_404()
        before = source.model_dump()
        helix = source.helices[3]
        native = native_full_arrays_for_helix(helix, source)
        corner_rotation = Rotation.from_rotvec(np.array([0., np.pi / 2, 0.])).as_matrix()
        pivot = np.array([5., 7., 16.])
        paths = corner_wedge_paths(source, helix, operation_id='corner-test', outgoing_helix_id='mobile',
                                    center_nm=pivot, rotation=corner_rotation)
        effective = effective_helix_for_geometry(helix, source)
        raw = nucleotide_positions_arrays(effective.model_copy(update={
            'phase_offset': effective.phase_offset + native_full_phase_roll_rad(source)}))
        for index, op in enumerate(paths):
            positions, matrices, tangent = sweep_frames(op, raw['local_bps'], helix.bp_start,
                                                        effective.axis_start.to_array(), [0, 0, 1])
            sites = {**raw, 'axis_points': positions,
                     'radial_hats': np.einsum('nij,nj->ni', matrices, raw['radial_hats']),
                     'axis_tangents': tangent}
            full = place_native_full(sites)
            for field in ('positions', 'base_positions'):
                expected = native[field] if index == 0 else (native[field] - pivot) @ corner_rotation.T + pivot
                np.testing.assert_allclose(full[field], expected, atol=1e-10, rtol=0)
        assert source.model_dump() == before
        assert paths[0].params.preceding_op_ids == [op.id for op in source.deformations]
        outgoing_ids = {h.id: f'mobile-{i}' for i, h in enumerate(source.helices)}
        bundle_paths = corner_bundle_paths(source, source.helices, operation_id='corner-test',
            outgoing_helix_ids=outgoing_ids, center_nm=pivot, rotation=corner_rotation)
        rest = [effective_helix_for_geometry(h, source) for h in source.helices]
        centroid, axis = _bundle_centroid_and_tangent(rest)
        for h, effective in zip(source.helices, rest):
            raw = nucleotide_positions_arrays(effective.model_copy(update={
                'phase_offset': effective.phase_offset + native_full_phase_roll_rad(source)}))
            native = native_full_arrays_for_helix(h, source)
            offset = effective.axis_start.to_array() - centroid
            offset -= np.dot(offset, axis) * axis
            for index, op in enumerate(bundle_paths):
                positions, matrices, tangent = sweep_frames(op, raw['local_bps'], h.bp_start, centroid, axis)
                full = place_native_full({**raw,
                    'axis_points': positions + matrices @ offset,
                    'radial_hats': np.einsum('nij,nj->ni', matrices, raw['radial_hats']),
                    'axis_tangents': tangent})
                expected = native['positions'] if index == 0 else (native['positions'] - pivot) @ corner_rotation.T + pivot
                np.testing.assert_allclose(full['positions'], expected, atol=1e-10, rtol=0)
        assert len(bundle_paths[0].affected_helix_ids) == len(bundle_paths[1].affected_helix_ids) == 8
        assert source.model_dump() == before
