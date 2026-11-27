"""Conservative, read-only resource observations for optional EM trajectory work."""
import os
from pathlib import Path
import shutil
import subprocess


def observe():
    logical = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
    physical = max(1, logical // 2)  # conservative fallback when topology unavailable
    active = []
    try:
        for path in Path('/proc').glob('[0-9]*/comm'):
            try:
                if path.read_text().strip().lower() in ('oxdna', 'gmx', 'gmx_mpi', 'namd2', 'namd3', 'lmp'):
                    active.append(int(path.parent.name))
            except OSError:
                pass
        info = Path('/proc/cpuinfo').read_text()
        cores = set()
        allowed = os.sched_getaffinity(0) if hasattr(os, 'sched_getaffinity') else None
        for block in info.split('\n\n'):
            fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
            fields = {k.strip(): v.strip() for k, v in fields.items()}
            if 'core id' in fields and (allowed is None or int(fields['processor']) in allowed):
                cores.add((fields.get('physical id', '0'), fields['core id']))
        physical = len(cores) or physical
    except OSError:
        pass
    try:
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        available_gib = int(memory['MemAvailable'].split()[0]) / 1024**2
    except (OSError, KeyError, ValueError):
        available_gib = 2.  # unknown memory: permit only one worker
    load = os.getloadavg()[0] if hasattr(os, 'getloadavg') else physical / 2
    # Reserve two physical cores and 1 GiB; allow ~1 GiB per bounded frame worker.
    workers = max(1, min(4, physical - 2, int(available_gib - 1),
                         max(1, physical - int(load) - 1)))
    if active:
        workers = min(workers, 2)
    if available_gib < 2:
        workers = 0
    gpu = {'safe': False, 'reason': 'GPU telemetry unavailable'}
    smi = shutil.which('nvidia-smi')
    if smi:
        try:
            query = subprocess.run([smi, '--query-gpu=index,utilization.gpu,memory.free',
                                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
            rows = [[float(v.strip()) for v in line.split(',')] for line in query.stdout.splitlines()]
            processes = subprocess.run([smi, '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                                       capture_output=True, text=True, timeout=3, check=True)
            # Exclude this process and descendants (our own persistent workers).
            owned = {os.getpid()}
            parents = {}
            for path in Path('/proc').glob('[0-9]*/status'):
                try:
                    fields = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
                    parents[int(path.parent.name)] = int(fields['PPid'])
                except (OSError, KeyError, ValueError):
                    pass
            for _ in range(8):
                owned.update(pid for pid, parent in parents.items() if parent in owned)
            pids = [int(line.strip()) for line in processes.stdout.splitlines() if line.strip().isdigit()]
            external = [pid for pid in pids if pid not in owned]
            own_gpu = any(pid in owned for pid in pids)
            safe = bool(rows) and not active and not external and all(
                (own_gpu or r[1] < 20) and r[2] >= 2048 for r in rows)
            gpu = {'safe': safe, 'reason': 'idle GPU with memory headroom' if safe else
                   'GPU busy, simulation active, or insufficient GPU memory', 'devices': rows,
                   'external_compute_pids': external}
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {'cpu_workers': workers, 'physical_cores': physical, 'logical_cpus': logical,
            'available_memory_gib': available_gib, 'load_average': load,
            'simulation_pids': active, 'gpu': gpu}
