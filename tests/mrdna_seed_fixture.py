"""Copy only seed inputs before calling an API that reconciles job metadata."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import tempfile


def _fingerprint(path):
    if not path.exists():
        return None
    stat = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return stat.st_size, stat.st_mtime_ns, digest


@contextmanager
def private_seed_job(job, source_workspace, scratch):
    from backend.core.mrdna_runner import resolve_md_seed_inputs

    source = job.job_dir(source_workspace)
    _, psf, dcd = resolve_md_seed_inputs(job, source_workspace)
    inputs = [source / 'job.json', source / 'design.json', psf, psf.with_suffix('.pdb'), dcd]
    if (source / 'display.json').exists():
        inputs.append(source / 'display.json')
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(f'Required mrDNA seed fixture input missing: {path}')
    # No hardlinks/symlinks: the reconciler may replace or overwrite its files.
    before = {p: _fingerprint(p) for p in inputs + [source / '.runtime.lock']}
    names_before = {p.relative_to(source) for p in source.rglob('*')}
    required = sum(before[p][0] for p in inputs)
    if shutil.disk_usage(scratch).free < required + 128 * 1024**2:
        raise RuntimeError('Insufficient scratch space for the private mrDNA seed fixture')
    with tempfile.TemporaryDirectory(prefix='mrdna-seed-', dir=scratch) as directory:
        workspace = Path(directory)
        target = job.job_dir(workspace)
        try:
            for path in inputs:
                copy = target / path.relative_to(source)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, copy)
                assert _fingerprint(copy)[2] == before[path][2], 'Seed input changed during copy'
            yield workspace
        finally:
            assert {p: _fingerprint(p) for p in before} == before, 'Source job inputs or lock changed'
            assert {p.relative_to(source) for p in source.rglob('*')} == names_before, 'Source job namespace changed'
