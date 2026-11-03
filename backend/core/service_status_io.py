"""Bounded read-only status metadata; never accept pipes/devices as status files."""
import os
from pathlib import Path
import stat

from backend.core.part_document_io import MAX_METADATA_BYTES


class StatusReadLimit(RuntimeError):
    """Escape handlers that treat ordinary missing/malformed status as inactive."""


class StatusReader:
    def __init__(self):
        self.remaining = MAX_METADATA_BYTES

    def __call__(self, path):
        fd = os.open(Path(path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StatusReadLimit('Status input must be a regular file')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                value = stream.read(self.remaining + 1)
            if len(value) > self.remaining:
                raise StatusReadLimit('Status metadata exceeds the cumulative byte allowance')
            self.remaining -= len(value)
            return value.decode('utf-8')
        finally:
            os.close(fd)
