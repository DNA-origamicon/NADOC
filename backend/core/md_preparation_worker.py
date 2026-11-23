"""Compute-node entrypoint for the same native package builder and finalizer."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import tarfile
import time
import traceback

from backend.core.alpine_transfer_state import atomic_json
from backend.core.md_preparation_bundle import digest


def main():
    root = Path.cwd()
    output = Path(os.environ.get("NADOC_PREP_OUTPUT_DIR", str(root))).resolve()
    try:
        atomic_json(output / 'progress.json', dict(phase='topology', fraction=0, message='Verifying frozen preparation inputs…'))
        hashes = json.loads((root / 'inputs.json').read_text())
        for name, expected in hashes.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or digest(path) != expected:
                raise ValueError(f'Preparation input hash mismatch: {name}')
        import cloudpickle
        payload = cloudpickle.loads((root / 'request.pkl').read_bytes())
        prepare = payload['prepare']
        if not prepare.__module__.startswith('backend.core.'):
            raise ValueError('Preparation callable is not a NADOC native operation')
        from backend.api.md_request_models import CreateJobRequest
        from backend.core.md_preparation_finalize import finalize_package
        from backend.core.namd_resources import prepare_with_memory_budget
        work = root / 'result'
        work.mkdir(exist_ok=True)
        def progress(phase, fraction=None, message=None):
            atomic_json(output / 'progress.json', dict(phase=phase, fraction=fraction,
                        message=message, updated_at=time.time()))
        kwargs = payload['kwargs']
        kwargs['progress'] = progress
        args = (prepare_with_memory_budget, prepare) if payload['bounded'] else (prepare,)
        subdir, stem, segments = args[0](*args[1:], payload['design'], work, **kwargs)
        finalize_package(work, subdir, stem, CreateJobRequest.model_validate(payload['body']), payload['graphene'])
        package = work / subdir
        files = {str(p.relative_to(work)): digest(p) for p in package.rglob('*') if p.is_file()}
        result = dict(package_subdir=subdir, name_stem=stem,
                      segments=[dataclasses.asdict(s) for s in segments], files=files,
                      input_manifest_sha256=digest(root / 'inputs.json'))
        atomic_json(work / 'result.json', result)
        with tarfile.open(output / 'result.tar.gz', 'w:gz', compresslevel=3) as archive:
            archive.add(package, arcname=subdir)
            archive.add(work / 'result.json', arcname='result.json')
        atomic_json(output / 'status.json', dict(state='complete', archive_sha256=digest(output / 'result.tar.gz')))
    except Exception as exc:
        atomic_json(output / 'status.json', dict(state='failed', error=str(exc), traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
