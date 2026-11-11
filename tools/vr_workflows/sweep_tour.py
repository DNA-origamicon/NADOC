"""Isolated S-shaped Sweep tour: Free Draw, point edits and desktop history.

Demo and validation use all four controller profiles; Demo adds review holds.
The browser, native viewer and temporary six-helix part belong to
this run. Only evidence remains after its workspace is removed.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid
import hashlib

from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active():
        raise RuntimeError('Close the active viewer before starting an isolated Sweep tour.')
    # Build preparation must not consume the measured browser launch budget.
    from backend.api.routes_vr import _ensure_viewer_built
    _ensure_viewer_built()
    output = (args.output or ROOT/'.development-artifacts/vr-sweep-tour'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nadoc-sweep-tour-') as workspace:
        with socket.socket() as backend, socket.socket() as frontend:
            backend.bind(('127.0.0.1', 0))
            frontend.bind(('127.0.0.1', 0))
            backend_port = str(backend.getsockname()[1])
            frontend_port = str(frontend.getsockname()[1])
        env = {**os.environ,
            'SCRYWRITE_BACKEND_PORT': backend_port,
            'SCRYWRITE_FRONTEND_PORT': frontend_port,
            'SCRYWRITE_TEST_WORKSPACE': workspace,
            'NADOC_E2E_FRONTEND_PORT': frontend_port,
            'NADOC_E2E_API_BASE': 'http://127.0.0.1:'+backend_port,
            'NADOC_WORKSPACE': workspace,
            'NADOC_PHYSICAL_VR_TEST': '1',
            'NADOC_VR_SWEEP_EVIDENCE': str(output/'sweep-evidence'),
            'NADOC_VR_SWEEP_VALIDATE': '1' if args.validate else '0',
            'NADOC_VR_DEMO': '0' if args.validate else '1',
            'NADOC_VR_DEMO_HOLD': os.environ.get('NADOC_VR_DEMO_HOLD', '3')}
        command = ['npx', 'playwright', 'test', '--config', 'playwright.vr-sweep.config.js',
            'vr_sweep.spec.js', '--workers=1', '--output', str(output/'playwright'), '--headed']
        try:
            result = subprocess.run(command, cwd=ROOT/'frontend', env=env)
        finally:
            # SteamVR can reopen its dashboard when the owned viewer exits.
            # Dismiss through its shipped command on success, failure or stop.
            from tools.vr_workflows.sweep_view import dismiss_dashboard
            dismiss_dashboard(output/'teardown')
    bridge_key = hashlib.sha256(str(ROOT/'frontend').encode()).hexdigest()[:12]
    bridge_file = Path(tempfile.gettempdir())/f'nadoc-viewer-test-{bridge_key}-{frontend_port}.json'
    cleanup = {'workspace_removed': not Path(workspace).exists(),
               'browser_credentials_removed': not bridge_file.exists()}
    (output/'result.json').write_text(json.dumps({
        'passed': result.returncode == 0 and all(cleanup.values()), 'validation': args.validate,
        'workspace': workspace, 'cleanup': cleanup,
        'evidence': str(output/'sweep-evidence')}, indent=2)+'\n')
    print(output, flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    if not all(cleanup.values()):
        raise RuntimeError('Sweep tour cleanup incomplete: '+str(cleanup))


if __name__ == '__main__':
    main()
