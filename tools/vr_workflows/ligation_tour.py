"""Isolated native VR ligation, scissors/history and view-tablet tours.

Browser, backend, files and native viewer are isolated; only evidence is retained.
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


def main(kind="ligation", prepare_workspace=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', choices=['steady_fast','steady_deliberate','variable_fast','variable_deliberate'], help='Run one diagnostic motion profile instead of the full validation campaign')
    args = parser.parse_args()
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active():
        raise RuntimeError(f'Close the active viewer before starting the isolated {kind.replace("_", " ")} tour.')
    output = (args.output or ROOT/f'.development-artifacts/vr-{kind}'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    profiles = ['steady_fast', 'steady_deliberate', 'variable_fast', 'variable_deliberate'] if args.validate else ['steady_fast']
    if args.profile: profiles = [args.profile]
    results = []
    with tempfile.TemporaryDirectory(prefix='nadoc-ligation-tour-') as temporary:
        if prepare_workspace:
            prepare_workspace(Path(temporary))
        for profile in profiles:
            with socket.socket() as backend, socket.socket() as frontend:
                backend.bind(('127.0.0.1', 0))
                frontend.bind(('127.0.0.1', 0))
                backend_port = str(backend.getsockname()[1])
                frontend_port = str(frontend.getsockname()[1])
            env = {**os.environ, 'NADOC_SMOKE_BACKEND_PORT': backend_port,
                'NADOC_SMOKE_FRONTEND_PORT': frontend_port,
                'NADOC_E2E_API_BASE': 'http://127.0.0.1:' + backend_port,
                'NADOC_WORKSPACE': temporary, 'NADOC_PHYSICAL_VR_TEST': '1',
                'NADOC_VR_PROFILE': profile, 'NADOC_VR_DEMO': '0' if args.validate else '1',
                'NADOC_VR_DEMO_HOLD': '3'}
            command = ['npx', 'playwright', 'test', '--config', 'playwright.vr-simulations.config.js' if kind == 'simulations' else 'playwright.smoke.config.js',
                f'vr_{kind}.spec.js', '--workers=1', '--output', str(output/'end'/profile)]
            if not args.validate:
                command.append('--headed')
            result = subprocess.run(command, cwd=ROOT/'frontend', env=env)
            results.append({'profile': profile, 'passed': result.returncode == 0})
            (output/'result.json').write_text(json.dumps({'results': results,
                'workspace': 'temporary, removed on exit'}, indent=2))
            if result.returncode and kind != 'simulations':
                raise SystemExit(result.returncode)
    print(output, flush=True)
    if any(not result['passed'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
