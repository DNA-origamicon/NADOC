"""Small, idle-expiring pool of killable playback interpreters.

A busy worker is owned exclusively by md_analysis_runner; cancellation still kills
its complete process group. Only successful, idle workers enter this bounded pool.
"""
import signal
import threading
import time

_idle = []
_lock = threading.Lock()
_MAX_IDLE = 1


def _serve(connection):
    from backend.core.md_analysis_runner import _target
    try:
        while connection.poll(30):
            command = connection.recv()
            _target(*command)
            signal.alarm(0)
            connection.send(True)
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


def acquire(context):
    from backend.core.md_analysis_runner import _kill

    with _lock:
        while _idle:
            process, connection, since = _idle.pop()
            if process.is_alive() and time.monotonic() - since < 25:
                return process, connection
            _kill(process)
            process.join()
            connection.close()
    parent, child = context.Pipe()
    process = context.Process(target=_serve, args=(child,), daemon=True)
    process.start()
    child.close()
    return process, parent


def release(process, connection):
    from backend.core.md_analysis_runner import _kill
    from backend.core.memory_budget import simulation_active
    # A running simulation already pays for health overlap. Do not retain an
    # additional playback interpreter between user requests during that run.
    try:
        retain=not simulation_active()
    except MemoryError:
        retain=False
    with _lock:
        keep = retain and process.is_alive() and len(_idle) < _MAX_IDLE
        if keep:
            _idle.append((process, connection, time.monotonic()))
    if not keep:
        _kill(process)
        connection.close()


def close():
    from backend.core.md_analysis_runner import _kill
    with _lock:
        workers = list(_idle)
        _idle.clear()
    for process, connection, _since in workers:
        _kill(process)
        connection.close()


from backend.core.memory_budget import register_reclaimer
register_reclaimer('idle_playback_workers', close)
