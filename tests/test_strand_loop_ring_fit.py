"""Regression against the demonstrated and explicitly selected loop candidate."""
import gzip
import json
from pathlib import Path
import numpy as np
import pytest
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from experiments.loop_orientation_comparison import build_input

CASES=json.loads(gzip.decompress((Path(__file__).parent/'data/loop_ring_priority_cases.json.gz').read_bytes()))['cases']

@pytest.mark.parametrize('case',CASES)
def test_approved_ring_priority_atoms_and_full_pose(tmp_path,case):
    (tmp_path/'inputs').mkdir()
    _,_,design,proof=build_input(tmp_path,case['length'],case['bp'],case['direction'])
    assert proof['status']=='verified'
    model=build_atomistic_model(design,strand_loop_display=True)
    atoms=[[a.x,a.y,a.z] for a in model.atoms if a.copy_k]
    np.testing.assert_allclose(atoms,case['atoms'],atol=1e-12,rtol=0)
    records=[r for r in _geometry_for_design(design) if r.get('loop_order',0)>0]
    np.testing.assert_allclose([r['backbone_position'] for r in records],case['beads'],atol=1e-12,rtol=0)
    # q and -q represent the same rotation.
    from scipy.spatial.transform import Rotation
    np.testing.assert_allclose(Rotation.from_quat([r['slab_quaternion'] for r in records]).as_matrix(),Rotation.from_quat(case['quaternions']).as_matrix(),atol=1e-12,rtol=0)
    assert all(r['placement_source']=='strand-loop-ellipse-v4-ring-priority' for r in records)


def test_temporary_atomistic_design_view_is_not_revalidated():
    from unittest.mock import patch
    from backend.core.models import Design
    from tests.test_strand_loop_atoms import loop_design
    from backend.core.strand_loop_ring_fit import _POSE_CACHE
    design, _, _ = loop_design(True, 6)
    transient = design.model_copy(update={'cluster_transforms': []})
    _POSE_CACHE.clear()
    with patch.object(Design, 'model_validate_json', side_effect=AssertionError('Temporary view must not be revalidated')):
        records = _geometry_for_design(transient)
    assert any(r.get('placement_source') == 'strand-loop-ellipse-v4-ring-priority' for r in records)
