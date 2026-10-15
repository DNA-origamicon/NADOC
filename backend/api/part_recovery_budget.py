"""Bound cumulative recovery encoding during explicit recipe operations.

Discarded cascade attempts still consume this work allowance. The bound limits
both retained recovery and repeated serialization; it is not a process heap cap.
"""

from backend.core.part_history_proof import ProofBudgetExceeded


MAX_RECOVERY_BYTES = 8_000_000
_PAYLOAD_FIELDS = frozenset({"design_snapshot_gz_b64", "post_state_gz_b64", "pre_state_gz_b64",
                            "diff_added_b64", "diff_removed_b64", "diff_modified_b64"})


def retained_recovery_bytes(entries, *, max_rows, limit=MAX_RECOVERY_BYTES):
    """Bound saved bodies retained by publication's undo, without decoding them.

    This is storage admission, never replay evidence. Corrupt small strings stay
    repairable. Count actual strings rather than caller-supplied size metadata;
    non-ASCII corruption receives a conservative four-byte-per-character charge.
    The caller owns the source lock and separately admits definition contents.
    """
    from itertools import chain
    from backend.core.part_verification_capture import CaptureLimit

    if type(entries) is not list or len(entries) > max_rows:
        raise CaptureLimit("Retained history exceeds its publication row allowance")
    rows, size = len(entries), 0
    for entry in entries:
        children = entry.__dict__.get("children", [])
        if type(children) is not list:
            raise CaptureLimit("Retained history requires a bounded child list")
        rows += len(children)
        if rows > max_rows:
            raise CaptureLimit("Retained history exceeds its publication row allowance")
        for row in chain((entry,), children):
            for field in _PAYLOAD_FIELDS.intersection(row.__dict__):
                value = row.__dict__[field]
                if value is None:
                    continue
                if type(value) is not str:
                    raise CaptureLimit("Retained recovery must contain encoded strings")
                size += len(value) * (1 if value.isascii() else 4)
                if size > limit:
                    raise CaptureLimit("Retained recovery exceeds its publication byte allowance")
    return size


class RecoveryBudget:
    def __init__(self, limit=None):
        self.remaining = MAX_RECOVERY_BYTES if limit is None else limit

    def charge(self, *payloads):
        # Snapshot/delta payloads are ASCII base64. Charge encoded bytes, not
        # misleading uncompressed-size metadata supplied by an old document.
        self.remaining -= sum(len(payload) for payload in payloads)
        if self.remaining < 0:
            raise ProofBudgetExceeded("Regenerated recovery exceeds the cumulative encoding budget")
