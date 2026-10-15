"""Isolated, time-bounded proof input capture from a lock-owned design."""

from backend.core.part_capture_inputs import CaptureLimit as CaptureLimit, visit_inputs


def capture(design, *, max_nodes=30_000, max_bytes=2_000_000, seconds=0.025,
            preserve_entry_types=False):
    """Caller owns the state lock; isolation retains the cooperative deadline.

    Recovery payloads and display/physical data are excluded. Immutable strings
    are shared but charged. Time is checked at object boundaries, not a hard
    real-time guarantee. Private candidate admission uses the same accounting
    without constructing another isolated graph.
    """
    return visit_inputs(design, max_nodes=max_nodes, max_bytes=max_bytes, seconds=seconds,
                        preserve_entry_types=preserve_entry_types, copy_inputs=True)


def admit(design, *, max_nodes=30_000, max_bytes=2_000_000, preserve_entry_types=False):
    """Check resource bounds of an already-private candidate without copying.

    This is not source isolation or validation, and grants no proof certificate.
    No independent time limit is imposed on private admission. Live input must
    still go through capture under its host lock before native preparation.
    """
    visit_inputs(design, max_nodes=max_nodes, max_bytes=max_bytes, seconds=None,
                 preserve_entry_types=preserve_entry_types, copy_inputs=False)
