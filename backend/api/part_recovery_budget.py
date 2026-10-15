"""Bound cumulative recovery encoding during explicit recipe operations.

Discarded cascade attempts still consume this work allowance. The bound limits
both retained recovery and repeated serialization; it is not a process heap cap.
"""

from backend.core.part_history_proof import ProofBudgetExceeded


MAX_RECOVERY_BYTES = 8_000_000


class RecoveryBudget:
    def __init__(self, limit=None):
        self.remaining = MAX_RECOVERY_BYTES if limit is None else limit

    def charge(self, *payloads):
        # Snapshot/delta payloads are ASCII base64. Charge encoded bytes, not
        # misleading uncompressed-size metadata supplied by an old document.
        self.remaining -= sum(len(payload) for payload in payloads)
        if self.remaining < 0:
            raise ProofBudgetExceeded("Regenerated recovery exceeds the cumulative encoding budget")
