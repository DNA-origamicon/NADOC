"""Tie native viewers to the backend worker that launched them."""
import os
import signal
import subprocess
import threading

_lock = threading.Lock()
_owned = {}


def track(process, cleanup_thread):
    with _lock:
        _owned[process.pid] = (process, cleanup_thread)


def forget(pid):
    with _lock:
        _owned.pop(pid, None)


def shutdown():
    # Keep Popen ownership rather than trusting a PID from a stale state file.
    with _lock:
        owned = list(_owned.values())
        _owned.clear()
    for process, cleanup in owned:
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
        except ProcessLookupError:
            pass
        # Let the existing owner remove snapshots, IPC files and progress state.
        if cleanup.is_alive():
            cleanup.join(timeout=1)
