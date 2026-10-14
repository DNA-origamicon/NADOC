"""Reviewed launch repair; the frozen alternate-release calculation stays unchanged."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import time

REPO = Path(os.environ.get('NADOC_REPO_ROOT', '/home/jojo/Work/NADOC'))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked, now, pin, read, save


def blocking_units(listing):
    """Only unit identity determines exclusion; descriptions contain arbitrary paths."""
    units = []
    for line in listing.splitlines():
        fields = line.split()
        if not fields:
            continue
        unit = fields[1] if fields[0] == '●' else fields[0]
        if 'cpd-' in unit and not unit.endswith('-watch.service'):
            units.append(unit)
    return units


def require_resources(available, archive_free):
    if available < 12*1024**3 or archive_free < 30*1024**3:
        raise RuntimeError('Insufficient headroom')


def launch(root):
    review = read(root/'launch_repair_review.json')
    assert checked(review['launcher']) == Path(__file__).resolve()
    assert checked(review['native_plan']) == root/'plan.json'
    assert review['scientific_plan_unchanged'] and review['resource_limits_unchanged']
    for item in review['evidence']:
        checked(item)
    plan = read(root/'plan.json')
    spec = importlib.util.spec_from_file_location('frozen_release_v2', checked(plan['worker']))
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.context(root)  # Archive mount, pause, authorization, version and source checks.
    assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    service = root.parent/(root.name+'-service')
    if (root/'launch_receipt.json').exists() or service.exists():
        raise RuntimeError('Job already launched or partially created; review before recovery')
    listing = subprocess.check_output(['systemctl', '--user', 'list-units', '--type=service',
        '--state=running', '--no-legend', '--plain', '--no-pager'], text=True)
    conflicts = blocking_units(listing)
    if conflicts:
        raise RuntimeError(f'Another CPD calculation active: {conflicts}')
    processes = subprocess.check_output(['ps', '-eo', 'args='], text=True).splitlines()
    if any(row.split() and Path(row.split()[0]).name in ('namd2', 'namd3', 'psi4') for row in processes):
        raise RuntimeError('Another native job active')
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    free = shutil.disk_usage(root).free
    require_resources(available, free)
    codex = shutil.which('codex')
    if not codex or not os.environ.get('CODEX_THREAD_ID'):
        raise RuntimeError('Missing completion-wake destination')
    service.mkdir()
    for old, new in [('launch.py', 'supervisor.py'), ('watch.py', 'watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old, service/new)
    start = time.time()
    unit = 'cpd-corrected-anti1-alternate-sugar-qm-release-v2'
    save(service/'watcher_config.json', dict(codex_executable=str(Path(codex).resolve()),
        expected_seconds=plan['expected_seconds'], review_deadline_epoch=start+6900,
        review_deadline_id='alternate-sugar-qm-release-v2-audit', self_test=False))
    save(service/'execution_plan.json', dict(unit=unit, thread=os.environ['CODEX_THREAD_ID'],
        command=[str(worker.PYTHON), str(checked(plan['worker'])), 'run', str(root)],
        cwd=str(root), runtime_hours=2., memory_gib=8, omp_threads=4,
        plan=pin(root/'plan.json'), completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json', dict(at=now(), deadline_epoch=start+7200, unit=unit,
        available_memory_gib=available/1024**3, archive_free_bytes=free,
        execution_plan=pin(service/'execution_plan.json'), supervisor=pin(service/'supervisor.py'),
        watcher=pin(service/'watcher.py'), launch_repair_review=pin(root/'launch_repair_review.json'),
        launcher=pin(Path(__file__))))
    subprocess.run(['systemd-run', '--user', f'--unit={unit}', '--property=MemoryMax=8G',
        '--property=MemorySwapMax=0', '--property=RuntimeMaxSec=7185s',
        '--property=TimeoutStopSec=15s', '--property=KillMode=control-group', '--property=CPUQuota=400%',
        f'--setenv=PYTHONPATH={REPO}', f'--setenv=NADOC_REPO_ROOT={REPO}',
        '--setenv=PYTHONDONTWRITEBYTECODE=1', '--setenv=OPENBLAS_NUM_THREADS=1',
        '--setenv=MKL_NUM_THREADS=1', '--setenv=OMP_NUM_THREADS=4',
        f'--setenv=TMPDIR={root}/tmp', f'--setenv=PSI_SCRATCH={root}/tmp',
        '/usr/bin/python3', str(service/'supervisor.py'), '--supervise', str(service)], check=True)
    print(service)


if __name__ == '__main__':
    launch(Path(sys.argv[1]).resolve())
