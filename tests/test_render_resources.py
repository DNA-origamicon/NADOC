"""Resource-based export admission, including parent container constraints."""
from pathlib import Path
from types import SimpleNamespace

from backend.rendering import resources


def test_memory_honors_tightest_ancestor_and_current_use(monkeypatch):
    monkeypatch.setattr(resources.psutil, 'virtual_memory', lambda: SimpleNamespace(available=1000))
    contents = {
        '/proc/self/cgroup': '0::/parent/child',
        '/sys/fs/cgroup/parent/child/memory.max': '900',
        '/sys/fs/cgroup/parent/child/memory.current': '100',
        '/sys/fs/cgroup/parent/memory.max': '700',
        '/sys/fs/cgroup/parent/memory.current': '500',
        '/sys/fs/cgroup/memory.max': 'max',
    }
    monkeypatch.setattr(Path, 'read_text', lambda self, *args, **kwargs: contents[str(self)])
    assert resources.available_memory() == 200
    contents['/sys/fs/cgroup/parent/memory.current'] = '650'
    assert resources.available_memory() == 50


def test_native_host_uses_os_memory_and_current_scratch_without_fixed_ceiling(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(Path, 'read_text', unavailable)
    monkeypatch.setattr(resources.psutil, 'virtual_memory', lambda: SimpleNamespace(available=3*1024**3))
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _: SimpleNamespace(free=2*1024**3))
    assert resources.upload_capacity('/scratch') == {
        'available_memory_bytes':3*1024**3, 'scratch_free_bytes':2*1024**3,
        'upload_limit_bytes':2*1024**3, 'free_gpu_memory_bytes':None,
    }
