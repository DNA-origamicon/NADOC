"""Package batching preserves paths/content and fails before submission on extraction errors."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import pytest
from backend.core import md_executor as ex
from backend.core.cluster_ssh import RunResult


@pytest.mark.parametrize('gpu', [True, False])
def test_bundle_roundtrip_preserves_package_and_progress(tmp_path, gpu):
    package = tmp_path / 'package'
    (package / 'forcefield').mkdir(parents=True)
    for i in range(8):
        (package / f'stage{i}.conf').write_text('GPUresident on\ntimestep 4\nrun 20\n')
    (package / 'forcefield' / 'parameters with spaces.prm').write_text('parameters\n')
    (package / 'large.pdb').write_bytes(b'x' * (1024 * 1024 + 1))
    (package / 'script.sh').write_text('#!/bin/sh\nexit 0\n')
    (package / 'script.sh').chmod(0o755)
    remote = tmp_path / 'remote with spaces'
    uploads = []
    updates = []
    class Connection:
        async def mkdir_p(self, path):
            Path(path).mkdir(parents=True, exist_ok=True)
        async def sftp_put(self, source, destination):
            uploads.append(destination)
            shutil.copyfile(source, destination)
        async def run(self, command):
            r = subprocess.run(command, shell=True, capture_output=True, text=True)
            return RunResult(r.returncode, r.stdout, r.stderr)
    asyncio.run(ex._upload_package(Connection(), ex.stage_plan(package), str(remote), tmp_path,
                                   None, gpu=gpu, submit_progress=lambda *a, **kw: updates.append(kw)))
    assert len(uploads) == 2  # one setup bundle and one large input
    assert not (remote / '.nadoc_setup.tar').exists()
    assert not list(package.glob('*.tar'))
    for source, rel in ex.stage_plan(package):
        expected = source.read_bytes()
        if source.suffix == '.conf' and not gpu:
            expected = ex.strip_gpu_resident(expected.decode()).encode()
        assert (remote / rel).read_bytes() == expected
    assert (remote / 'script.sh').stat().st_mode & 0o111
    assert updates[-1]['files_done'] == updates[-1]['files_total'] == 11
    assert updates[-1]['bytes_done'] == updates[-1]['bytes_total']


def test_extract_failure_stops_upload_and_cleans_local_bundle(tmp_path):
    files = []
    for i in range(8):
        p = tmp_path / f'{i}.conf'; p.write_text('run 20\n'); files.append((p, p.name))
    uploaded = []
    class Connection:
        async def mkdir_p(self, path): pass
        async def sftp_put(self, source, destination): uploaded.append(Path(source))
        async def run(self, command): return RunResult(1, '', 'disk quota exceeded')
    with pytest.raises(RuntimeError, match='disk quota exceeded'):
        asyncio.run(ex._upload_package(Connection(), files, '/remote', tmp_path, None,
                                       gpu=True, submit_progress=lambda *a, **kw: None))
    assert len(uploaded) == 1 and not uploaded[0].exists()
