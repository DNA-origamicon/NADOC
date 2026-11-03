"""Record launch-time identities so future measurements can be compared honestly.

Provenance is diagnostic metadata, not a claim that a build/device is qualified.
Missing identities are explicit; never infer them from a later installation.
"""
from functools import lru_cache
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import time


@lru_cache(maxsize=32)
def _hash_file(path, size, mtime, ctime):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_identity(path):
    path = Path(path).resolve()
    try:
        stat = path.stat()
        return dict(path=str(path), sha256=_hash_file(str(path), stat.st_size,
                    stat.st_mtime_ns, stat.st_ctime_ns), bytes=stat.st_size)
    except OSError as exc:
        return dict(path=str(path), sha256=None, error=str(exc))


def resource_receipt(binary, configuration, estimate, *, threads, devices):
    """Snapshot the forecast and its runtime identity before the engine starts."""
    executable = shutil.which(str(binary)) or str(binary)
    gpu = None; errors = []
    cuda = bool(devices and str(devices).lower() not in ('cpu', 'none'))
    if cuda:
        try:
            result = subprocess.run(['nvidia-smi', '--id='+str(devices),
                '--query-gpu=name,uuid,driver_version,memory.total',
                '--format=csv,noheader,nounits'], capture_output=True, text=True,
                timeout=5, check=True)
            lines = result.stdout.strip().splitlines()
            if len(lines) != 1:
                raise ValueError('Expected one GPU identity')
            name, uuid, driver, total = (v.strip() for v in lines[0].split(','))
            gpu = dict(name=name, uuid=uuid, driver=driver, total_mib=int(total))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            errors.append('GPU identity unavailable: '+str(exc))
    engine = file_identity(executable)
    conf = file_identity(configuration)
    missing = [name for name, item in [('engine_sha256',engine),('config_sha256',conf)]
               if item['sha256'] is None]
    if cuda and gpu is None:missing.extend(['gpu','driver'])
    return dict(schema='namd-resource-receipt-v1', recorded_epoch=time.time(),
        engine=engine, configuration=conf, gpu=gpu, threads=threads, devices=devices,
        platform=platform.platform(), forecast=estimate.as_dict(),
        missing_provenance=missing, errors=errors,
        qualification='Identity recorded for comparison; no automatic cross-build or cross-device certification.')
