"""Bounded native CPD production starts through the real create/start HTTP routes."""
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from backend.api import routes_md
from backend.core import simulation_runtime, namd_runner, memory_budget
from backend.core.md_job import MdJob
from scripts.validate_cpd_hmr import pin, save


async def main():
    root = Path(tempfile.mkdtemp(prefix='cpd-managed-start-20261104-', dir='.development-artifacts')).resolve()
    print(root, flush=True)
    source = Path('workspace').resolve()
    parents = ['935bbecba8cf', '6d6c46163a00', 'b2b43076da96', '974191dc2e63']
    receipt = {'worker': pin(__file__), 'runs': [], 'passed': False}
    try:
        with tempfile.TemporaryDirectory(prefix='workspace-', dir=root) as temporary:
            ws = Path(temporary)
            (ws/'md_jobs').mkdir()
            pins = []
            for jid in parents:
                src = source/'md_jobs'/jid
                dst = ws/'md_jobs'/jid
                dst.mkdir()
                for f in src.iterdir():
                    if f.is_file():
                        shutil.copy2(f, dst/f.name)
                    elif f.name == 'package':
                        (dst/f.name).symlink_to(f, target_is_directory=True)
                pins.append(pin(src/'job.json'))
            app = FastAPI()
            app.include_router(routes_md.router, prefix='/api')
            with simulation_runtime.use_workspace(ws):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://validation') as client:
                    for jid in parents:
                        parent = MdJob.load(jid, ws)
                        record = {'parent': jid, 'design': parent.design_name}
                        receipt['runs'].append(record)
                        response = await client.post(f'/api/md/jobs/{jid}/production-run', json={
                            'length_ns': .01, 'autostart': False, 'production_timestep_fs': 4,
                            'hmr': True, 'gpu_resident': 'on', 'execution_target': 'local',
                            'allow_undersized_cell': True, 'enm_restraints': 'off', 'dcd_freq': 250,
                            'seed': 731044})
                        record['create'] = {'status': response.status_code, 'body': response.json()}
                        response.raise_for_status()
                        child_id = response.json()['job']['job_id']
                        admission_deadline = time.monotonic()+300
                        while True:
                            with memory_budget._locked() as registry:
                                busy = any(r['kind'] in {'heavy_analysis', 'simulation'}
                                           for r in memory_budget._records(registry))
                            if not busy:
                                break
                            if time.monotonic() > admission_deadline:
                                raise TimeoutError('Waiting for existing user workload')
                            await asyncio.sleep(1)
                        response = await client.post(f'/api/md/jobs/{child_id}/start')
                        record['start'] = {'status': response.status_code, 'body': response.json()}
                        response.raise_for_status()
                        deadline = time.monotonic()+600
                        while True:
                            job = MdJob.load(child_id, ws)
                            if not namd_runner.is_running(child_id) and job.status.value != 'running':
                                if (job.status.value == 'failed' and 'Heavy trajectory analysis is running' in (job.error or '')
                                        and time.monotonic() < deadline):
                                    record.setdefault('busy_admission_retries', 0)
                                    record['busy_admission_retries'] += 1
                                    await asyncio.sleep(2)
                                    response = await client.post(f'/api/md/jobs/{child_id}/start')
                                    response.raise_for_status()
                                    continue
                                break
                            if time.monotonic() > deadline:
                                namd_runner.stop_job(child_id, ws)
                                raise TimeoutError(child_id)
                            await asyncio.sleep(1)
                        record['job'] = json.loads((job.job_dir(ws)/'job.json').read_text())
                        pkg = job.package_dir(ws)
                        evidence = root/child_id
                        evidence.mkdir()
                        for f in pkg.rglob('*'):
                            if f.is_file() and f.suffix in {'.log', '.conf'}:
                                dest = evidence/f.relative_to(pkg)
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(f, dest)
                        record['passed'] = job.status.value == 'completed'
                        save(root/'receipt.json', receipt)
                        print(parent.design_name, job.status.value, job.error, flush=True)
                        if not record['passed']:
                            raise RuntimeError(job.error)
            assert all(pin(p['path']) == p for p in pins)
            receipt['source_jobs_unchanged'] = True
        receipt['temporary_files_removed'] = not Path(temporary).exists()
        receipt['passed'] = True
    finally:
        save(root/'receipt.json', receipt)


if __name__ == '__main__':
    asyncio.run(main())
