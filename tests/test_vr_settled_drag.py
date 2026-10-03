"""Safety and measurement boundaries for the long physical-runtime probe."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tools.vr_workflows import settled_drag
from tools.vr_workflows.tour_catalog import arguments, catalog


def test_long_drag_is_registered_with_all_profile_validation():
    tour = next(t for t in catalog()['tours'] if t['id'] == 'move-settled-drag')
    args = arguments(tour, True)
    assert '--settled-drag' in args and '--validate' in args
    assert args[args.index('--target') + 1] == 'cluster'


def test_settled_probe_keeps_trigger_held_and_excludes_warmup(monkeypatch, tmp_path):
    now = [0.0]
    calls = []
    released = []
    state = {'move_grabbing': True, 'hands': [{}, {
        'position': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}]}
    live = SimpleNamespace(state=state, frame=lambda: None,
                           send=lambda op, **kw: calls.append(op),
                           release=lambda: released.append(True))
    monkeypatch.delenv('NADOC_VR_AUDIT_INTERVALS', raising=False)
    monkeypatch.setattr(settled_drag.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(settled_drag.time, 'sleep', lambda dt: now.__setitem__(0, now[0]+dt))

    def reach(session, target, preset, seed, **kwargs):
        now[0] += 1
        state['hands'][1] = {'position': target,
                             'orientation_xyzw': kwargs['target_orientation']}
        return {'preset': preset, 'seed': seed}

    monkeypatch.setattr(settled_drag, 'reach_target', reach)
    settled_drag.run(live, tmp_path, 'steady_fast', np.zeros(3), [0, 0, 0, 1],
                     np.array([.1, 0, 0]), [0, 0, 0, 1])
    result = json.loads((tmp_path/'settled-drag.json').read_text())
    stages = {s['name']: s for s in result['stages']}
    assert result['completed'] and not result['captures_during_measurement']
    assert stages['settled-drag']['seconds'] >= 30
    assert stages['settled-drag']['first_trial'] >= 5
    assert stages['settled-hold']['seconds'] >= 10
    assert calls and set(calls) == {'pose'} and not released
    assert state['hands'][1]['position'] == [.1, 0, 0]


def test_lost_grab_fails_and_releases_inputs(tmp_path):
    released = []
    live = SimpleNamespace(state={'move_grabbing': False}, release=lambda: released.append(True))
    with pytest.raises(AssertionError, match='lost the held trigger'):
        settled_drag.run(live, tmp_path, 'steady_fast', np.zeros(3), [0, 0, 0, 1],
                         np.ones(3)*.1, [0, 0, 0, 1])
    assert released == [True]
    assert not json.loads((tmp_path/'settled-drag.json').read_text())['completed']
