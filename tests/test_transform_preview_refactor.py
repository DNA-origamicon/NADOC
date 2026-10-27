"""Independent output oracles for preview hot-path refactors."""
from copy import deepcopy
from random import Random

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.deformation import _segments_for_helix
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Domain, Strand, StrandType, Direction
from backend.core.native_slab_placement import (
    _native_registration, _native_slab_array_poses, attach_native_slab_poses,
)
from tests.conftest import make_minimal_design


def test_axis_sweep_matches_exhaustive_interval_owners():
    rng = Random(126)
    design = make_minimal_design()
    helix = design.helices[0]
    for _ in range(40):
        candidates = []
        for i in range(rng.randrange(1, 30)):
            strand = Strand(id=f"s{i % 7}", strand_type=rng.choice(list(StrandType)))
            domain = Domain(helix_id=helix.id, start_bp=rng.randrange(-10, 40),
                            end_bp=rng.randrange(-10, 40), direction=Direction.FORWARD)
            candidates.append((strand, i % 3, domain))
        edges = sorted({bp for _, _, d in candidates
                        for bp in (min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1)})
        expected = []
        for lo, end in zip(edges, edges[1:]):
            owners = [(s, di, d) for s, di, d in candidates
                      if min(d.start_bp, d.end_bp) <= lo and max(d.start_bp, d.end_bp) >= end - 1]
            owners.sort(key=lambda row: (row[0].strand_type != StrandType.SCAFFOLD, row[0].id, row[1]))
            if owners:
                s, di, d = owners[0]
                expected.append(dict(strand_id=s.id, domain_index=di, ovhg_id=d.overhang_id,
                    bp_lo=lo, bp_hi=end - 1,
                    domain_ids=[dict(strand_id=s.id, domain_index=di) for s, di, _ in owners]))
        assert _segments_for_helix(design, helix, candidates) == expected


@pytest.mark.parametrize("rotation", [0, 31, 137])
def test_dense_slab_attachment_is_bit_exact_with_previous_batch_layout(rotation):
    from backend.core.models import ClusterRigidTransform
    design = make_minimal_design()
    design.cluster_transforms = [ClusterRigidTransform(helix_ids=[h.id for h in design.helices],
        translation=[5.5, -17, 3], pivot=[1, 2, 3],
        rotation=Rotation.from_euler('xyz', [rotation, 7, -21], degrees=True).as_quat().tolist())]
    records = _geometry_for_design(design)
    original = deepcopy(records)
    arrays = [np.asarray([r[field] for r in records], dtype=float)
              for field in ('backbone_position', 'base_position', 'base_normal', 'axis_tangent')]
    slab, base = map(np.asarray, zip(*(_native_registration()[r['direction']] for r in records)))
    centers, frames = _native_slab_array_poses(*arrays, slab, base)
    # The original producer materialized per-record views, then rebuilt frames.
    frames = np.asarray([frame for frame in frames])
    quaternions = Rotation.from_matrix(frames).as_quat()
    attach_native_slab_poses(records)
    assert np.asarray([r['slab_position'] for r in records]).tobytes() == centers.tobytes()
    assert np.asarray([r['slab_quaternion'] for r in records]).tobytes() == quaternions.tobytes()
    assert records == original
