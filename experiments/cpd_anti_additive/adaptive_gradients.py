"""Fill spare physical cores after the optimization exits, without timed polling."""

from concurrent.futures import ThreadPoolExecutor
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import time

from scripts.run_local_photoproduct_hessian import _run_task, _completion_state
from experiments.cpd_drude_recovery.campaign import write


def open_pidfd(pid):
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.pidfd_open(int(pid), 0)
    if fd < 0:
        error = ctypes.get_errno()
        if error == errno.ESRCH:
            return None
        raise OSError(error, "pidfd_open")
    return fd


def run(plan_path, root, selected, timings, qm_python, optimization_status):
    plan = json.loads(plan_path.read_text())
    folder = plan_path.parent
    pending = iter(
        [
            t
            for t in plan["tasks"]
            if _completion_state(plan_path=plan_path, root=folder, task=t) == "pending"
        ]
    )
    opt = json.loads(optimization_status.read_text())
    fd = open_pidfd(opt["pid"]) if opt["state"] not in ("complete", "failed") else None
    reader, writer = os.pipe()
    pool = ThreadPoolExecutor(max_workers=4)
    active = {}
    completed = []
    events = []
    workers = selected["workers"]
    threads = selected["threads"]
    released = False

    def release():
        nonlocal workers, threads, released
        # Existing worker threads also need the wider affinity for their next subprocess.
        for task in Path("/proc/self/task").iterdir():
            try:
                os.sched_setaffinity(int(task.name), set(range(16)))
            except ProcessLookupError:
                pass
        fastest = min((2, 3, 4), key=lambda t: timings[t])
        if timings[fastest] < 0.95 * timings[threads]:
            threads = fastest
        workers = 4
        released = True
        events.append(
            dict(
                event="optimization_exited_cores_reclaimed",
                at=time.time(),
                workers=workers,
                threads=threads,
                cpus=list(range(16)),
            )
        )

    def submit():
        while len(active) < workers:
            task = next(pending, None)
            if task is None:
                break
            f = pool.submit(
                _run_task,
                task=task,
                plan_path=plan_path,
                root=folder,
                qm_python=qm_python,
                scratch_root=root / "scratch",
                threads=threads,
                memory_gib=3,
            )
            active[f] = task["id"]
            f.add_done_callback(lambda _: os.write(writer, b"1"))

    try:
        if fd is None:
            release()
        submit()
        while active:
            ready, _, _ = select.select(
                [reader] + ([fd] if fd is not None else []), [], []
            )
            if fd is not None and fd in ready:
                os.close(fd)
                fd = None
                release()
            if reader in ready:
                os.read(reader, 4096)
            for f in list(active):
                if f.done():
                    completed.append(f.result())
                    del active[f]
            write(
                root / "adaptive_progress.json",
                dict(
                    completed_this_run=len(completed),
                    initial_pilot=selected,
                    workers=workers,
                    threads=threads,
                    optimization_cores_reclaimed=released,
                    events=events,
                    completed_records=completed,
                ),
            )
            submit()
        pool.shutdown(wait=True)
    except BaseException:
        for f in active:
            f.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        os.close(reader)
        os.close(writer)
        if fd is not None:
            os.close(fd)
