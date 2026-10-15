"""Bounded Join preview choices: references only, never cached geometry.

Join's historical flexible display derivation can select either endpoint first.
Remember the orientation the user previewed as a discrete feature input before
commit. The native command must still derive and resolve every tether itself.
"""
from collections import OrderedDict
import json
from threading import Lock
from time import monotonic

from fastapi import HTTPException

from backend.api.doc_context import get_current_doc


MAX_CHOICES_BYTES = 128_000
MAX_PREVIEWS = 16
TTL_SECONDS = 300
_pending = OrderedDict()
_lock = Lock()


def remember(token, design_id, revision, choices):
    encoded = json.dumps(choices, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_CHOICES_BYTES:
        raise ValueError("Join preview exceeds the orientation-input limit")
    key = (get_current_doc(), token)
    now = monotonic()
    with _lock:
        for old in list(_pending):
            if _pending[old][0] < now:
                del _pending[old]
        previous = _pending.get(key)
        if previous is not None and previous[1:] != (design_id, revision, encoded):
            raise ValueError("Join preview choices changed; refresh the source before previewing again")
        _pending[key] = (now + TTL_SECONDS, design_id, revision, encoded)
        _pending.move_to_end(key)
        while len(_pending) > MAX_PREVIEWS:
            _pending.popitem(last=False)


def resolve(token, design_id, revision):
    with _lock:
        value = _pending.get((get_current_doc(), token))
    if value is None or value[0] < monotonic() or value[1:3] != (design_id, revision):
        raise HTTPException(409, detail="Join preview expired or changed; preview again.")
    # A failed atomic commit may retry this preview. Revision checks prevent a
    # successful commit being applied twice; decoding returns independent inputs.
    return json.loads(value[3])
