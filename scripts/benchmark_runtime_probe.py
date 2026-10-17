"""Bounded benchmark-only GC interval correlation; never changes GC policy.

The callback records wall-clock intervals, not causation or memory usage. An
overlap must not be subtracted from user-observed latency to claim a pass.
"""

import gc
from threading import get_ident
from time import perf_counter


def overlap_ms(events, start, end):
    """Sum collection intervals clipped to one measured operation interval."""
    return sum(max(0., min(end, item["end"]) - max(start, item["start"]))
               for item in events) * 1000


class RuntimeProbe:
    """Own one callback temporarily; preserve every preexisting callback."""

    def __init__(self, *, phase=lambda: None, max_events=4096):
        if type(max_events) is not int or not 1 <= max_events <= 100_000:
            raise ValueError("Runtime probe event limit must be between 1 and 100,000")
        self.events, self._starts = [], {}
        self.dropped_events = 0
        self._phase, self.max_events = phase, max_events
        self._callback = self._record
        self._active = False

    def _record(self, event, info):
        key = (get_ident(), info["generation"])
        now = perf_counter()
        if event == "start":
            if len(self.events) + len(self._starts) >= self.max_events:
                self.dropped_events += 1
                return
            self._starts[key] = (now, self._phase())
        elif event == "stop":
            start = self._starts.pop(key, None)
            if start is not None:
                self.events.append({"start": start[0], "end": now, "thread": key[0],
                                    "phase": start[1], "generation": key[1]})

    def intervals(self, start, end):
        return [item for item in self.events if item["start"] <= end and item["end"] >= start]

    def __enter__(self):
        if self._active:
            raise RuntimeError("Runtime probe is already installed")
        gc.callbacks.append(self._callback)
        self._active = True
        return self

    def __exit__(self, *_args):
        if self._callback in gc.callbacks:
            gc.callbacks.remove(self._callback)
        self._active = False
        self._starts.clear()
