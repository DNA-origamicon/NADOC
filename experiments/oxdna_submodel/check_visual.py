"""Run the real-app visual check, retaining one image and cleaning all scratch.

Persistent-artifact inventory: copied oxDNA jobs, API load caches/revisions,
backend sessions, browser storage, Vite cache, reports and screenshots all live
under TemporaryDirectory. The finally cleanup covers failures/timeouts. Only the
single review screenshot and this run's log are copied to the evidence directory.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output',type=Path)
parser.add_argument('--parent-job',type=Path)
parser.add_argument('--source',type=Path)
args=parser.parse_args()
output=args.output.resolve()
with tempfile.TemporaryDirectory(prefix='visual-', dir=output) as temporary:
    scratch = Path(temporary)
    manifest=json.loads((output/('visual-manifest.json' if (output/'visual-manifest.json').exists() else 'manifest.json')).read_text())
    if args.parent_job:
        if not args.source:raise ValueError('--source required with --parent-job')
        parent=args.parent_job.resolve()
        shutil.copytree(parent,scratch/'workspace/oxdna_jobs'/parent.name)
        manifest.update(job_id=parent.name,source=str(args.source.resolve()),display_relaxed=True)
    else:
        shutil.copytree(output/'workspace', scratch/'workspace')
    (scratch/'manifest.json').write_text(json.dumps(manifest))
    (scratch/'tmp').mkdir()
    env = {**os.environ, 'NADOC_WORKSPACE':str(scratch/'workspace'),
           'NADOC_SMOKE_E2E_ROOT':str(scratch), 'TMPDIR':str(scratch/'tmp'),
           'NADOC_SUBMODEL_MANIFEST':str(scratch/'manifest.json')}
    with (output/'visual.log').open('w') as log:
        process = subprocess.Popen(['npx','playwright','test','--config=playwright.smoke.config.js',
                                    'oxdna_submodel_duplex.spec.js'], cwd='frontend', env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=150)
        finally:
            # npx may leave server/browser children on failure; own the entire group.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    for image in scratch.glob('playwright/**/duplex-*.png'):
        shutil.copy2(image, output/image.name)
    for report in scratch.glob('playwright/**/visualization-options.json'):
        shutil.copy2(report, output/report.name)
    if code:
        for failure in scratch.glob('playwright/**/test-failed-*.png'):
            shutil.copy2(failure, output/failure.name)
    if code:
        raise subprocess.CalledProcessError(code, process.args)
assert not scratch.exists()
