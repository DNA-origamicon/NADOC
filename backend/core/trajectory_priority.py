"""Cross-process foreground leases for interruptible trajectory backfill.

Linux cannot generally undo an unprivileged nice(19). Hand work back to the normal
interactive process instead of trapping a user behind a low-priority cache lock.
Kernel leases survive neither a crash nor cancellation, unlike sentinel files.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import tempfile
import threading

PREEMPTED = 75
BACKFILL_PROCESS = False  # enabled only by the disposable worker entry point


def _directory():
    directory = Path(tempfile.gettempdir()) / f"nadoc-analysis-demand-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


@contextmanager
def foreground_work():
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=_directory())
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        published = Path(name).with_name(Path(name).name.replace(".pending-", "request-", 1))
        os.replace(name, published)
        name = str(published)
        yield
    finally:
        # Unlink while still locked: a scanner cannot mistake a newly reused name
        # for an abandoned request. A killed process simply leaves an unlocked file.
        Path(name).unlink(missing_ok=True)
        os.close(fd)


def foreground_active():
    for path in _directory().glob("request-*"):
        try:
            with path.open("r") as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                # Requests become visible only after locking. An unlocked lease is
                # abandoned by a crashed/cancelled process, and can be removed safely.
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    return False


@contextmanager
def interruptible_backfill():
    """Only enter in the disposable worker process, never in the API server."""
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            if foreground_active():
                # Release every nested analysis lock promptly, even inside native
                # trajectory readers. Atomic cache publication protects finished work.
                os._exit(PREEMPTED)
            stop.wait(0.05)

    thread = threading.Thread(target=monitor, name="analysis-demand", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
