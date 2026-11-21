"""Remote ownership, submission receipts and result acceptance without native simulations."""
import asyncio
import json
from pathlib import Path
import tarfile
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.core import solver_cluster as remote
from backend.core.solver_cluster_config import SolverClusterSettings, validate_settings


@pytest.mark.parametrize('rc', [0, 1])
def test_environment_preflight_allows_cold_shared_volume_imports(rc):
    class Connection:
        def is_connected(self):
            return True

        async def run(self, command, *, timeout):
            # Model a valid cold import taking longer than the former limit.
            if timeout < 45:
                raise TimeoutError('cold network-volume import')
            assert timeout <= 180
            return SimpleNamespace(rc=rc, stdout='', stderr='missing dependency')

    check = remote.preflight(Connection(), 'snupi', SolverClusterSettings(python='/env/python'))
    if rc:
        with pytest.raises(RuntimeError, match='missing dependency'):
            asyncio.run(check)
    else:
        asyncio.run(check)


def test_uploaded_bundle_imports_snupi_without_source_checkout(tmp_path):
    job = job_at(tmp_path, 'snupi')
    # Opaque archive fixture, not an authored molecular structure.
    (job.job_dir(tmp_path) / 'design.json').write_bytes(b'opaque existing snapshot')
    archive = tmp_path / 'bundle.tar.gz'
    remote.bundle_inputs(archive, 'snupi', job, tmp_path)
    extracted = tmp_path / 'extracted'
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert 'backend/core/m13mp18.txt' in names
        assert 'backend/core/p7560.txt' in names
        assert 'backend/core/p8064.txt' in names
        assert 'backend/data/parameters/snupi_params.json' in names
        tar.extractall(extracted, filter='data')
    result = subprocess.run([sys.executable, '-I', '-c',
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'from backend.core import snupi_runner; from backend.physics import fem_solver; '
        'from backend.core.sequences import M13MP18_SEQUENCE; '
        'assert len(M13MP18_SEQUENCE) == 7249; '
        'assert snupi_runner.__file__.startswith(sys.argv[1])', str(extracted)],
        text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def job_at(tmp_path, engine):
    from backend.core.snupi_job import new_snupi_job
    from backend.core.mrdna_job import new_mrdna_job
    job = (new_snupi_job if engine == 'snupi' else new_mrdna_job)(design_name='existing snapshot')
    job.execution_target = 'alpine'
    job.design_fingerprint = 'source-fingerprint'
    job.remote = {'settings': {'python': '/env/bin/python'}, 'slurm_job_id': '123', 'directory': '/scratch/job'}
    job.save(tmp_path)
    return job


@pytest.mark.parametrize('engine', ['snupi', 'mrdna'])
def test_legacy_and_remote_persistence(tmp_path, engine):
    job = job_at(tmp_path, engine)
    assert remote.job_class(engine).load(job.job_id, tmp_path).remote == job.remote
    data = job.to_dict()
    data.pop('execution_target'); data.pop('remote')
    assert remote.job_class(engine).from_metadata(data).execution_target == 'local'


def test_settings_validate_scheduler_and_shell_values(tmp_path):
    with pytest.raises(ValueError):
        SolverClusterSettings(python='/env/python', partition='acpu\n#SBATCH --exclusive')
    with pytest.raises(ValueError, match='GPU'):
        validate_settings('mrdna', {'python': '/env/python', 'arbd': '/bin/arbd'}, tmp_path)
    config, _, partition = validate_settings('snupi', {'python': '/env/python'}, tmp_path)
    assert config.mem_gb == 64
    job = job_at(tmp_path, 'snupi')
    script = remote.script('snupi', job, '/scratch/a space', config, partition)
    assert "cd '/scratch/a space'" in script
    assert '#SBATCH --mem=64G' in script
    assert 'NADOC_HYDRO_MEM_GB=54.975581' in script
    assert '--gres' not in script


@pytest.mark.parametrize('engine', ['snupi', 'mrdna'])
def test_remote_reconcile_never_uses_local_pid(tmp_path, monkeypatch, engine):
    job = job_at(tmp_path, engine)
    job.status = type(job.status)('running')
    monkeypatch.setattr(remote, '_background', lambda *a: None)
    module = __import__(f'backend.core.{engine}_runner', fromlist=['reconcile'])
    assert getattr(module, f'reconcile_{engine}_status')(job, tmp_path).status.value == 'running'
    assert module.job_progress(job, tmp_path)['eta_seconds'] is None


class Connection:
    def __init__(self, state='RUNNING', archive=None):
        self.state = state
        self.archive = archive
        self.commands = []
    def is_connected(self): return True
    async def run(self, command, **kw):
        self.commands.append(command)
        if 'tar czf results.tar.gz' in command:
            # A large valid result can exceed the former two-minute window.
            if kw.get('timeout', 0) < 180:
                raise TimeoutError('large native trajectory packaging')
            assert kw['timeout'] <= 900
        return SimpleNamespace(rc=0, stderr='', stdout=f'123|{self.state}|0:0\n' if 'sacct' in command else '')
    async def sftp_get(self, remote_path, local):
        import shutil
        if remote_path.endswith('results.tar.gz'):
            shutil.copyfile(self.archive, local)
        else:
            Path(local).write_text('scheduler log')


@pytest.mark.parametrize('engine', ['snupi', 'mrdna'])
@pytest.mark.parametrize('scheduler,solver,expected', [('COMPLETED','completed','completed'), ('COMPLETED','failed','failed'), ('TIMEOUT','running','failed')])
def test_scheduler_completion_requires_solver_result(tmp_path, engine, scheduler, solver, expected):
    job = job_at(tmp_path, engine)
    stage = tmp_path / 'remote'; stage.mkdir()
    report = job.to_dict(); report['status'] = solver
    if engine == 'snupi':
        report['execution'] = {'backend': 'cuda', 'precision': 'float64', 'rng': 'torch-cuda'}
    (stage / 'job.json').write_text(json.dumps(report))
    (stage / 'display.json').write_text('{}')
    (stage / 'design.json').write_text('must never replace local snapshot')
    (stage / '.runtime.json').write_text('must never import remote PID')
    (job.job_dir(tmp_path) / 'design.json').write_text('original')
    archive = tmp_path / 'result.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in stage.iterdir(): tar.add(path, arcname=path.name)
    asyncio.run(remote.refresh(engine, job.job_id, tmp_path, Connection(scheduler, archive)))
    loaded = remote.job_class(engine).load(job.job_id, tmp_path)
    assert loaded.status.value == expected
    assert loaded.remote['results_collected']
    assert loaded.execution_target == 'alpine'
    if engine == 'snupi':
        assert loaded.execution == report['execution']
    assert (job.job_dir(tmp_path) / 'design.json').read_text() == 'original'
    assert not (job.job_dir(tmp_path) / '.runtime.json').exists()


def test_disconnect_preserves_remote_state(tmp_path):
    job = job_at(tmp_path, 'snupi')
    conn = Connection(); conn.is_connected = lambda: False
    asyncio.run(remote.refresh('snupi', job.job_id, tmp_path, conn))
    assert remote.job_class('snupi').load(job.job_id, tmp_path).remote == job.remote
    assert not conn.commands


def test_existing_receipt_prevents_duplicate_submit(tmp_path):
    job = job_at(tmp_path, 'snupi')
    with pytest.raises(ValueError, match='submission receipt'):
        remote.start(job, tmp_path, 'snupi')


def test_cancel_requires_connection_and_scheduler_ack(tmp_path):
    job = job_at(tmp_path, 'snupi')
    job.remote.pop('slurm_job_id')
    with pytest.raises(ValueError, match='scheduler ID'):
        asyncio.run(remote.cancel(job, tmp_path))


def test_pending_provider_receipt_blocks_archive_and_delete(tmp_path):
    job = job_at(tmp_path, 'snupi')
    assert remote.remote_pending(job)
    job.execution_target = 'runpod'; job.status = type(job.status)('failed')
    job.remote = {'pod_id': 'billing-pod'}
    assert remote.remote_pending(job)
    job.remote['pod_destroyed'] = True
    assert not remote.remote_pending(job)


def test_submit_pipeline_failure_retains_uncertainty(tmp_path, monkeypatch):
    job = job_at(tmp_path, 'snupi')
    job.remote = {'settings': {'python': '/env/bin/python'}}
    job.save(tmp_path)
    async def preflight(*args): pass
    monkeypatch.setattr(remote, 'preflight', preflight)
    monkeypatch.setattr(remote, 'bundle_inputs', lambda *args: None)
    class SubmitConnection:
        user = 'test'
        async def mkdir_p(self, path): pass
        async def sftp_put(self, source, target): pass
        async def run(self, command, **kw):
            return SimpleNamespace(rc=1 if 'sbatch --parsable' in command else 0,
                                   stdout='', stderr='receipt write failed')
    with pytest.raises(RuntimeError, match='receipt write failed'):
        asyncio.run(remote.submit('snupi', job.job_id, tmp_path, SubmitConnection()))
    live = remote.job_class('snupi').load(job.job_id, tmp_path)
    assert live.remote['submission_uncertain']
    with pytest.raises(ValueError, match='unresolved submission'):
        remote.start(live, tmp_path, 'snupi')
