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


@pytest.mark.parametrize('kind', ['straight', 'bend', 'twist', 'sweep', 'partial', 'posed', 'extension', 'outside'])
def test_general_geometry_reuses_array_slabs_with_exact_post_pose_results(kind, monkeypatch):
    from backend.core import native_slab_placement as slabs
    from backend.core.models import NucleotideTransform, StrandExtension
    from tests.test_native_compact_geometry import _design

    design = _design(kind if kind in {'bend', 'twist', 'sweep', 'partial'} else 'straight')
    if kind == 'posed':
        design.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id=design.helices[0].id,
            bp_index=9, copy_k=1, direction=Direction.FORWARD, translation=[1, -3, 2],
            rotation=Rotation.from_euler('xyz', [.3, -.5, .8]).as_quat().tolist())]
    elif kind == 'extension':
        design.extensions = [StrandExtension(strand_id=design.strands[0].id, end='five_prime', sequence='AAA')]
    elif kind == 'outside':
        design.strands[0].domains[0].start_bp = -3
    pending = []
    original = slabs.attach_native_slab_poses
    def attach(records):
        pending.extend(records)
        return original(records)
    monkeypatch.setattr(slabs, 'attach_native_slab_poses', attach)
    actual = _geometry_for_design(design)
    expected = deepcopy(actual)
    # The previous general producer attached every slab after every residue
    # pose. Re-evaluate that authority from the final bead/base records.
    for record in expected:
        record.pop('slab_position', None)
        record.pop('slab_quaternion', None)
    original(expected)
    import orjson
    assert orjson.dumps(actual) == orjson.dumps(expected)
    assert len(pending) == (1 if kind == 'posed' else 3 if kind == 'extension' else 0)


def test_array_slab_failure_preserves_actual_residue_diagnostic(monkeypatch):
    from backend.core import design_geometry as geometry
    from backend.core.native_full_placement import NativePlacementError
    design = make_minimal_design()
    original = geometry.native_full_arrays_for_helix
    def corrupted(*args, **kwargs):
        arrays = original(*args, **kwargs)
        arrays['base_positions'][0] += 100
        return arrays
    monkeypatch.setattr(geometry, 'native_full_arrays_for_helix', corrupted)
    with pytest.raises(NativePlacementError, match='registration') as caught:
        geometry._geometry_for_design(design)
    assert caught.value.details['identity']['helix_id'] == design.helices[0].id
    assert caught.value.details['identity']['bp_index'] == 0
