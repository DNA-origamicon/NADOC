"""Portable source relocation preserves recorded dependency identity."""
import hashlib
import json
from pathlib import Path

import pytest

from backend.core.shared_design_paths import resolve_shared_source


def fixture(root):
    shared = root / 'Shared Designs'
    shared.mkdir()
    target = shared / 'part.nadoc'
    target.write_bytes(b'recorded source bytes')
    old = 'Shared Designs/old/run/part.nadoc'
    entry = {'path': 'Shared Designs/part.nadoc', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    manifest = shared / '.relocations.json'
    manifest.write_text(json.dumps({'version': 1, 'files': {old: entry}}))
    return target, old, entry, manifest


def test_resolves_exact_dependency_and_preserves_original_precedence(tmp_path):
    target, old, _, _ = fixture(tmp_path)
    assert resolve_shared_source(tmp_path, old) == target
    assert resolve_shared_source(tmp_path, 'missing.nadoc') == tmp_path / 'missing.nadoc'
    original = tmp_path / old
    original.parent.mkdir(parents=True)
    original.write_bytes(b'original')
    assert resolve_shared_source(tmp_path, old) == original


def test_changed_dependency_fails_closed(tmp_path):
    target, old, _, _ = fixture(tmp_path)
    target.write_bytes(b'different design')
    with pytest.raises(ValueError, match='source changed'):
        resolve_shared_source(tmp_path, old)


@pytest.mark.parametrize('destination', ['../outside.nadoc', '/tmp/outside.nadoc', 'Other/part.nadoc', 'Shared Designs/../outside.nadoc'])
def test_manifest_cannot_escape_shared_folder(tmp_path, destination):
    _, old, entry, manifest = fixture(tmp_path)
    entry['path'] = destination
    manifest.write_text(json.dumps({'version': 1, 'files': {old: entry}}))
    with pytest.raises(ValueError, match='escapes'):
        resolve_shared_source(tmp_path, old)


def test_runtime_shared_symlink_supported_but_escape_rejected(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    target, old, _, _ = fixture(checkout)
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (runtime / 'Shared Designs').symlink_to(checkout / 'Shared Designs', target_is_directory=True)
    assert resolve_shared_source(runtime, old) == target
    target.unlink()
    outside = tmp_path / 'outside.nadoc'
    outside.write_bytes(b'recorded source bytes')
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='escapes'):
        resolve_shared_source(runtime, old)


def test_assembly_edit_cannot_recreate_historical_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from backend.api import assembly
    _, old, _, _ = fixture(tmp_path)
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    instance = SimpleNamespace(source=SimpleNamespace(type='file', path=old))
    with pytest.raises(HTTPException) as error:
        assembly._replace_instance_design(None, instance, None)
    assert error.value.status_code == 409
    assert not (tmp_path / old).parent.exists()
