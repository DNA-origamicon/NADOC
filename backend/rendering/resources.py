"""Observed host/container capacity for disposable rendering transfers.

This is not a VRAM estimate or a guarantee that Cycles can allocate a scene.
Do not substitute a fixed triangle, RAM percentage or upload ceiling here.
"""
from pathlib import Path
import shutil

import psutil


def available_memory():
    available = psutil.virtual_memory().available
    # Respect a process's cgroup and every ancestor, including validation scopes.
    try:
        relative = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        root = Path('/sys/fs/cgroup')
        directory = root / relative.lstrip('/')
        while directory.is_relative_to(root):
            maximum = (directory / 'memory.max').read_text().strip()
            if maximum != 'max':
                available = min(available, max(0, int(maximum) - int((directory / 'memory.current').read_text())))
            if directory == root:
                break
            directory = directory.parent
    except (OSError, ValueError, StopIteration):
        pass  # Windows/macOS or a host without cgroup v2: use OS capacity.
    return int(available)


def upload_capacity(directory):
    memory = available_memory()
    disk = shutil.disk_usage(directory).free
    return {'available_memory_bytes': memory, 'scratch_free_bytes': disk,
            'upload_limit_bytes': min(memory, disk), 'free_gpu_memory_bytes': None}
