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
