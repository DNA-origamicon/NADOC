"""Visible File workflow in an isolated browser and physical native viewer.

No molecular objects or saved parts are created. New Part is cancelled after
keyboard entry. The temporary empty backend document only permits VR startup.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
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
        raise RuntimeError('An existing viewer is active; this isolated demo will not replace it.')
    subprocess.run([str(ROOT/'scripts/validation_guard.sh'), sys.executable, '-c',
        'from backend.api.routes_vr import _read_state, _ensure_viewer_built; _read_state(); _ensure_viewer_built()'], check=True)
    output = (args.output or ROOT/'.development-artifacts/vr-file-tour'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = None
    with tempfile.TemporaryDirectory(prefix='nadoc-file-tour-') as workspace:
        with socket.socket() as backend, socket.socket() as frontend:
            backend.bind(('127.0.0.1', 0)); frontend.bind(('127.0.0.1', 0))
            backend_port, frontend_port = str(backend.getsockname()[1]), str(frontend.getsockname()[1])
        # Folder navigation has real selectable entries without any structure fixture.
        (Path(workspace)/'File demo folder').mkdir()
        env = {**os.environ, 'SCRYWRITE_BACKEND_PORT': backend_port,
               'SCRYWRITE_FRONTEND_PORT': frontend_port, 'SCRYWRITE_TEST_WORKSPACE': workspace,
               'NADOC_E2E_FRONTEND_PORT': frontend_port, 'NADOC_WORKSPACE': workspace,
               'NADOC_E2E_API_BASE': 'http://127.0.0.1:'+backend_port,
               'NADOC_PHYSICAL_VR_TEST': '1', 'NADOC_VR_FILE_EVIDENCE': str(output),
               'NADOC_VR_FILE_VALIDATE': '1' if args.validate else '0',
               'NADOC_VR_DEMO_HOLD': os.environ.get('NADOC_VR_DEMO_HOLD', '5')}
        try:
            result = subprocess.run([str(ROOT/'scripts/validation_guard.sh'), 'node',
                'node_modules/@playwright/test/cli.js', 'test', '--config', 'playwright.vr-file-tour.config.js',
                '--output', str(output/'playwright'), '--headed'], cwd=ROOT/'frontend', env=env)
        finally:
            from tools.vr_workflows.sweep_view import dismiss_dashboard
            dismiss_dashboard(output/'teardown')
            leftovers = [str(p) for suffix in ('*.nadoc', '*.nass') for p in Path(workspace).rglob(suffix)]
            (output/'workspace-check.json').write_text(json.dumps({'structure_files': leftovers}, indent=2))
    key = hashlib.sha256(str(ROOT/'frontend').encode()).hexdigest()[:12]
    cleanup = {'workspace_removed': not Path(workspace).exists(), 'no_structure_files': not leftovers,
               'credentials_removed': not (Path(tempfile.gettempdir())/f'nadoc-viewer-test-{key}-{frontend_port}.json').exists()}
    (output/'result.json').write_text(json.dumps({'passed': result is not None and result.returncode == 0 and all(cleanup.values()),
        'cleanup': cleanup, 'validation': args.validate}, indent=2))
    stages_path = output/'stages.json'
    stages = json.loads(stages_path.read_text()) if stages_path.exists() else {'stages': []}
    cards = ''.join('<section><h2>'+html.escape(stage['name'])+'</h2><img src="'+html.escape(stage['name'])+'/desktop/desktop-client.png" alt="Actual desktop mirror"></section>' for stage in stages['stages'])
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>VR File workflow review</title>'
        '<style>body{background:#10151c;color:#eee;font:18px system-ui;max-width:1200px;margin:32px auto}img{width:100%}section{margin:40px 0}</style>'
        '<h1>VR File workflow review</h1><p>Real controller input, browser dialogs, submitted stereo images and actual desktop captures. '
        'New Part is cancelled before creation. No part files are saved. Save As commit and existing-file loading are outside this non-creating demo.</p>'+cards)
    print(output/'index.html', flush=True)
    if result is None or result.returncode or not all(cleanup.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
