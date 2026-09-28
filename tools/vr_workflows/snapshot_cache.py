"""Bounded immutable export cache for isolated visualization tours.

Content addressing survives viewer/backend resets without trusting document IDs,
filenames, mtimes or mutable in-memory geometry. Geometry production is unchanged.
"""
import errno
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.development-artifacts/vr-scene-cache'
MAX_BYTES = 2 * 1024**3
MAX_ENTRIES = 2


def exporter_fingerprint(root=ROOT):
    """Conservatively invalidate on exporter, geometry, template or dependency edits."""
    digest = hashlib.sha256(b'vr-tour-export-v1\0')
    paths = [root/'uv.lock', root/'tools/vr_workflows/snapshot_cache.py',
             root/'tools/vr_workflows/representation_tour.py']
    for directory in ('backend/api', 'backend/core', 'backend/data'):
        paths.extend(p for p in (root/directory).rglob('*')
                     if p.is_file() and p.suffix in {'.py', '.json', '.npz', '.npy', '.pdb'})
    for path in sorted(paths):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _prune(cache):
    entries = sorted(cache.glob('*.nadocvr'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    total = 0
    for index, path in enumerate(entries):
        total += path.stat().st_size
        if index >= MAX_ENTRIES or total > MAX_BYTES:
            path.unlink()
            path.with_suffix('.json').unlink(missing_ok=True)


def prepare(raw, destination, producer, *, cache=CACHE, fingerprint=None, enabled=True):
    """Build atomically or reuse byte-verified output; producer receives stable bytes."""
    started = time.perf_counter()
    if destination.exists():
        raise FileExistsError(destination)
    if not enabled:
        producer(raw, destination)
        return {'cache_hit': False, 'cache_enabled': False, 'export_s': time.perf_counter()-started}
    cache.mkdir(parents=True, exist_ok=True)
    version = fingerprint if fingerprint is not None else exporter_fingerprint()
    key = hashlib.sha256(raw + version.encode()).hexdigest()
    snapshot = cache/(key+'.nadocvr')
    metadata = snapshot.with_suffix('.json')
    # One short-lived exporter at a time; interrupted writers never publish a hit.
    with (cache/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        hit = False
        try:
            info = json.loads(metadata.read_text())
            hit = snapshot.stat().st_size == info['bytes'] and file_digest(snapshot) == info['sha256']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not hit:
            # Remove temporary output left by a forcibly terminated exporter.
            for orphan in cache.glob('.pending-*'):
                if orphan.is_file():
                    orphan.unlink()
            with tempfile.NamedTemporaryFile(dir=cache, prefix='.pending-', delete=False) as stream:
                pending = Path(stream.name)
            try:
                producer(raw, pending)
                info = {'bytes': pending.stat().st_size, 'sha256': file_digest(pending)}
                pending.replace(snapshot)
                metadata.write_text(json.dumps(info))
            finally:
                pending.unlink(missing_ok=True)
        # Hard links avoid copying hundreds of MB and survive cache eviction.
        # Run snapshots are immutable; independent evidence has its own pathname.
        try:
            os.link(snapshot, destination)
        except OSError as error:
            if error.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP):
                raise
            shutil.copyfile(snapshot, destination)
        os.utime(snapshot, None)
        _prune(cache)
    return {'cache_hit': hit, 'cache_enabled': True, 'cache_key': key,
            'export_s': time.perf_counter()-started}
