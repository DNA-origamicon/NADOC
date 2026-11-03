"""Request-local limits for observational job evidence (no persistent cache).

Deadlines are cooperative between local filesystem calls, not a syscall timeout.
Callers must not admit network paths or treat this as a qualified HTTP boundary.
"""
import os
from pathlib import Path
import stat
import time

from backend.core.part_document_io import MAX_METADATA_BYTES

MAX_ENTRIES = 4096
MAX_WORK = 30000
MAX_TEXT = 16384
MAX_COMMAND = 4096
MAX_SECONDS = 5


class EvidenceUnavailable(RuntimeError):
    """Must escape native helpers' missing/malformed-file fallbacks."""


class Evidence:
    def __init__(self, proc_root=Path('/proc'), *, cancelled=None):
        self.proc_root = Path(proc_root)
        self.cancelled = cancelled
        self.remaining = MAX_METADATA_BYTES
        self.work = MAX_WORK
        self.deadline = time.monotonic() + MAX_SECONDS
        self._processes = None
        self.processes_complete = True
        self.process_ids = set()
        self.process_commands = {}

    def tick(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise EvidenceUnavailable('cancelled')
        self.work -= 1
        if self.work < 0 or time.monotonic() > self.deadline:
            raise EvidenceUnavailable('work_budget')

    def open_regular(self, path, flags=os.O_RDONLY):
        self.tick()
        fd = os.open(path, flags | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise EvidenceUnavailable('non_regular_file')
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, path, limit=MAX_TEXT, *, prefix=False):
        self.tick()
        if self.remaining < limit + (not prefix):
            raise EvidenceUnavailable('byte_budget')
        try:
            fd = self.open_regular(path)
            try:
                with os.fdopen(fd, 'rb', closefd=False) as stream:
                    data = stream.read(limit + (not prefix))
            finally:
                os.close(fd)
        except FileNotFoundError:
            raise  # native helpers deliberately interpret absence
        except OSError as exc:
            raise EvidenceUnavailable('unreadable_file') from exc
        self.remaining -= len(data)
        self.tick()
        if len(data) > limit:
            raise EvidenceUnavailable('file_budget')
        return data

    def text(self, path):
        return self.read(path).decode('utf-8', errors='replace')

    def json_text(self, path):
        # At most 16 KiB bounds scalar/container count before json.loads. Limit
        # nesting before parsing as well, independent of Python's recursion limit.
        try:
            text = self.read(path).decode('utf-8')
        except UnicodeError as exc:
            raise EvidenceUnavailable('unreadable_encoding') from exc
        depth = 0
        quoted = escaped = False
        for character in text:
            self.tick()
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in '[{':
                depth += 1
                if depth > 64:
                    raise EvidenceUnavailable('nesting_budget')
            elif character in ']}':
                depth -= 1
        return text

    def exists(self, path):
        self.tick()
        try:
            Path(path).stat()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise EvidenceUnavailable('unreadable_file') from exc

    def entries(self, path):
        self.tick()
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                self.tick()
                if index >= MAX_ENTRIES:
                    raise EvidenceUnavailable('entry_budget')
                yield entry

    def processes(self):
        """One bounded inventory; incomplete negative evidence is never false."""
        if self._processes is not None:
            return self._processes
        self._processes = []
        try:
            for entry in self.entries(self.proc_root):
                if not entry.name.isdigit():
                    continue
                if len(entry.name) > 10:
                    self.processes_complete = False
                    continue
                pid = int(entry.name)
                self.process_ids.add(pid)
                path = Path(entry.path)
                try:
                    command = self.read(path / 'cmdline', MAX_COMMAND)
                except FileNotFoundError:
                    continue  # exited during snapshot
                except EvidenceUnavailable:
                    self.processes_complete = False
                    continue
                self.process_commands[pid] = command
                if not any(token in command.lower() for token in (b'namd', b'srun', b'arbd', b'oxdna')):
                    continue
                cwd = None
                try:
                    self.tick()
                    target = os.readlink(path / 'cwd')
                    if len(target) > MAX_COMMAND:
                        raise EvidenceUnavailable('path_budget')
                    self.remaining -= len(target.encode())
                    if self.remaining < 0:
                        raise EvidenceUnavailable('byte_budget')
                    cwd = (path / target).resolve()
                except (OSError, EvidenceUnavailable):
                    self.processes_complete = False
                self._processes.append((command, cwd))
        except (OSError, EvidenceUnavailable):
            self.processes_complete = False
        return self._processes

    def pid_evidence(self, pid, *, command=False):
        self.tick()
        if pid is None or pid == 0:
            return b'' if command else False
        if type(pid) is not int or not 0 < pid < 2**31:
            raise EvidenceUnavailable('invalid_pid')
        self.processes()
        self.tick()
        if command and pid in self.process_commands:
            return self.process_commands[pid]
        if not command and pid in self.process_ids:
            return True
        if not self.processes_complete:
            raise EvidenceUnavailable('process_inventory_incomplete')
        return b'' if command else False

    def size(self, path):
        self.tick()
        try:
            return Path(path).stat().st_size
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise EvidenceUnavailable('unreadable_file') from exc
