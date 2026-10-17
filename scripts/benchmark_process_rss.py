"""Bounded Linux RSS sampling for explicitly owned benchmark workers only.

This is measurement, never admission or application policy. RSS includes shared
pages in each process, so adding parent and child RSS double-counts such pages.
Reads are sequential and sampling can miss short peaks, especially while Python
holds the GIL. Record the actual sampling gaps rather than claiming a heap bound.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter


INCREMENT_ALLOWANCE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ProcessRSS:
    pid: int
    parent_pid: int
    birth_ticks: int
    rss_bytes: int


def read_process_rss(pid, *, proc_root=Path("/proc"), page_bytes=None):
    """Read one bounded stat record; start ticks distinguish recycled PIDs."""
    if type(pid) is not int or pid <= 0:
        raise ValueError("RSS sampling requires a positive process ID")
    with (proc_root / str(pid) / "stat").open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("Process stat record exceeds the measurement bound")
    left, right = raw.find(b"("), raw.rfind(b")")
    if left < 1 or right < left or int(raw[:left]) != pid:
        raise ValueError("Invalid process stat identity")
    fields = raw[right + 1:].split()
    if len(fields) < 22:
        raise ValueError("Incomplete process stat record")
    parent, birth, pages = int(fields[1]), int(fields[19]), int(fields[21])
    page_bytes = os.sysconf("SC_PAGE_SIZE") if page_bytes is None else page_bytes
    if min(parent, birth, pages) < 0 or type(page_bytes) is not int or page_bytes <= 0:
        raise ValueError("Invalid process RSS counters")
    return ProcessRSS(pid, parent, birth, pages * page_bytes)


class ProcessRSSSampler:
    """Sample parent + explicitly registered direct children, retaining aggregates.

    Enter after the admitted source/undo state exists, before beginning work.
    Register a child immediately after the benchmark's owned worker starts. No
    descendant discovery, process environment reads, GC changes or retries occur.
    """

    def __init__(self, *, interval_seconds=.005, max_samples=100_000, max_children=4,
                 reader=read_process_rss, clock=perf_counter, parent_pid=None):
        if (type(interval_seconds) not in (int, float) or not .001 <= interval_seconds <= .1
                or type(max_samples) is not int or not 2 <= max_samples <= 100_000
                or type(max_children) is not int or not 1 <= max_children <= 16):
            raise ValueError("RSS sampler requires bounded interval, sample and child limits")
        self.interval_seconds, self.max_samples, self.max_children = interval_seconds, max_samples, max_children
        self.parent_pid = os.getpid() if parent_pid is None else parent_pid
        if type(self.parent_pid) is not int or self.parent_pid <= 0:
            raise ValueError("RSS sampling requires a positive parent process ID")
        self._reader, self._clock = reader, clock
        self._lock, self._stop = Lock(), Event()
        self._thread = None
        self._started = False
        self._phase = "retained_idle"
        self._children = {}
        self._phases = {}
        self._errors = {}
        self._previous = None
        self._parent_birth = None
        self.baseline_parent_bytes = None
        self.samples = 0
        self.samples_with_children = 0
        self.peak_parent_bytes = 0
        self.peak_children_bytes = 0
        self.peak_combined_bytes = 0
        self.max_sample_gap_ms = 0.
        self.max_sample_duration_ms = 0.
        self.exhausted = False

    def _error(self, code):
        self._errors[code] = self._errors.get(code, 0) + 1

    def set_phase(self, value):
        if value not in {"retained_idle", "retained_ready_result", "start", "worker", "ready", "commit"}:
            raise ValueError("Unknown RSS benchmark phase")
        with self._lock:
            self._phase = value

    def register_child(self, pid):
        """Bind only a worker PID supplied by the benchmark's supervisor hook."""
        with self._lock:
            if not self._started or self._stop.is_set():
                raise RuntimeError("RSS sampler is not active")
            try:
                child = self._reader(pid)
            except (OSError, ValueError):
                self._error("child_registration_unavailable")
                return False
            key = (child.pid, child.birth_ticks)
            if child.parent_pid != self.parent_pid or child.pid == self.parent_pid:
                self._error("child_not_owned")
                return False
            if key not in self._children and len(self._children) >= self.max_children:
                self._error("child_limit")
                return False
            self._children[key] = child
        self._sample()
        return True

    def _sample(self):
        with self._lock:
            if self.samples >= self.max_samples:
                self.exhausted = True
                return
            started = self._clock()
            if self._previous is not None:
                self.max_sample_gap_ms = max(self.max_sample_gap_ms, (started - self._previous) * 1000)
            self._previous = started
            self.samples += 1
            try:
                parent = self._reader(self.parent_pid)
                if self._parent_birth is None:
                    self._parent_birth = parent.birth_ticks
                    self.baseline_parent_bytes = parent.rss_bytes
                elif parent.birth_ticks != self._parent_birth:
                    raise ValueError("Parent process identity changed")
            except (OSError, ValueError):
                self._error("parent_sample_unavailable")
                return
            children, count = 0, 0
            for (pid, birth), registered in self._children.items():
                try:
                    child = self._reader(pid)
                except ProcessLookupError:
                    continue
                except FileNotFoundError:
                    continue  # An owned child was reaped between samples.
                except (OSError, ValueError):
                    self._error("child_sample_unavailable")
                    continue
                if child.birth_ticks != birth or child.parent_pid != registered.parent_pid:
                    self._error("child_identity_changed")
                    continue
                children += child.rss_bytes
                count += 1
            combined = parent.rss_bytes + children
            self.samples_with_children += bool(count)
            self.peak_parent_bytes = max(self.peak_parent_bytes, parent.rss_bytes)
            self.peak_children_bytes = max(self.peak_children_bytes, children)
            self.peak_combined_bytes = max(self.peak_combined_bytes, combined)
            phase = self._phases.setdefault(self._phase, {"samples": 0, "peak_combined_bytes": 0})
            phase["samples"] += 1
            phase["peak_combined_bytes"] = max(phase["peak_combined_bytes"], combined)
            self.max_sample_duration_ms = max(self.max_sample_duration_ms, (self._clock() - started) * 1000)

    def _run(self):
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def __enter__(self):
        if self._started:
            raise RuntimeError("RSS sampler cannot be entered twice")
        self._started = True
        self._sample()
        self._thread = Thread(target=self._run, name="benchmark-owned-process-rss", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._stop.set()
        self._thread.join(timeout=2.)
        if self._thread.is_alive():
            raise RuntimeError("RSS sampler thread did not stop")
        self._sample()

    def report(self):
        with self._lock:
            measured = (self.baseline_parent_bytes is not None and self.samples_with_children > 0
                        and not self.exhausted and not self._errors)
            increase = (None if self.baseline_parent_bytes is None else
                        self.peak_combined_bytes - self.baseline_parent_bytes)
            return {
                "requested_interval_ms": self.interval_seconds * 1000,
                "max_sample_gap_ms": self.max_sample_gap_ms,
                "max_sample_duration_ms": self.max_sample_duration_ms,
                "sample_count": self.samples, "samples_with_children": self.samples_with_children,
                "sample_limit": self.max_samples, "sample_limit_reached": self.exhausted,
                "owned_child_count": len(self._children), "errors": dict(self._errors),
                "baseline_parent_bytes": self.baseline_parent_bytes,
                "peak_parent_bytes": self.peak_parent_bytes, "peak_owned_children_bytes": self.peak_children_bytes,
                "peak_combined_bytes": self.peak_combined_bytes, "increase_over_idle_bytes": increase,
                "allowance_bytes": INCREMENT_ALLOWANCE_BYTES,
                "observed_within_allowance": (increase <= INCREMENT_ALLOWANCE_BYTES) if measured else None,
                "measurement_complete": measured,
                "sampler_stopped": self._thread is not None and not self._thread.is_alive(),
                "phases": {key: dict(value) for key, value in self._phases.items()},
            }
