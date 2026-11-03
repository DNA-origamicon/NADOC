"""Drive discovery and Windows path input for the archive folder picker."""
import subprocess
from pathlib import Path

from backend.api import routes_fs as fs


def test_windows_path_is_translated_without_shell(monkeypatch, tmp_path):
    monkeypatch.setattr(fs, '_is_wsl', lambda: True)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, str(tmp_path) + '\n', '')
    monkeypatch.setattr(fs.subprocess, 'run', run)
    result = fs.fs_listdir(r'F:\Simulation files')
    assert result['path'] == str(tmp_path)
    assert calls[0][0] == ['wslpath', '-u', r'F:\Simulation files']
    assert 'shell' not in calls[0][1]


def test_locations_include_mounted_external_drive_and_capacity(monkeypatch, tmp_path):
    drive = tmp_path / 'External SSD'
    drive.mkdir()
    monkeypatch.setattr(fs, '_mounted_paths', lambda: [drive, tmp_path / 'disconnected'])
    locations = fs._locations()
    entry = next(x for x in locations if x['path'] == str(drive))
    assert entry['name'] == 'Drive: External SSD'
    assert entry['total_bytes'] > 0
    assert 'free_bytes' in entry
    assert not any(x['path'] == str(tmp_path / 'disconnected') for x in locations)


def test_mount_paths_decode_spaces_and_exclude_wsl_internals(monkeypatch):
    monkeypatch.setattr(fs.os, 'name', 'posix')
    monkeypatch.setattr(Path, 'read_text', lambda self: (
        '1 0 0:1 / /mnt/f rw - 9p F: rw\n'
        '2 0 0:2 / /media/user/External\\040SSD rw - ext4 /dev/sde rw\n'
        '3 0 0:3 / /mnt/wslg rw - tmpfs tmpfs rw\n'
        '4 0 0:4 / /mnt/wsl/PHYSICALDRIVE2p1 rw - ext4 /dev/sde1 rw\n'
    ))
    assert fs._mounted_paths() == [Path('/media/user/External SSD'), Path('/mnt/f'), Path('/mnt/wsl/PHYSICALDRIVE2p1')]


def test_directory_picker_preserves_order_hidden_and_symlink_rules(tmp_path):
    import pytest
    for name in ('zeta', 'Alpha', 'alpha', '.hidden'):
        (tmp_path / name).mkdir()
    (tmp_path / 'file').write_text('not a folder')
    try:
        (tmp_path / 'linked').symlink_to(tmp_path / 'zeta', target_is_directory=True)
        (tmp_path / 'broken').symlink_to(tmp_path / 'absent')
    except OSError:
        pytest.skip('Symlinks unavailable')
    expected = [dict(name=p.name, path=str(p)) for p in sorted(tmp_path.iterdir(), key=lambda p: p.name.lower()) if not p.name.startswith('.') and p.is_dir()]
    assert fs._list_dir(tmp_path)['entries'] == expected


def test_directory_picker_status_and_unreadable_entries(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        fs._list_dir(tmp_path / 'missing')
    assert error.value.status_code == 404
    file = tmp_path / 'file'
    file.touch()
    with pytest.raises(HTTPException) as error:
        fs._list_dir(file)
    assert error.value.status_code == 400

    class Entry:
        name = 'unreadable'
        def is_dir(self):
            raise PermissionError('entry denied')
    class Scan:
        def __enter__(self):
            return iter([Entry()])
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(fs.os, 'scandir', lambda path: Scan())
    assert fs._list_dir(tmp_path)['entries'] == []
    def denied(path):
        raise PermissionError('directory denied')
    monkeypatch.setattr(fs.os, 'scandir', denied)
    with pytest.raises(HTTPException) as error:
        fs._list_dir(tmp_path)
    assert error.value.status_code == 403
