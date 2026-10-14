"""Real Tools-menu stereo recording, with open/closed menus and grip motion."""
import json
from pathlib import Path
import subprocess
import time
import zlib

from tools.vr_motion.metrics import rotate
from tools.vr_workflows.menu_tour import click
from tools.vr_workflows.profile_input import reach_target


def run(live, catalog, output, preset):
    del catalog
    trials, clips = [], []
    if live.state['sidebars'][0]['open']:
        live.button('menu', hand=0)
    anchor, _ = live.capture_to(output / 'before', files=['left.png', 'right.png', 'evidence.json'], discard_source=True)
    eye = anchor['eyes'][0]
    orientation = eye['orientation_xyzw']
    head = live.state['head_position']
    def position(offset):
        return [a + b for a, b in zip(head, rotate(orientation, offset))]
    wrist = position([.3, -.1, -.4])
    home, away = position([-.5, -.35, -.4]), position([-.1, -.35, -.4])
    try:
        for opened in (True, False):
            live.send('pose', hand=1, position=wrist, orientation=orientation)
            live.frame()
            if not live.state['sidebars'][1]['open']:
                live.button('menu', hand=1)
            click(live, 1, 'tab:tools', preset, trials)
            # The eighth Tools row is visible on the first page.
            click(live, 1, 'vr-record', preset, trials)
            assert live.state['recording']['busy']
            assert not next(c for c in live.state['controls'] if c['id'] == 'vr-record')['enabled']
            if not opened:
                live.button('menu', hand=1)
            live.send('pose', hand=0, position=home, orientation=orientation)
            live.frame()
            deadline = time.monotonic() + 4
            while not live.state['recording']['recording']:
                assert time.monotonic() < deadline, 'Countdown did not start recording'
                time.sleep(.05)
                live.frame()
            live.send('button', hand=0, button='grip', pressed=True)
            live.frame()
            for destination in (away, home):
                trials.append(reach_target(live, destination, preset, 9230 + len(trials),
                    target_position=destination, target_orientation=orientation, hand=0))
            live.send('button', hand=0, button='grip', pressed=False)
            live.frame()
            deadline = time.monotonic() + 240
            while live.state['recording']['busy']:
                assert time.monotonic() < deadline, 'Recording/export did not finish'
                time.sleep(.25)
                live.frame()
            status = live.state['recording']
            assert not status['error'], status
            directory = Path(status['directory'])
            timeline = json.loads((directory / 'timeline.json').read_text())
            assert timeline['saved_frames'] == len(timeline['frames']) > 0
            assert all(f['menus_open'] == [False, opened] for f in timeline['frames'])
            assert timeline['requested_frames'] == timeline['saved_frames'] + timeline['dropped_pairs']
            first = timeline['frames'][0]
            raw = zlib.decompress((directory / f"{first['frame']}.rgbz").read_bytes())
            half = timeline['width'] * timeline['height'] * 3
            assert len(raw) == half * 2 and raw[:half] != raw[half:], 'Missing distinct stereo eye content'
            videos = {}
            for name in ('left', 'right'):
                probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(directory / (name + '.mp4'))]))['streams'][0]
                assert 4.8 <= float(probe['duration']) <= 5.1, probe
                assert (probe['width'], probe['height']) == (timeline['width'], timeline['height'])
                videos[name] = {key: probe[key] for key in ('width', 'height', 'duration', 'nb_frames')}
            clip = dict(directory=str(directory), menu_open=opened, captured_hz=timeline['capture_rate_hz'],
                        maximum_gap_ms=timeline['maximum_frame_gap_seconds'] * 1000,
                        skipped=timeline['dropped_pairs'], videos=videos)
            clips.append(clip)
            (output / 'recordings.json').write_text(json.dumps(clips, indent=2))
        return dict(passed=True, clips=clips, trials=trials, physical_scanout_verified=False)
    finally:
        live.release()
        (output / 'trials.json').write_text(json.dumps(trials, indent=2))
