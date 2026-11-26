"""Storage routing only: placeholders, no molecular documents are authored."""
from pathlib import Path

import pytest

from backend.core import workspace_location as location
from backend.core.workspace import safe_workspace_path
from backend.core.workspace_listing import list_workspace_entries


@pytest.fixture
def storage(tmp_path, monkeypatch):
    checkout = tmp_path / 'checkout'
    shared = checkout / 'workspace' / 'Shared Designs'
    shared.mkdir(parents=True)
    archive = tmp_path / 'archive'
    archive.mkdir()
    (checkout / '.nadoc-workspace').symlink_to(archive, target_is_directory=True)
    (archive / 'Shared Designs').symlink_to(shared, target_is_directory=True)
    monkeypatch.setattr(location, 'PROJECT_ROOT', checkout)
    monkeypatch.delenv('NADOC_WORKSPACE', raising=False)
    return checkout, archive, shared


def test_storage_configuration_and_environment_precedence(storage, monkeypatch):
    checkout, archive, shared = storage
    assert location.default_workspace() == archive
    monkeypatch.setenv('NADOC_WORKSPACE', str(checkout / 'isolated'))
    assert location.default_workspace() == checkout / 'isolated'


def test_unavailable_storage_fails_without_fallback(storage):
    checkout, archive, shared = storage
    (checkout / '.nadoc-workspace').unlink()
    (checkout / '.nadoc-workspace').symlink_to(checkout / 'missing')
    with pytest.raises(RuntimeError, match='unavailable'):
        location.default_workspace()


def test_shared_library_lists_and_reads_through_logical_path(storage):
    checkout, archive, shared = storage
    (shared / 'parts').mkdir()
    (shared / 'parts' / 'example.nadoc').touch()
    (archive / 'local.nadoc').touch()
    paths = {entry['path'] for entry in list_workspace_entries(archive)}
    assert paths == {'Shared Designs', 'Shared Designs/parts',
                     'Shared Designs/parts/example.nadoc', 'local.nadoc'}
    path = safe_workspace_path('Shared Designs/parts/example.nadoc', archive)
    assert path.relative_to(archive).as_posix() == 'Shared Designs/parts/example.nadoc'
    assert path.samefile(shared / 'parts/example.nadoc')
    assert safe_workspace_path('Shared Designs/parts/new.nadoc', archive).parent.samefile(shared / 'parts')


def test_shared_link_does_not_allow_escape_or_other_links(storage):
    checkout, archive, shared = storage
    outside = checkout / 'outside'
    outside.mkdir()
    (outside / 'secret.nadoc').touch()
    (shared / 'escape').symlink_to(outside, target_is_directory=True)
    (archive / 'arbitrary').symlink_to(outside, target_is_directory=True)
    for path in ('Shared Designs/../local.nadoc', 'Shared Designs/escape/secret.nadoc',
                 'arbitrary/secret.nadoc', str(outside / 'secret.nadoc')):
        with pytest.raises(ValueError, match='outside'):
            safe_workspace_path(path, archive)
    paths = {e['path'] for e in list_workspace_entries(archive)}
    assert 'Shared Designs/escape/secret.nadoc' not in paths
    assert 'arbitrary/secret.nadoc' not in paths


def test_wrong_shared_link_is_not_trusted(storage):
    checkout, archive, shared = storage
    (archive / 'Shared Designs').unlink()
    (archive / 'Shared Designs').symlink_to(checkout, target_is_directory=True)
    assert location.linked_shared_root(archive) is None
    with pytest.raises(ValueError, match='outside'):
        safe_workspace_path('Shared Designs/workspace/Shared Designs/file.nadoc', archive)
    assert {e['path'] for e in list_workspace_entries(archive)} == {'Shared Designs'}


def test_runtime_job_lookup_keeps_archive_storage(storage):
    from backend.core.simulation_runtime import job_path

    checkout, archive, shared = storage
    assert job_path('md_jobs', 'example-job', archive) == archive / 'md_jobs/example-job'


def test_identity_scan_includes_trusted_shared_link(storage):
    from backend.api.routes_assembly_workspace import _audit_candidate_files

    checkout, archive, shared = storage
    (shared / 'example.nadoc').touch()
    (shared / '.git').mkdir()
    (shared / '.git/ignored.nadoc').touch()
    assert _audit_candidate_files(archive) == [archive / 'Shared Designs/example.nadoc']


def test_reference_remap_includes_trusted_shared_link(storage):
    import json
    from backend.core.workspace import patch_nass_files

    checkout, archive, shared = storage
    # Metadata-only reference fixture; no molecular structure.
    path = shared / 'references.nass'
    path.write_text(json.dumps({'sources': {'part': {'type': 'file', 'path': 'old.nadoc'}}}))
    assert patch_nass_files(archive, 'old.nadoc', 'new.nadoc') == ['Shared Designs/references.nass']
    assert json.loads(path.read_text())['sources']['part']['path'] == 'new.nadoc'
