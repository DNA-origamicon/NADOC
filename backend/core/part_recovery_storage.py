"""Bound encoded history storage without interpreting it as replay evidence."""

from itertools import chain

from backend.core.part_capture_graph import CaptureLimit


MAX_RECOVERY_BYTES = 8_000_000
RECOVERY_PAYLOAD_FIELDS = frozenset({"design_snapshot_gz_b64", "post_state_gz_b64", "pre_state_gz_b64",
                                   "diff_added_b64", "diff_removed_b64", "diff_modified_b64"})


def retained_recovery_bytes(entries, *, max_rows, limit=MAX_RECOVERY_BYTES):
    """Bound saved bodies retained by publication's undo, without decoding them.

    This is storage admission, never replay evidence. Corrupt small strings stay
    repairable. Count actual strings rather than caller-supplied size metadata;
    non-ASCII corruption receives a conservative four-byte-per-character charge.
    The caller owns the source lock and separately admits definition contents.
    """
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
            for field in RECOVERY_PAYLOAD_FIELDS.intersection(row.__dict__):
                value = row.__dict__[field]
                if value is None:
                    continue
                if type(value) is not str:
                    raise CaptureLimit("Retained recovery must contain encoded strings")
                size += len(value) * (1 if value.isascii() else 4)
                if size > limit:
                    raise CaptureLimit("Retained recovery exceeds its publication byte allowance")
    return size
