import pytest
from tools.vr_motion.extrude_probe import path_trace, cellset
from tools.vr_motion.presets import PRESETS


def test_profile_comparison_preserves_route_seed_and_timing():
    points=[[0,0,0],[.1,0,0],[.2,.02,0]]
    for name in PRESETS:
        ideal=path_trace(points,[0,0,0,1],name,ideal=True)
        actual=path_trace(points,[0,0,0,1],name)
        assert [s['t'] for s in ideal['samples']] == [s['t'] for s in actual['samples']]
        assert all(b['t']>a['t'] for a,b in zip(actual['samples'],actual['samples'][1:]))
        assert ideal['samples'][-1]['hands']['right']['position'] == pytest.approx(points[-1])
        assert actual == path_trace(points,[0,0,0,1],name)
        assert actual['samples'][-1]['hands']['right']['position'] != points[-1]
    fast=path_trace(points,[0,0,0,1],'steady_fast')
    slow=path_trace(points,[0,0,0,1],'steady_deliberate')
    assert fast['samples'][-1]['t'] < slow['samples'][-1]['t']


def test_cells_are_compared_as_identity_sets():
    assert cellset({'extrude':{'cells':[[0,1],[0,0],[0,1]]}})=={(0,0),(0,1)}
