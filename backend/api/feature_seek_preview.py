"""Bounded, short-lived, document-scoped preparation for interactive seeks.

Preview never changes the editor or undo history. A token can commit only against
the exact source object and revision that was previewed. No historical geometry
is substituted into the topology, and abandoned previews expire.
"""
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from backend.api.doc_context import get_current_doc
from backend.core.models import Design


@dataclass
class PreparedSeek:
    source: Design
    revision: int
    target: Design
    position: int
    sub_position: int | None
    token: str
    expires: float


_pending: OrderedDict[str, PreparedSeek] = OrderedDict()
_lock = Lock()


def remember(source, revision, target, position, sub_position):
    prepared = PreparedSeek(source, revision, target, position, sub_position,
                            uuid4().hex, monotonic() + 60)
    with _lock:
        for doc in list(_pending):
            if _pending[doc].expires < monotonic():
                del _pending[doc]
        _pending[get_current_doc()] = prepared
        _pending.move_to_end(get_current_doc())
        while len(_pending) > 8:
            _pending.popitem(last=False)
    return prepared.token


def consume(token, source, revision, position, sub_position):
    with _lock:
        prepared = _pending.get(get_current_doc())
        if prepared is not None and prepared.token == token:
            del _pending[get_current_doc()]
        else:
            prepared = None
    if (prepared is None or prepared.expires < monotonic()
            or prepared.source is not source or prepared.revision != revision
            or (prepared.position, prepared.sub_position) != (position, sub_position)):
        raise HTTPException(409, detail="Design changed or preview expired. Select the stage again.")
    return prepared.target
