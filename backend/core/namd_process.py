"""Identify native NAMD processes without matching shell scripts that mention them."""

import os


def is_segment_command(cmdline: bytes, segment: str) -> bool:
    argv = [arg for arg in cmdline.split(b"\0") if arg]
    if not argv:
        return False
    executable = os.path.basename(argv[0]).lower()
    if executable not in (b"namd", b"namd2", b"namd3", b"srun"):
        return False
    stem = segment.encode()
    return any(
        os.path.basename(arg) == stem + b".conf"
        or (
            os.path.basename(arg).startswith(stem + b".resume")
            and arg.endswith(b".conf")
        )
        for arg in argv[1:]
    )
