"""Resource detection must avoid active simulations and unknown GPU telemetry."""
import os
from pathlib import Path
from types import SimpleNamespace

from backend.physics import em_resources


def fake_host(tmp_path, monkeypatch, *, simulation=False, compute='', utilization=0):
    proc = tmp_path/'proc'; proc.mkdir()
    (proc/'cpuinfo').write_text('\n\n'.join(f'processor: {i}\nphysical id: 0\ncore id: {i//2}' for i in range(12)))
    (proc/'meminfo').write_text('MemAvailable: 16777216 kB\n')
    if simulation:
        folder = proc/'123'; folder.mkdir(); (folder/'comm').write_text('oxDNA\n')
    real_path = Path
    monkeypatch.setattr(em_resources, 'Path', lambda path: proc/str(path)[6:] if str(path).startswith('/proc/') else
                        proc if str(path) == '/proc' else real_path(path))
    monkeypatch.setattr(em_resources.os, 'sched_getaffinity', lambda pid: set(range(12)))
    monkeypatch.setattr(em_resources.os, 'getloadavg', lambda: (0., 0., 0.))
    monkeypatch.setattr(em_resources.shutil, 'which', lambda name: '/fake/nvidia-smi')
    def run(args, **kwargs):
        return SimpleNamespace(stdout=compute if 'pid' in args[1] else f'0, {utilization}, 6000\n')
    monkeypatch.setattr(em_resources.subprocess, 'run', run)


def test_simulation_reserves_gpu_and_caps_cpu(tmp_path, monkeypatch):
    fake_host(tmp_path, monkeypatch, simulation=True)
    observed = em_resources.observe()
    assert observed['simulation_pids'] == [123]
    assert observed['cpu_workers'] == 2
    assert not observed['gpu']['safe']


def test_idle_machine_and_external_gpu_process(tmp_path, monkeypatch):
    fake_host(tmp_path, monkeypatch, compute='999999\n')
    assert not em_resources.observe()['gpu']['safe']
    monkeypatch.setattr(em_resources.subprocess, 'run', lambda args, **kwargs:
                        SimpleNamespace(stdout='' if 'pid' in args[1] else '0, 0, 6000\n'))
    observed = em_resources.observe()
    assert observed['gpu']['safe'] and observed['cpu_workers'] == 4


def test_own_gpu_usage_does_not_trigger_false_contention(tmp_path, monkeypatch):
    fake_host(tmp_path, monkeypatch, compute=f'{os.getpid()}\n', utilization=80)
    assert em_resources.observe()['gpu']['safe']


def test_unknown_gpu_and_low_memory_are_conservative(tmp_path, monkeypatch):
    fake_host(tmp_path, monkeypatch)
    (tmp_path/'proc'/'meminfo').write_text('MemAvailable: 2097152 kB\n')
    monkeypatch.setattr(em_resources.shutil, 'which', lambda name: None)
    observed = em_resources.observe()
    assert not observed['gpu']['safe'] and observed['cpu_workers'] == 1
