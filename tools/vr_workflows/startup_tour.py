"""Cold browser-route VR startup on a private, read-only copy of a part."""
import argparse
import json
import time
import threading
import uuid
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request
from backend.api import routes_vr as vr, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.models import Design
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.menu_tour import enlarge_mirror

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, default=ROOT/'workspace/24hb_0xT.nadoc')
    parser.add_argument('--output', type=Path, default=ROOT/'.development-artifacts/vr-startup'/uuid.uuid4().hex[:12])
    parser.add_argument('--representations', action='store_true')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if vr._read_state():
        raise RuntimeError('Close the existing VR viewer before running an isolated startup tour')
    args.output.mkdir(parents=True, exist_ok=False)
    doc = '__test_vr_startup_' + uuid.uuid4().hex
    token = set_current_doc(doc)
    request = Request({'type': 'http', 'client': ('127.0.0.1', 12345), 'headers': []})
    launched = False
    live = None
    cleanup_thread = None
    samples = []
    log_offset=vr._LOG_PATH.stat().st_size if vr._LOG_PATH.exists() else 0
    try:
        state.set_design(Design.from_json(args.design.read_text()))
        # Observation adjustment only: place the eventual model in the tracked view.
        command = vr._viewer_command
        with patch.object(vr, '_viewer_command', side_effect=lambda *a: command(*a)+[
            '--place-scene-in-view', 'on', '--scene-view', 'head', '--scene-distance', '1.3']):
            started = time.monotonic()
            result = vr.launch_vr(vr.VRLaunchRequest(scrywrite_live='transactions' if args.representations else 'inspect', mirror_eye='left'), request)
        launched = True
        cleanup_thread=next((t for t in threading.enumerate() if t.name=="nadoc-vr-cleanup"),None)
        (args.output/"owned-state.json").write_text(json.dumps(vr._read_state(),indent=2))
        (args.output/'launch.json').write_text(json.dumps(result, indent=2))
        deadline = started + 300
        while time.monotonic() < deadline:
            if live is None:
                try:
                    live = LiveSession(Bridge(result['scrywrite_socket']), physical=True, allow_transactions=args.representations)
                    enlarge_mirror(live)
                except (OSError, ValueError, RuntimeError):
                    time.sleep(.2)
                    continue
            live.frame()
            status = live.state['startup']
            sample = dict(seconds=time.monotonic()-started, frame=live.state['frame'], **status)
            samples.append(sample)
            if status['phase'] == 'error':
                raise RuntimeError(status['detail'])
            name = 'loading' if status['active'] else 'part-ready'
            if not (args.output/name).exists():
                evidence, _ = live.capture_to(args.output/name, files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'], discard_source=True)
                import numpy as np
                for eye in ('left','right'):
                    pixels=np.fromfile(args.output/name/(eye+'.classes.u8'),dtype=np.uint8)
                    assert int((pixels==(3 if status['active'] else 1)).sum())>100, name+' must have visible pixels in '+eye
            if not status['active']:
                assert any(s['active'] for s in samples), 'No loading frame was observed'
                assert samples[-1]['frame']>samples[0]['frame']+10, 'Frames must advance during loading'
                print(json.dumps(dict(passed=True,first_loading_seconds=samples[0]['seconds'],part_ready_seconds=sample['seconds']),indent=2))
                if args.representations:
                    from tools.vr_workflows.lazy_representation_check import run
                    run(live, vr._read_state(), args.output/'representations', args.validate)
                return
            time.sleep(.25)
        raise TimeoutError('VR startup did not complete')
    finally:
        (args.output/'progress.json').write_text(json.dumps(samples,indent=2))
        if launched:
            vr.stop_vr(request)
            if cleanup_thread is not None:
                cleanup_thread.join(timeout=60)
            # The exporter is cancellation-aware at preparation stage boundaries.
            deadline=time.monotonic()+60
            while vr._read_state() and time.monotonic()<deadline:
                time.sleep(.1)
        if vr._LOG_PATH.exists():
            with vr._LOG_PATH.open("rb") as log:
                log.seek(log_offset)
                (args.output/"viewer.log").write_bytes(log.read())
        if launched and not vr._read_state():
            socket_directory=Path(result["scrywrite_socket"]).parent
            if socket_directory.exists() and not any(socket_directory.iterdir()):
                socket_directory.rmdir()
        state.drop_doc(doc)
        reset_current_doc(token)


if __name__ == '__main__':
    main()
