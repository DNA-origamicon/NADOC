"""Generate the Extrude picture guide using real UI actions in isolated scratch.

Persistent inventory: only the requested output directory (Markdown, PNGs, action
manifest, audited example and verification). Everything else lives beneath a
fresh owned scratch root: workspace/project history, browser profiles/downloads,
viewer bridge credentials (TMPDIR), caches, server logs, Playwright output.
The finally block stops owned processes and removes scratch on failure too.
No user workspace is opened. SIGKILL/power loss requires review of the printed root.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.run_deformation_history_e2e import (
    REPO, browser_installation, storage_parent, stop_owned_processes,
)
from scripts.feature_guides import (
    GUIDES, directory_hashes, load_catalog, promote_directory,
    render_guide, render_ledger, snapshot,
)


def main(output=None, replace=False):
    catalog = load_catalog(REPO)
    feature = catalog['features']['extrude']
    source = snapshot(REPO, catalog, feature)
    if source['unmatched']:
        raise RuntimeError(f'Missing guide dependencies: {source["unmatched"]}')
    output = Path(output or REPO / GUIDES / feature['guide']).expanduser().resolve()
    expected, previous_manifest = None, None
    if output.exists():
        if not replace:
            raise RuntimeError(f'Refusing to overwrite an existing guide: {output}; use --replace after review')
        previous_manifest = json.loads((output / 'manifest.json').read_text())
        if previous_manifest.get('feature') != 'extrude':
            raise RuntimeError('Refusing to replace a different guide')
        expected = directory_hashes(output)
        if set(expected) != set(previous_manifest['assets']) | {'manifest.json'}:
            raise RuntimeError('Guide contains unexpected files; preserve/review them before replacement')
    browsers = browser_installation()
    root = Path(tempfile.mkdtemp(prefix='__e2e__guide-', dir=storage_parent()))
    (root / '.owner-start').touch()
    print(f'Owned scratch inventory: {root}', flush=True)
    child = None
    stage = None
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        for name in ('workspace', 'tmp', 'cache', 'guide'):
            (root / name).mkdir()
        env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': browsers,
               'NADOC_HISTORY_E2E_ROOT': str(root), 'NADOC_SMOKE_E2E_ROOT': str(root),
               'NADOC_GUIDE_OUTPUT': str(root / 'guide'),
               'NADOC_WORKSPACE': str(root / 'workspace'), 'NADOC_DISABLE_SESSION_CACHE': '1',
               'TMPDIR': str(root / 'tmp'), 'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
               'XDG_CACHE_HOME': str(root / 'cache'), 'PYTHONDONTWRITEBYTECODE': '1',
               'PWTEST_CACHE_DIR': str(root / 'cache' / 'playwright'),
               'CUDA_CACHE_PATH': str(root / 'cache' / 'cuda'),
               'NADOC_RUNPOD_AUTOCONNECT': '0', 'NADOC_SHARE_AUTOSTART': '0',
               'NADOC_SHARE_CONTROL_FILE': str(root / 'share-control.json'),
               'NADOC_MD_PLAYBACK_CACHE_DIR': str(root / 'workspace' / 'playback')}
        child = subprocess.Popen(
            ['node', 'node_modules/@playwright/test/cli.js', 'test', '--config', 'playwright.guides.config.js'],
            cwd=REPO / 'frontend', env=env, start_new_session=(os.name == 'posix'))
        if child.wait() != 0:
            raise RuntimeError('Guide capture failed; no guide published')
        from backend.core.models import Design
        from scripts.agent_structure_guard import audit, publish
        files = list((root / 'workspace').glob('__e2e__*.nadoc'))
        if len(files) != 1:
            raise RuntimeError('AGENT_PROCESS_REQUIRED: expected one saved example')
        saved = Design.model_validate_json(files[0].read_text())
        audit(saved)
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.guide-staging-', dir=output.parent))
        proof = publish(saved, stage / 'example.nadoc')
        proof['path'] = 'example.nadoc'  # portable link, not a machine-local staging path
        reopened = audit(Design.model_validate_json((stage / 'example.nadoc').read_text()))
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
        (stage / 'verification.json').write_text(json.dumps({
            'guide': 'extrude', 'source_revision': revision,
            'source_worktree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip()),
            'publication': proof, 'reopened_audit': reopened,
            'interaction': 'Real browser input; rendered cell positions are read-only observations',
        }, indent=2))
        for asset in (root / 'guide').iterdir():
            shutil.copy2(asset, stage / asset.name)
        steps = json.loads((stage / 'steps.json').read_text())
        (stage / 'README.md').write_text(render_guide(steps, feature))
        current_catalog = load_catalog(REPO)
        if (feature != current_catalog['features']['extrude']
                or source != snapshot(REPO, current_catalog, current_catalog['features']['extrude'])):
            raise RuntimeError('Source changed during capture; refusing to stamp a mixed-version guide')
        captured = datetime.now(ZoneInfo('America/Denver')).isoformat(timespec='seconds')
        (stage / 'manifest.json').write_text(json.dumps({
            'schema': 1, 'feature': 'extrude',
            'created_at': previous_manifest['created_at'] if previous_manifest else captured,
            'captured_at': captured, 'source_revision': revision,
            'source_worktree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip()),
            'source': source, 'covered_workflows': feature['covered_workflows'],
            'introduction': feature['introduction'],
            'assets': directory_hashes(stage),
        }, indent=2) + '\n')
        promote_directory(stage, output, expected)
        stage = None
        audit(Design.model_validate_json((output / 'example.nadoc').read_text()))
        if output == (REPO / GUIDES / feature['guide']).resolve():
            (REPO / GUIDES / 'LEDGER.md').write_text(render_ledger(REPO))
        print(f'Guide: {output / "README.md"}', flush=True)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        signal.signal(signal.SIGTERM, previous)
        stop_owned_processes(root)
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        shutil.rmtree(root)
        if root.exists():
            raise RuntimeError(f'Cleanup failed: {root}')
        print(f'Cleanup verified absent: {root}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='Optional preview destination; default docs/guides/extrude')
    parser.add_argument('--replace', action='store_true', help='Regenerate the existing guide after review, preserving first-created date')
    args = parser.parse_args()
    main(args.output, args.replace)
