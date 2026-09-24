"""Linux completion events and deadline-based supervision without periodic polling."""

import ctypes
import os
import select
import struct


class CompletionEvents:
    def __init__(self, folder, pid=None):
        libc = ctypes.CDLL(None, use_errno=True)
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        # Atomic replacement, close after direct write, and deletion.
        if (
            libc.inotify_add_watch(self.fd, os.fsencode(folder), 0x80 | 0x08 | 0x200)
            < 0
        ):
            os.close(self.fd)
            raise OSError(ctypes.get_errno(), "inotify_add_watch")
        self.pidfd = None
        if pid:
            try:
                self.pidfd = os.pidfd_open(pid)
            except ProcessLookupError:
                pass

    def wait(self, timeout=None):
        ready, _, _ = select.select(
            [self.fd] + ([self.pidfd] if self.pidfd is not None else []),
            [],
            [],
            timeout,
        )
        events = set()
        if self.pidfd in ready:
            events.add("process_exit")
            os.close(self.pidfd)
            self.pidfd = None
        if self.fd in ready:
            data = os.read(self.fd, 65536)
            offset = 0
            while offset < len(data):
                _, mask, _, length = struct.unpack_from("iIII", data, offset)
                name = data[offset + 16 : offset + 16 + length].split(b"\0")[0].decode()
                if name == "status.json" or mask & 0x4000:
                    events.add("status")
                offset += 16 + length
        if not ready:
            events.add("deadline")
        return events

    def close(self):
        os.close(self.fd)
        if self.pidfd is not None:
            os.close(self.pidfd)


def deadline_seconds(expected_seconds, grace_seconds=300):
    if expected_seconds <= 0 or grace_seconds < 0:
        raise ValueError("Expected runtime must be positive; grace must be nonnegative")
    return expected_seconds + max(grace_seconds, expected_seconds * 0.5)
