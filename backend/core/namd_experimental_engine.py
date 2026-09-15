"""Resolve an explicitly recorded experimental electrode engine without global changes."""
import hashlib
import json
import os
from pathlib import Path


def experimental_engine(job, package):
    requested=(job.prep_params or {}).get('experimental_namd_binary')
    if not requested:
        return None
    manifest=json.loads((Path(package)/'manifest.json').read_text())
    provenance=manifest.get('experimental_validation',{})
    binary=Path(requested).expanduser().resolve()
    if not manifest.get('two_electrodes') or provenance.get('binary')!=str(binary):
        raise RuntimeError('Experimental electrode engine is missing matching package provenance.')
    if not binary.is_file() or not os.access(binary,os.X_OK):
        raise RuntimeError(f'Experimental electrode engine is unavailable: {binary}')
    expected=provenance.get('binary_sha256')
    if not expected or hashlib.sha256(binary.read_bytes()).hexdigest()!=expected:
        raise RuntimeError('Experimental electrode engine checksum changed; revalidate the binary before restarting.')
    return str(binary)
