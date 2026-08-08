"""Is this process a child of a hot-reloading dev server?

Exists for exactly one decision, and it is a money decision.

``main.lifespan`` destroys every RunPod pod it still owns on shutdown, because once the
process is gone nothing is watching the pod and it bills on. (Since the key moved to disk
the NEXT startup does reap orphans — but that is a safety net for a crash, not a licence to
leave pods up when the user has closed the app.) That is right for a real
shutdown and **wrong for a dev-server reload** — `just dev` runs uvicorn with
``--reload --reload-dir backend``, so editing any backend file tears the server down and
takes a live, paid, multi-day GPU run with it. Measured: a 200 ns production died at 0.4%
because a source file was saved.

A reload is indistinguishable from a shutdown *inside* the child — uvicorn sets no marker
and the signal is the same SIGTERM. What IS visible is the ancestry: the reloader
supervisor is still `uvicorn ... --reload` and the server runs as its (multiprocessing
spawn) child. So we walk up ``/proc`` looking for it.

**Fails toward the expensive-but-safe answer.** Any doubt — unreadable ``/proc``, a
non-Linux host, a truncated chain — returns False, which means "terminate the pods". A
leaked pod bills forever; a killed dev run costs minutes and is resumable from the volume.
"""

from __future__ import annotations

import os

# The reloader is the server's parent (spawn) or grandparent (under `uv run`). Six is
# generous enough for a wrapper or two without walking to init on a weird host.
_MAX_DEPTH = 6

_MARKERS = ("--reload", "--reload-dir")


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().decode("utf-8", "replace").replace("\0", " ")
    except OSError:
        return ""


def parse_ppid(raw: str) -> int:
    """Parent pid out of a ``/proc/<pid>/stat`` line; 0 when it cannot be read.

    Split on the LAST ``)``, never ``raw.split()[3]``: field 2 is the executable name in
    parentheses and it may contain both spaces and parentheses. NAMD renames itself
    "NAMD masterPe", which is exactly the shape that breaks the naive split.
    """
    try:
        return int(raw[raw.rindex(")") + 1 :].split()[1])
    except (ValueError, IndexError):
        return 0


def _ppid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            return parse_ppid(fh.read().decode("utf-8", "replace"))
    except OSError:
        return 0


def under_reloader(pid: int | None = None, *, max_depth: int = _MAX_DEPTH) -> bool:
    """True when a uvicorn ``--reload`` supervisor is an ancestor of this process.

    Used to decide whether a shutdown is a RELOAD (hand the pods to the next process,
    which re-attaches) or a real exit (destroy them now). Never raises.
    """
    cur = os.getpid() if pid is None else pid
    for _ in range(max_depth):
        cmd = _cmdline(cur)
        if not cmd:
            return False
        if any(m in cmd for m in _MARKERS):
            return True
        nxt = _ppid(cur)
        if nxt <= 1 or nxt == cur:
            return False
        cur = nxt
    return False
