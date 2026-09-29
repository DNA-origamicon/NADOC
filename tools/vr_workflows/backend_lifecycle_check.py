"""Verify an isolated real backend shuts down its native VR child and sidecars."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    from backend.api import routes_vr as vr
    if vr._read_state():
        raise RuntimeError('Close the current viewer before the isolated shutdown check')
    args.output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0))
        port=reserve.getsockname()[1]
    def request(path, body=None):
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/'+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-NADOC-Doc':'__e2e__vr_shutdown'})
        return json.load(urllib.request.urlopen(req,timeout=20))
    session=None
    with tempfile.TemporaryDirectory(prefix='workspace-',dir=args.output) as workspace:
        env={**os.environ,'NADOC_WORKSPACE':str(Path(workspace).resolve()),'NADOC_DISABLE_SESSION_CACHE':'1'}
        with (args.output/'backend.log').open('w') as log:
            backend=subprocess.Popen(['uv','run','uvicorn','backend.api.main:app','--host','127.0.0.1','--port',str(port),'--timeout-graceful-shutdown','2'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    try:
                        request('vr/status')
                        break
                    except OSError:
                        if backend.poll() is not None:
                            raise RuntimeError('Isolated backend exited during startup')
                        time.sleep(.2)
                request('design',{'name':'__e2e__VR shutdown'})
                launched=request('vr/launch',{})
                assert launched['running']
                session=json.loads(vr._STATE_PATH.read_text())
                (args.output/'owned-state.json').write_text(json.dumps(session,indent=2))
                # Terminate only the isolated backend group, not the separately-grouped viewer.
                import signal
                os.killpg(backend.pid, signal.SIGTERM)
                backend.wait(timeout=15)
                deadline=time.monotonic()+5
                while Path('/proc/'+str(session['pid'])).exists() and time.monotonic()<deadline:
                    time.sleep(.05)
                assert not Path('/proc/'+str(session['pid'])).exists(),'Viewer survived backend shutdown'
                assert vr._read_state() is None
                remaining=[v for k,v in session.items() if k.endswith('_path') and isinstance(v,str) and Path(v).exists()]
                assert not remaining,remaining
                (args.output/'result.json').write_text(json.dumps({'passed':True,'viewerExited':True,'sidecarsRemoved':True},indent=2))
            finally:
                if backend.poll() is None:
                    import signal
                    os.killpg(backend.pid,signal.SIGTERM)
                    backend.wait(timeout=15)
                if session and vr._read_state() and vr._read_state()['pid']==session['pid']:
                    # Failure cleanup is restricted to this check's child.
                    import signal
                    os.killpg(session['pid'],signal.SIGTERM)


if __name__=='__main__':
    main()
