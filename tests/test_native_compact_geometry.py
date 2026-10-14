"""Array emission retains every native compact value and authority check."""

from copy import deepcopy

import numpy as np
import orjson
import pytest
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import (
    _compact_geometry_for_design, native_full_arrays_for_helix,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    BendParams, ClusterRigidTransform, DeformationOp, Direction, LoopSkip,
    NucleotideTransform, StrandExtension, TwistParams,
)
from backend.core.native_compact_geometry import native_compact_geometry, geometry_arrays_to_lists
from backend.core.native_full_placement import NativePlacementError
from backend.core.native_geometry_binary import pack_geometry_binary, unpack_geometry_binary
from backend.core.native_slab_placement import native_slab_poses_for_arrays
from backend.core.sweep_model import SweepParams


def _design(kind):
    design = make_bundle_design([(0, 0), (1, 0)], 43)
    for h in design.helices:
        h.loop_skips = [LoopSkip(bp_index=9, delta=1), LoopSkip(bp_index=18, delta=-1)]
    if kind in ('bend', 'twist'):
        design.deformations = [DeformationOp(type=kind, plane_a_bp=3, plane_b_bp=39,
            params=BendParams(curvature_deg_per_bp=1.7, direction_deg=31) if kind == 'bend'
            else TwistParams(total_degrees=91))]
    if kind == 'sweep':
        t = np.linspace(0, 1.1, 43)
        points = np.column_stack([15 * (1 - np.cos(t)), np.zeros(43), 15 * np.sin(t)])
        design.deformations = [DeformationOp(type='sweep', plane_a_bp=0, plane_b_bp=42,
            params=SweepParams(points_nm=[points[0].tolist(), points[-1].tolist()],
                origin_nm=(0, 0, 0), initial_rotation=np.eye(3).ravel().tolist(),
                steps=42, path_length_nm=16.5, bp_positions_nm=points.tolist(),
                bp_frames=Rotation.from_euler('y', t[:, None]).as_matrix().reshape(-1, 9).tolist()))]
    design.cluster_transforms = [ClusterRigidTransform(id='move', helix_ids=[h.id for h in design.helices],
        translation=[3, -5, 7], rotation=Rotation.from_euler('xyz', [.2, -.4, .7]).as_quat().tolist())]
    if kind == 'partial':
        design.strands = design.strands[:-1]
        strand = design.strands[0]
        first = strand.domains[0]
        strand.domains = [first.model_copy(update={'end_bp': 12}), first.model_copy(update={'start_bp': 23})]
        # Later domains/strands own a reused slot, just as the record dictionary.
        duplicate = strand.model_copy(deep=True, update={'id': 'overlap'})
        duplicate.domains = [first.model_copy(update={'start_bp': 7, 'end_bp': 10})]
        design.strands.append(duplicate)
    return design


@pytest.mark.parametrize('kind', ['straight', 'bend', 'twist', 'sweep', 'partial'])
def test_compact_arrays_match_every_general_pipeline_value_and_binary64_bit(kind):
    design = _design(kind)
    expected = _compact_geometry_for_design(design)
    arrays = native_compact_geometry(design)
    assert arrays is not None
    actual = geometry_arrays_to_lists(arrays)
    assert orjson.dumps(actual) == orjson.dumps(expected)
    assert orjson.dumps(unpack_geometry_binary(pack_geometry_binary(arrays))) == orjson.dumps(expected)
    for hid, directions in actual.items():
        for direction, bucket in directions.items():
            for field in ('bb', 'bs', 'bn', 'at', 'sp', 'sq'):
                assert np.asarray(bucket[field]).tobytes() == np.asarray(expected[hid][direction][field]).tobytes()
            assert bucket['bp'].count(9) == 2 if 9 in bucket['bp'] else True
            assert 18 not in bucket['bp']


@pytest.mark.parametrize('unsupported', ['extension', 'nucleotide_transform', 'outside_helix'])
def test_unsupported_topology_explicitly_retains_general_pipeline(unsupported):
    design = _design('straight')
    if unsupported == 'extension':
        design.extensions = [StrandExtension(strand_id=design.strands[0].id, end='five_prime', sequence='AAA')]
    elif unsupported == 'nucleotide_transform':
        design.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id=design.helices[0].id,
            bp_index=0, direction=Direction.FORWARD, translation=[1, 0, 0])]
    else:
        design.strands[0].domains[0].start_bp = -2
    assert native_compact_geometry(design) is None
    assert _compact_geometry_for_design(design)


@pytest.mark.parametrize('field,value,message', [
    ('base_positions', [100, 0, 0], 'registration'),
    ('axis_tangents', [0, 0, 0], 'zero axis tangent'),
    ('base_normals', [0, 0, 0], 'degenerate base frame'),
    ('positions', [float('nan'), 0, 0], 'Invalid backbone_position'),
])
def test_array_slab_authority_rejects_corrupted_placements(field, value, message):
    design = _design('straight')
    arrays = deepcopy(native_full_arrays_for_helix(design.helices[0], design))
    arrays[field][3] = value
    with pytest.raises(NativePlacementError, match=message):
        native_slab_poses_for_arrays(arrays)
