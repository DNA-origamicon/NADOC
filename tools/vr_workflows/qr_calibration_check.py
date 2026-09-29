"""Exercise the real Share-tab camera toggle. Does not fake a physical QR lock."""
import json
import time
import numpy as np
from PIL import Image
from tools.vr_workflows.menu_tour import click


def run(live, catalog, output, preset):
    del catalog
    trials = []
    click(live, 0, 'tab:share', preset, trials)
    before = live.state['presentation']['model_to_tracking_rows']
    for hand in (0, 1):
        if live.state['sidebars'][hand]['open']:
            live.button('menu', hand=hand)
    baseline, _ = live.capture_to(output / 'before', files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
    live.button('menu', hand=0)
    try:
        click(live, 0, 'qr-calibrate', preset, trials)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            live.frame()
            state = live.state['qr_calibration']
            if state['preview_width'] > 0 and state['edge_pixels'] > 100:
                break
            if not state['running']:
                raise RuntimeError(state['status'])
            time.sleep(.1)
        else:
            raise RuntimeError('No live camera preview')
        live.button('menu', hand=0)
        evidence, _ = live.capture_to(output / 'camera', files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
        changed = []
        for eye in ('left', 'right'):
            a = np.asarray(Image.open(output / 'before' / (eye + '.png')).convert('RGB'), dtype=float)
            b = np.asarray(Image.open(output / 'camera' / (eye + '.png')).convert('RGB'), dtype=float)
            changed.append(int((np.abs(a-b).max(axis=2) > 12).sum()))
        assert min(changed) > 200, 'Camera preview did not produce visible stereo pixels'
        if not state['registered']:
            assert live.state['presentation']['model_to_tracking_rows'] == before, 'No QR lock must not move the model'
        live.button('menu', hand=0)
        click(live, 0, 'qr-calibrate', preset, trials)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            live.frame()
            if not live.state['qr_calibration']['running']:
                break
            time.sleep(.1)
        assert not live.state['qr_calibration']['running'], 'Cancel left camera worker alive'
        report = dict(passed=True, camera=state, stereo_changed_pixels=changed, trials=trials,
                      physical_qr_registration_verified=False, note='Real camera preview/cancel only; printed-target registration requires on-site testing.')
        (output / 'qr-check.json').write_text(json.dumps(report, indent=2))
        return report
    finally:
        if live.state.get('qr_calibration', {}).get('running'):
            click(live, 0, 'qr-calibrate', preset, trials)
