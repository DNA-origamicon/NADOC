"""Single shared work slot with one bounded foreground reservation.

Only sealed interactive readers opt into waiting, and only behind background
work. No input capture/allocation is queued. All other consumers remain fail-fast.
The existing supervisor still owns release after child/buffer cleanup.
"""
from threading import Condition
from time import monotonic


class WorkAdmission:
    def __init__(self):
        self._condition = Condition()
        self._held = False
        self._background = False
        self._waiting = False

    def acquire(self, *, blocking=False, background=False):
        if blocking:
            raise ValueError('Shared work admission requires explicit bounded waiting')
        with self._condition:
            if self._held or self._waiting:
                return False
            self._held, self._background = True, background
            return True

    def acquire_foreground(self, *, deadline, check):
        # Run origin/cancellation checks without holding the admission lock.
        check()
        with self._condition:
            if self._waiting or (self._held and not self._background):
                return False
            self._waiting = True
        try:
            while True:
                check()
                with self._condition:
                    if monotonic() >= deadline:
                        # The caller normally supplies its typed deadline error.
                        return False
                    if not self._held:
                        self._held, self._background = True, False
                        return True
                    self._condition.wait(min(.05, max(0, deadline - monotonic())))
        finally:
            with self._condition:
                self._waiting = False
                self._condition.notify_all()

    def release(self):
        with self._condition:
            if not self._held:
                raise ValueError('Shared work slot released too many times')
            self._held, self._background = False, False
            self._condition.notify_all()
