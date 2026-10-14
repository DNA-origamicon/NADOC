"""Pin the live viewer executable before recording, outside the capture window."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time


def viewer_identity(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Recording needs a positive viewer PID")
    process = Path(f"/proc/{pid}")
    if process.stat().st_uid != os.getuid():
        raise ValueError("Viewer belongs to another user")

    def start_ticks():
        # comm may contain spaces or parentheses; fields after its last ')' start
        # at field3. Linux process starttime is field22.
        return int((process / "stat").read_text().rsplit(") ", 1)[1].split()[19])

    before = start_ticks()
    executable = process / "exe"
    with executable.open("rb") as stream:
        identity = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = executable.stat()
    if before != start_ticks() or (identity.st_dev, identity.st_ino) != (after.st_dev, after.st_ino):
        raise RuntimeError("Viewer executable or process changed during provenance capture")
    return {"verified": True, "pid": pid, "start_ticks": before,
            "executable": os.readlink(executable), "executable_sha256": digest,
            "executable_bytes": identity.st_size, "captured_monotonic_ns": time.monotonic_ns()}
