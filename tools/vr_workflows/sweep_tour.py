"""Isolated S-shaped Sweep tour: Free Draw, point edits and desktop history.

Demo uses steady_fast with visible review holds; validation uses all four
controller profiles. The browser, native viewer and temporary part belong to
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
            'vr_sweep.spec.js', '--workers=1', '--output', str(output/'playwright')]
        if not args.validate or os.environ.get('NADOC_VR_FRAME_AUDIT') == '1':
            command.append('--headed')
        result = subprocess.run(command, cwd=ROOT/'frontend', env=env)
        (output/'result.json').write_text(json.dumps({
            'passed': result.returncode == 0, 'validation': args.validate,
            'workspace': 'temporary, removed on exit',
            'evidence': str(output/'sweep-evidence')}, indent=2)+'\n')
        print(output, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
