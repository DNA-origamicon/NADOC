"""The tour must reject an erased S, not merely accept a fitted point count."""
import math
import json

import numpy as np
import pytest

from tools.vr_motion.metrics import rotate
from tools.vr_motion.sweep_calibration import curve
from tools.vr_workflows.sweep_probe import s_shape_report
from tools.vr_workflows.sweep_probe import wait_for_headset, green_stroke_pixels


@pytest.mark.parametrize('upright', [False, True])
def test_s_shape_requires_opposite_lobes_in_the_recorded_drawing_frame(upright):
    q = [math.sin(math.pi/4), 0, 0, math.cos(math.pi/4)] if upright else [0, 0, 0, 1]
    origin = np.array([.4, 1.1, -.8])
    points = [origin+rotate(q, curve(u, 's-curve')) for u in np.linspace(0, 1, 13)]
    assert s_shape_report(points, q)['passed']


@pytest.mark.parametrize('shape', ['line', 'arc'])
def test_straight_or_single_bend_does_not_pass_as_s_shape(shape):
    points = [curve(u, shape) for u in np.linspace(0, 1, 13)]
    assert not s_shape_report(points, [0, 0, 0, 1])['passed']


def test_s_shape_rejects_smoothing_that_erases_the_second_lobe():
    points = np.array([curve(u, 's-curve') for u in np.linspace(0, 1, 13)])
    points[:, 0] = np.maximum(points[:, 0], 0)
    assert not s_shape_report(points, [0, 0, 0, 1])['passed']


@pytest.mark.parametrize('focused,connected,flags', [(False, True, 15), (True, False, 15), (True, True, 3)])
def test_unready_headset_retains_failure_before_drawing(tmp_path, focused, connected, flags):
    class Bridge:
        def call(self, *args):
            return {'focused': focused, 'runtime_connected': connected, 'view_state_flags': flags, 'frame': 42}
    with pytest.raises(RuntimeError, match='wear the headset'):
        wait_for_headset(Bridge(), tmp_path, timeout=-1)
    report = json.loads((tmp_path/'tour-report.json').read_text())
    assert not report['passed'] and not report['drawing_started']
    assert json.loads((tmp_path/'failure-state.json').read_text())['frame'] == 42


def test_ready_headset_preserves_observation(tmp_path):
    class Bridge:
        def call(self, *args):
            return {'focused': True, 'runtime_connected': True, 'view_state_flags': 15, 'frame': 43}
    wait_for_headset(Bridge(), tmp_path, stable_frames=1)
    assert json.loads((tmp_path/'headset-ready.json').read_text())['frame'] == 43
    assert not (tmp_path/'tour-report.json').exists()


def test_headset_readiness_waits_through_startup_and_transient_focus(tmp_path, monkeypatch):
    rows = iter([(True, True), (False, True), (False, False), (False, True), (False, True)])
    class Bridge:
        frame = 0
        def call(self, *args):
            self.frame += 1
            loading, focused = next(rows)
            return {'frame': self.frame, 'startup': {'active': loading},
                    'focused': focused, 'runtime_connected': True, 'view_state_flags': 15}
    monkeypatch.setattr('tools.vr_workflows.sweep_probe.time.sleep', lambda _: None)
    wait_for_headset(Bridge(), tmp_path, stable_frames=2)
    assert json.loads((tmp_path/'headset-ready.json').read_text())['frame'] == 5


def test_dashboard_dismissal_does_not_substitute_for_tracked_focus(tmp_path):
    from unittest.mock import Mock
    class Bridge:
        def call(self, *args):
            return {'focused': False, 'runtime_connected': True, 'view_state_flags': 15, 'frame': 1}
    dismiss = Mock(return_value={'returncode': 0})
    with pytest.raises(RuntimeError, match='tracked headset focus'):
        wait_for_headset(Bridge(), tmp_path, timeout=-1, dismiss=dismiss)
    dismiss.assert_called_once_with(tmp_path)
    assert not (tmp_path/'headset-ready.json').exists()


def test_dashboard_uses_only_stock_hide_command(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from tools.vr_workflows.sweep_view import dismiss_dashboard
    command = tmp_path/'vrcmd'
    monkeypatch.setattr('tools.vr_capture.launch_compositor.process_ids', lambda _: [123])
    monkeypatch.setattr('scripts.vr_atomistic_diagnostics._find_vrcmd', lambda _: command)
    run = Mock(return_value=Mock(returncode=0, stdout='HideDashboard', stderr=''))
    monkeypatch.setattr('tools.vr_workflows.sweep_view.subprocess.run', run)
    assert dismiss_dashboard(tmp_path)['returncode'] == 0
    assert run.call_args.args[0] == [str(command), '--hidedashboard']
    assert run.call_args.kwargs['timeout'] == 5
    assert not json.loads((tmp_path/'dashboard-dismissal.json').read_text())['settings_changed']


def test_dashboard_teardown_never_starts_a_stopped_runtime(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from tools.vr_workflows.sweep_view import dismiss_dashboard
    monkeypatch.setattr('tools.vr_capture.launch_compositor.process_ids', lambda _: [])
    run = Mock()
    monkeypatch.setattr('tools.vr_workflows.sweep_view.subprocess.run', run)
    assert 'skipped' in dismiss_dashboard(tmp_path)
    run.assert_not_called()


@pytest.mark.parametrize('held', [False, True])
def test_capture_recovery_retains_untracked_frame_and_never_retries_held_motion(tmp_path, held):
    from unittest.mock import Mock
    from tools.vr_workflows.sweep_view import capture_tracked
    class Live:
        count = 0
        def capture_to(self, directory, **kwargs):
            self.count += 1
            directory.mkdir()
            (directory/'original').write_text(str(self.count))
            return {'state': {'view_state_flags': 3 if self.count == 1 else 15,
                              'hands': [{'trigger': held, 'grip': False}]}}, None
    live = Live(); wait = Mock(); destination = tmp_path/'review'
    if held:
        with pytest.raises(AssertionError, match='held gesture'):
            capture_tracked(live, destination, wait)
        assert live.count == 1
        wait.assert_not_called()
    else:
        assert capture_tracked(live, destination, wait)['state']['view_state_flags'] == 15
        assert (tmp_path/'review-untracked'/'original').read_text() == '1'
        assert (destination/'original').read_text() == '2'
        wait.assert_called_once_with(tmp_path/'review-untracked')


@pytest.mark.parametrize('outcome', [0, 1, 'interrupted'])
def test_tour_dismisses_dashboard_and_removes_workspace_on_exit(tmp_path, monkeypatch, outcome):
    from unittest.mock import Mock
    from tools.vr_workflows import sweep_tour
    output = tmp_path/'evidence'
    monkeypatch.setattr('sys.argv', ['sweep_tour', '--output', str(output)])
    monkeypatch.setattr('backend.api.routes_vr_tours._viewer_active', lambda: False)
    monkeypatch.setattr('backend.api.routes_vr._ensure_viewer_built', lambda: None)
    workspaces = []
    def run(command, **kwargs):
        workspaces.append(kwargs['env']['SCRYWRITE_TEST_WORKSPACE'])
        if outcome == 'interrupted':
            raise KeyboardInterrupt()
        return Mock(returncode=outcome)
    monkeypatch.setattr(sweep_tour.subprocess, 'run', run)
    dismiss = Mock()
    monkeypatch.setattr('tools.vr_workflows.sweep_view.dismiss_dashboard', dismiss)
    if outcome == 'interrupted':
        with pytest.raises(KeyboardInterrupt): sweep_tour.main()
    elif outcome:
        with pytest.raises(SystemExit): sweep_tour.main()
    else:
        sweep_tour.main()
    from pathlib import Path
    assert workspaces and all(not Path(p).exists() for p in workspaces)
    dismiss.assert_called_once_with(output/'teardown')


@pytest.mark.parametrize('angles', [[0, 0, 0], [135, -35, 20], [-175, 60, -15]])
def test_sidebar_placement_faces_translated_rotated_head(angles):
    from scipy.spatial.transform import Rotation
    from tools.vr_workflows.sweep_view import sidebar_wrist
    eye = Rotation.from_euler('yxz', angles, degrees=True)
    head = np.array([2.7, .4, -3.2])
    wrist = Rotation.from_euler('xyz', [12, 39, -8], degrees=True)
    tilt = Rotation.from_euler('x', -27, degrees=True)
    offset = np.array([.02, -.03, -.4])
    start = np.array([1., 2., 3.])
    position, orientation = sidebar_wrist(head, eye.as_quat(), start, wrist.as_quat(),
        start+wrist.apply(offset), (wrist*tilt).as_quat())
    actual = Rotation.from_quat(orientation)
    assert np.allclose(position+actual.apply(offset), head+eye.apply([.27, 0, -.65]))
    assert np.allclose((actual*tilt).as_matrix(), eye.as_matrix())


def test_menu_reopens_directly_at_calibrated_distance(tmp_path):
    from scipy.spatial.transform import Rotation
    from tools.vr_workflows.sweep_view import open_sidebar_in_view
    class Live:
        def __init__(self):
            self.head = np.array([1., 2., 3.]); self.eye = Rotation.identity()
            self.state = {'sidebars': [{}, {'open': False}], 'controls': []}
            self.opens = 0
        def capture_to(self, *args, **kwargs):
            return {'state': {'view_state_flags': 15}, 'eyes': [
                {'position': self.head.tolist(), 'orientation_xyzw': self.eye.as_quat().tolist()}]*2}, None
        def send(self, operation, **kwargs):
            assert operation == 'pose'
            self.position = np.array(kwargs['position']); self.wrist = Rotation.from_quat(kwargs['orientation'])
        def frame(self): pass
        def button(self, *args, **kwargs):
            panel = self.state['sidebars'][1]; panel['open'] = not panel['open']
            if panel['open']:
                self.opens += 1
                panel['position'] = (self.position+self.wrist.apply([0, 0, -.4])).tolist()
                orientation = self.wrist*Rotation.from_euler('x', -30, degrees=True)
                self.state['controls'] = [{'sidebar': 'right',
                    'hit_half_right': orientation.apply([.1,0,0]),
                    'hit_half_up': orientation.apply([0,.1,0])}]
    live = Live(); calibration = {}
    open_sidebar_in_view(live, tmp_path/'first', calibration)
    assert live.opens == 2
    live.state['sidebars'][1]['open'] = False
    live.head += [2, -.5, 1]; live.eye = Rotation.from_euler('y', 115, degrees=True)
    open_sidebar_in_view(live, tmp_path/'second', calibration)
    assert live.opens == 3  # no provisional opening before the final pose
    assert np.allclose(live.state['sidebars'][1]['position'], live.head+live.eye.apply([.27,0,-.65]))


@pytest.mark.parametrize('condition', ['visible', 'blank', 'behind', 'offscreen', 'one-eye'])
def test_stroke_requires_visible_pixels_in_both_eyes(tmp_path, condition):
    from PIL import Image
    eyes = [dict(eye=name, width=100, height=100, position=[0, 0, 0],
                 orientation_xyzw=[0, 0, 0, 1],
                 fov_left_right_up_down=[-math.pi/4, math.pi/4, math.pi/4, -math.pi/4])
            for name in ('left', 'right')]
    for eye in eyes:
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        if condition != 'blank' and not (condition == 'one-eye' and eye['eye'] == 'right'):
            image[45:55, 45:55] = [30, 240, 40]
        Image.fromarray(image).save(tmp_path/(eye['eye']+'.png'))
    point = [0, 0, 1] if condition == 'behind' else [4, 0, -1] if condition == 'offscreen' else [0, 0, -1]
    evidence = {'eyes': eyes}
    if condition == 'visible':
        assert set(green_stroke_pixels(tmp_path, evidence, [point]*5)) == {'left', 'right'}
    else:
        with pytest.raises(AssertionError, match='Green Sweep line missing'):
            green_stroke_pixels(tmp_path, evidence, [point]*5)
    from tools.vr_workflows.sweep_view import check_draft_pixels
    evidence['state'] = {'sweep': {'points_world': [point, point]}}
    if condition == 'visible':
        assert check_draft_pixels(tmp_path, evidence)['passed']
    else:
        with pytest.raises(AssertionError, match='Sweep knots not visible'):
            check_draft_pixels(tmp_path, evidence)
