"""Temporary CPD production playback benchmark, using private metadata and caches."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from tools.vr_workflows.tour_catalog import ROOT

JOBS = ['d6bcdef3d59f', '972af34aa9c5', '37d39cc6b88f', '9b08bed08561']
LARGE_JOBS = ['8466ccc17eff', '2f281ba1a83a']


def resource_snapshot():
    """Record validation-scope throttling so it is not mislabeled as disk latency."""
    result = {}
    try:
        group = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        scope = Path('/sys/fs/cgroup') / group.lstrip('/')
        for name in ('memory.current', 'memory.peak', 'memory.events', 'memory.pressure'):
            if (scope/name).exists(): result[name] = (scope/name).read_text().strip()
    except (OSError, StopIteration):
        pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--validate', action='store_true')
    selection.add_argument('--job', choices=JOBS + LARGE_JOBS, help='Repeat one completed workload')
    selection.add_argument('--large', action='store_true', help='Compare both completed 24HB workloads')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', type=Path, help='Optional original JS modules for an A/B run')
    args = parser.parse_args()
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit(subprocess.call([str(ROOT/'scripts/validation_guard.sh'), sys.executable, '-m', 'tools.vr_workflows.cpd_playback_check', *sys.argv[1:]], cwd=ROOT))
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active():
        raise RuntimeError('An existing viewer is active; preserve it and run this benchmark after it closes.')
    archive = Path('/media/jojo/Archive')
    if not archive.is_mount():
        raise RuntimeError('Archive must be mounted')
    out = (args.output or ROOT/'.development-artifacts/cpd-playback'/uuid.uuid4().hex[:10]).resolve(); out.mkdir(parents=True, exist_ok=True)
    if out.stat().st_dev != archive.stat().st_dev:
        raise RuntimeError('Benchmark output must be on Archive')
    selected = [args.job] if args.job else LARGE_JOBS if args.large else JOBS if args.validate else JOBS[:1]
    results = []
    metrics = {}
    resources = {}
    def fingerprints():
        values = {}
        for jid in selected:
            source = ROOT/'workspace/md_jobs'/jid
            for name in ('job.json', 'design.json'):
                values[str(source/name)] = hashlib.sha256((source/name).read_bytes()).hexdigest() if (source/name).exists() else None
            job = json.loads((source/'job.json').read_text())
            for path in (source/job['package_subdir']/'output').glob('*.dcd'):
                stat = path.stat(); values[str(path)] = [stat.st_size, stat.st_mtime_ns]
        return values
    before = fingerprints()
    (out/'sources.json').write_text(json.dumps({'before':before,'unchanged':None},indent=2))
    with tempfile.TemporaryDirectory(prefix='cpb-', dir=archive) as temporary:
        ws = Path(temporary)
        (ws/'tmp').mkdir()
        for jid in selected:
            source = ROOT/'workspace/md_jobs'/jid
            job = json.loads((source/'job.json').read_text())
            if job['status'] != 'completed':
                raise RuntimeError('Benchmark source must be completed')
            fixture = '__e2e__' + Path(job['design_source_path']).name
            design = json.loads((ROOT/'workspace'/job['design_source_path']).read_text())
            design['metadata']['name'] = fixture[:-6]
            design['metadata']['identity_last_known_path'] = fixture
            (ws/fixture).write_text(json.dumps(design))
            target = ws/'md_jobs'/jid; target.mkdir(parents=True)
            if (source/'design.json').exists():
                shutil.copy2(source/'design.json', target/'design.json')
            package = target/job['package_subdir']; package.mkdir(parents=True)
            original = source/job['package_subdir']
            for f in original.iterdir():
                if f.is_file() and f.suffix in ('.psf', '.pdb', '.json'):
                    copied = package/f.name
                    shutil.copy2(f, copied)
                    # Large 24HB PSF/PDB copies must not consume the validation
                    # scope as disposable page cache while the viewer is running.
                    if hasattr(os, 'posix_fadvise'):
                        with copied.open('rb') as stream:
                            os.fsync(stream.fileno())
                            os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            (package/'output').mkdir()
            for f in (original/'output').glob('*.dcd'):
                (package/'output'/f.name).symlink_to(f.resolve())
            job.update(design_source_path=fixture, archived=False, archive_path=None, parent_job_id=None)
            (target/'job.json').write_text(json.dumps(job))
            with socket.socket() as a, socket.socket() as b:
                a.bind(('127.0.0.1', 0)); b.bind(('127.0.0.1', 0))
                bp, fp = str(a.getsockname()[1]), str(b.getsockname()[1])
            env = {**os.environ, 'TMPDIR':str(ws/'tmp'), 'NADOC_WORKSPACE':str(ws),
                   'NADOC_SMOKE_BACKEND_PORT':bp, 'NADOC_SMOKE_FRONTEND_PORT':fp,
                   'NADOC_E2E_API_BASE':'http://127.0.0.1:'+bp, 'NADOC_VR_FRAME_AUDIT':'1', 'NADOC_VR_GPU_PASS_TIMING':'1', 'NADOC_VR_VIEW_PIPELINE':'1',
                   'NADOC_PLAYBACK_EXPECT_RESIDENT':'1' if jid in JOBS else '0',
                   'NADOC_PLAYBACK_EXPECT_TRANSFORMS':'0' if os.environ.get('NADOC_VR_TRANSFORM_UPDATES')=='0' else '1',
                   'NADOC_CPD_BENCHMARK_JOB':jid, 'NADOC_CPD_BENCHMARK_FIXTURE':fixture,
                   'NADOC_CPD_BASELINE':str(args.baseline.resolve()) if args.baseline else ''}
            resources[jid] = {'before': resource_snapshot()}
            result = subprocess.run(['node','node_modules/@playwright/test/cli.js','test',
                '--config','playwright.vr-simulations.config.js','vr_cpd_playback.spec.js',
                '--workers=1','--trace','off','--output',str(out/jid)], cwd=ROOT/'frontend', env=env)
            resources[jid]['after'] = resource_snapshot()
            (out/'resources.json').write_text(json.dumps(resources, indent=2))
            results.append({'job':jid,'passed':result.returncode == 0})
            (out/'result.json').write_text(json.dumps(results,indent=2))
            from tools.vr_workflows.playback_metrics import summarize
            metrics[jid] = [row for window in (out/jid).rglob('windows.json') for row in summarize(window.parent)]
            (out/'metrics.json').write_text(json.dumps(metrics, indent=2))
    unchanged = before == fingerprints()
    (out/'sources.json').write_text(json.dumps({'before':before,'unchanged':unchanged},indent=2))
    if not unchanged: raise RuntimeError('Benchmark source metadata or trajectory stat changed')
    (out/'cleanup.json').write_text(json.dumps({'private_workspace':temporary,'removed':not Path(temporary).exists()}))
    if any(not r['passed'] for r in results): raise SystemExit(1)


if __name__ == '__main__':
    main()
