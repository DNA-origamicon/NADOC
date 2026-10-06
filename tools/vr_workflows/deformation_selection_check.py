"""Exercise VR multi-selection through the real browser bridge; no headset needed."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--grep', default='VR')
    parser.add_argument('--output', type=Path, default=ROOT / '.development-artifacts/vr-deformation-selection')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nadoc-vr-selection-') as workspace:
        with socket.socket() as backend, socket.socket() as frontend:
            backend.bind(('127.0.0.1', 0)); frontend.bind(('127.0.0.1', 0))
            backend_port, frontend_port = str(backend.getsockname()[1]), str(frontend.getsockname()[1])
        env = {**os.environ, 'NADOC_WORKSPACE': workspace,
               'NADOC_SMOKE_BACKEND_PORT': backend_port, 'NADOC_SMOKE_FRONTEND_PORT': frontend_port,
               'NADOC_E2E_API_BASE': 'http://127.0.0.1:' + backend_port}
        with (args.output / 'browser.log').open('w') as log:
            result = subprocess.run(['npx', 'playwright', 'test', '--config', 'playwright.vr-bend.config.js',
                                     'vr_deformation_selection.spec.js', '--workers=1', '--grep', args.grep], cwd=ROOT / 'frontend',
                                    env=env, stdout=log, stderr=subprocess.STDOUT)
        print(args.output, flush=True)
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
