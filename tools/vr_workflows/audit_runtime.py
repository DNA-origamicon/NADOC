"""Boundary resource evidence and explicit resets for an exclusive VR audit."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import json
import signal


def numbers(path):
    values={}
    for line in Path(path).read_text().splitlines():
        fields=line.split()
        if len(fields)>1:
            try:values[fields[0].rstrip(':')]=int(fields[1])
            except ValueError:pass
    return values


def scope_memory():
    """Read this validation scope's pressure, including retained capture pages."""
    try:
        relative=next(line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        root=Path('/sys/fs/cgroup')/relative.lstrip('/')
        values={name:(root/name).read_text().strip() for name in ('memory.current','memory.peak','memory.high','memory.max')}
        return {**values,'events':numbers(root/'memory.events')}
    except (OSError,StopIteration):
        return None


def resources():
    memory=numbers('/proc/meminfo');vm=numbers('/proc/vmstat')
    shared=shutil.disk_usage('/dev/shm')
    return dict(epoch_ms=time.time()*1000,mem_available_kib=memory['MemAvailable'],
                mem_total_kib=memory['MemTotal'],swap_free_kib=memory['SwapFree'],
                swap_total_kib=memory['SwapTotal'],shm_used_bytes=shared.used,
                pswpin_pages=vm['pswpin'],pswpout_pages=vm['pswpout'],scope_memory=scope_memory())


def pressure(before,after):
    return dict(swap_in_pages=max(0,after['pswpin_pages']-before['pswpin_pages']),
                swap_out_pages=max(0,after['pswpout_pages']-before['pswpout_pages']),
                shm_growth_bytes=after['shm_used_bytes']-before['shm_used_bytes'])


def client_processes():
    found=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():continue
        try:
            if process.stat().st_uid==os.getuid() and (process/'comm').read_text().strip() in (
                'steam','steamwebhelper','vrserver','vrcompositor','vrmonitor'):
                found.append(int(process.name))
        except OSError:pass
    return found


def restart(output):
    """Gracefully reset the owned Steam client stack, never an active viewer.

    Opt-in only: this closes Steam's UI too. Intended for the exclusive audit
    runtime, not a shared session with another running Steam application.
    No process is force-killed and no shared-memory files are deleted.
    """
    from backend.api import routes_vr as vr
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active():raise RuntimeError('Refusing runtime reset with an active viewer')
    record={'before':resources(),'previous_client_pids':client_processes()}
    try:
        if record['previous_client_pids']:
            # Steam closes the server/compositor but its -nokillprocess monitor
            # can survive. Close the owned dashboard normally before the client.
            record['terminated_monitor_pids']=[]
            for pid in record['previous_client_pids']:
                try:
                    if Path(f'/proc/{pid}/comm').read_text().strip()=='vrmonitor':
                        os.kill(pid,signal.SIGTERM)
                        record['terminated_monitor_pids'].append(pid)
                except (FileNotFoundError,ProcessLookupError):pass
            subprocess.run(['steam','-shutdown'],check=True,timeout=30)
            deadline=time.monotonic()+30
            while client_processes() and time.monotonic()<deadline:time.sleep(.2)
            if client_processes():raise RuntimeError('Steam client did not close; refusing forced cleanup')
        record['after_shutdown']=resources()
        vr._start_steamvr()
        record['after_start']=resources()
        record['passed']=True
    except Exception as error:
        record.update(passed=False,error=str(error));raise
    finally:Path(output).write_text(json.dumps(record,indent=2))
