"""Exercise native history event dispatch and revision-checked browser refresh.

Uses an isolated browser/backend and intercepted VR transport, preserving any
physical headset session. Screenshots and failure traces remain in the report.
"""
import argparse
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.parse_args()
    output = ROOT / '.development-artifacts/vr-history-refresh' / uuid.uuid4().hex[:10]
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='nadoc-vr-history-') as workspace:
        env = {**os.environ, 'SCRYWRITE_TEST_WORKSPACE': workspace}
        with (output / 'browser.log').open('w') as log:
            result = subprocess.run([
                str(ROOT / 'scripts/validation_guard.sh'), 'node',
                'node_modules/@playwright/test/cli.js', 'test',
                '--config', 'playwright.vr-history.config.js', '--output', str(output / 'playwright'),
            ], cwd=ROOT / 'frontend', env=env, stdout=log, stderr=subprocess.STDOUT)
        leftovers = list(Path(workspace).rglob('*.nadoc')) + list(Path(workspace).rglob('*.nass'))
        if leftovers:
            raise RuntimeError(f'Test workspace cleanup failed: {leftovers}; evidence: {output}')
        print(output, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
