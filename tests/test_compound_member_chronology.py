"""A complete Move/Rotate evaluates member transport only after every owner pose."""
from copy import deepcopy

import numpy as np
import pytest

from backend.api import part_proof_commands as commands
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from tests.test_part_member_motion_order import M, _rigid
from tests.test_part_transform_constraint_history import _create_owner
from tests.test_part_transform_preview import source_recipe, snapshot
from tools.member_motion_native_example import verify


def recipe():
    source = source_recipe('nucleotide-transform', extra=True, suffix=False)
    for index, helix in enumerate(source.helices):
        source = _create_owner(source, f'arm-{index}', [helix.id])
    poses = [{'cluster_id': f'arm-{index}', 'parent_cluster_id': None,
              'overhang_duplex_driver_id': None, **deepcopy(M)} for index in range(2)]
    params = {'_proof_version': 1, 'primary_cluster_id': 'arm-0',
        'selected_cluster_ids': ['arm-0', 'arm-1'], 'poses': poses,
        'authoring': {'mode': 'free', 'joint_id': None, 'fixed_cluster_ids': [], 'pivot_id': 'centroid'},
        'primary_authored_fields': {}, 'legacy_source': None}
    return source, params


@pytest.mark.parametrize('reverse', [False, True])
def test_complete_move_carries_posed_insert_when_both_ends_move_together(reverse):
    source, params = recipe()
    captured = source.model_dump_json()
    if reverse:
        params['poses'].reverse()
    result = snapshot(source, 'placement-poses', params, 'move-both-arms')
    before = build_atomistic_model(source, fast_bridges=True)
    after = build_atomistic_model(result, fast_bridges=True)
    assert any(atom.extra_base_k is not None for atom in before.atoms)
    assert after.bonds == before.bonds
    for old, new in zip(before.atoms, after.atoms, strict=True):
        np.testing.assert_allclose([new.x, new.y, new.z], _rigid([old.x, old.y, old.z], M), atol=1e-10, rtol=0)
    for old, new in zip(_geometry_for_design(source), _geometry_for_design(result), strict=True):
        for field in ('base_position', 'backbone_position', 'slab_position'):
            np.testing.assert_allclose(new[field], _rigid(old[field], M), atol=1e-10, rtol=0)
    verify(result)
    assert source.model_dump_json() == captured


@pytest.mark.parametrize('mode', ['missing-companion', 'different-motion'])
def test_complete_move_still_refuses_differential_insert_motion_atomically(mode):
    source, params = recipe()
    captured = source.model_dump_json()
    if mode == 'missing-companion':
        params['selected_cluster_ids'] = ['arm-0']
        params['poses'].pop()
    else:
        params['poses'][1]['translation'][0] += 1
    with pytest.raises(ValueError, match='Move both ends'):
        commands.execute('placement-poses', source, params)
    assert source.model_dump_json() == captured
