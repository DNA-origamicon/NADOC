"""Half-space trimming across recorded Corner wedges and repeat plane motion."""
from pathlib import Path

import numpy as np
import pytest

from backend.api.bevel_live import source_axes, plane, retained_sites
from backend.api.part_bevel_commands import BevelCommand, build
from backend.api.feature_recording import record_feature
from backend.api import state
from backend.api.part_proof_commands import execute, dependencies
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history


def test_halfspace_can_keep_disjoint_intervals_and_whole_wedges():
    paths = [dict(helix_id='h', bps=list(range(5)), points=[[0, 0, z] for z in [-2, 0, 2, 0, -2]],
                  tangents=[[0, 0, 1]] * 5, rights=[[1, 0, 0]] * 5),
             dict(helix_id='removed', bps=[7, 8], points=[[0, 0, 3], [0, 0, 4]],
                  tangents=[[0, 0, 1]] * 2, rights=[[1, 0, 0]] * 2)]
    body = BevelCommand(cluster_id='c', position_bp=1, angle_deg=0, direction_deg=0, operation_id='test')
    assert retained_sites(paths, body) == {'h': {0, 1, 3, 4}, 'removed': set()}


def test_corner_test_planar_cuts_preserve_native_history_and_retained_geometry():
    from backend.core.design_geometry import _geometry_for_design
    path = Path(__file__).resolve().parents[1] / 'workspace/corner_test.nadoc'
    if not path.exists():
        pytest.skip('Local user validation design is absent')
    original_bytes = path.read_bytes()
    source = Design.model_validate_json(original_bytes)
    cluster = source.cluster_transforms[0].id
    paths = source_axes(source, cluster)
    old = {(n['helix_id'], n['bp_index'], n['direction']): n for n in _geometry_for_design(source) if n.get('strand_id')}
    for station, angle, end in [(50, 0, 'end'), (140, 25, 'end'), (150, 0, 'start')]:
        body = BevelCommand(cluster_id=cluster, position_bp=station, angle_deg=angle,
                            direction_deg=30, trim_end=end, operation_id=f'bevel-{station}')
        center, normal = plane(paths, body)
        expected = retained_sites(paths, body)
        params = body.model_dump(mode='json', by_alias=True)
        result, _, entry = record_feature(state._DesignSession(design=source.model_copy(deep=True)), 'bevel', 'Bevel validation', params,
                                          lambda d: build(d, params))
        assert result.feature_log[:-1] == source.feature_log
        assert entry.params['_proof_version'] == 2
        actual = {(d.helix_id, bp) for s in result.strands for d in s.domains
                  for bp in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1)}
        assert actual == {(hid, bp) for hid, sites in expected.items() for bp in sites}
        for p in paths:
            for bp, point in zip(p['bps'], p['points']):
                if (p['helix_id'], bp) in actual:
                    assert (1 if end == 'end' else -1) * np.dot(np.array(point) - center, normal) <= 1e-9
        reopened = Design.model_validate_json(result.model_dump_json())
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        for nuc in _geometry_for_design(result):
            if not nuc.get('strand_id'):
                continue
            key = nuc['helix_id'], nuc['bp_index'], nuc['direction']
            if key in old:
                np.testing.assert_allclose(nuc['backbone_position'], old[key]['backbone_position'], atol=1e-9)
    assert path.read_bytes() == original_bytes
