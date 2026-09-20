"""Lossless compressed JSON evidence, with legacy plain-JSON read compatibility."""
from __future__ import annotations

import gzip
import json
import os
import tempfile
from pathlib import Path


def json_artifact_exists(path: Path) -> bool:
    path = Path(path)
    return path.is_file() or path.with_suffix(path.suffix + '.gz').is_file()


def read_json_artifact(path: Path):
    """Prefer a freshly generated plain file over an older compressed archive."""
    path = Path(path)
    if path.is_file():
        data = path.read_bytes()
        return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)
    return json.loads(gzip.decompress(path.with_suffix(path.suffix + '.gz').read_bytes()))


def write_json_artifact(path: Path, payload, *, compressed: bool = False) -> Path:
    path = Path(path)
    plain_path = path
    data = (json.dumps(payload, indent=2) + '\n').encode()
    if compressed:
        path = path.with_suffix(path.suffix + '.gz')
        data = gzip.compress(data, mtime=0)
    # Publish complete bytes before removing the legacy representation.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if compressed:
        plain_path.unlink(missing_ok=True)
    return path
