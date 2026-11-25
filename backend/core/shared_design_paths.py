"""Read-only relocation of immutable shared inputs without rewriting feature logs."""
from pathlib import Path
import hashlib
import json


def resolve_shared_source(workspace: Path, source: str | Path) -> Path:
    """Resolve a missing historical source through the shared relocation manifest.

    Ordinary existing files take precedence. Aliases are contained in Shared
    Designs and bind exact bytes: replacing an archived dependency requires an
    explicit new source operation, never silently changing historical inputs.
    This helper must not be used to choose save/write destinations.
    """
    workspace, source = Path(workspace), Path(source)
    candidate = workspace / source
    if candidate.is_file() or source.is_absolute() or '..' in source.parts:
        return candidate
    if not source.parts or source.parts[0] != 'Shared Designs':
        return candidate
    shared = (workspace / 'Shared Designs').resolve()
    manifest = shared / '.relocations.json'
    if not manifest.is_file():
        return candidate
    data = json.loads(manifest.read_text())
    if data.get('version') != 1:
        raise ValueError('Unsupported shared design relocation manifest')
    entry = data['files'].get(source.as_posix())
    if entry is None:
        return candidate
    target = Path(entry['path'])
    if not target.parts or target.is_absolute() or '..' in target.parts or target.parts[0] != 'Shared Designs':
        raise ValueError('Shared design relocation escapes Shared Designs')
    resolved = (workspace / target).resolve()
    if not resolved.is_relative_to(shared):
        raise ValueError('Shared design relocation escapes Shared Designs')
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError(f'Shared design relocation source changed: {source}')
    return resolved
