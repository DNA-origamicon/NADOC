"""Bound model-to-JSON expansion before serializers allocate their output.

Unlike isolated graph capture, this visits each shared value at every position
where JSON would expand it. Only active ancestors are tracked, to reject cycles.
The byte allowance charges structural work (16/value plus string storage), not
exact escaped JSON bytes or peak process memory. Callers retain their separate
capture, recovery and encoded transport limits. This grants no model authority.
"""

from enum import Enum
from itertools import chain
from math import isfinite

from pydantic import BaseModel

from backend.core.part_capture_graph import CaptureLimit


_MAX_DEPTH = 64


class SerializationShapeError(ValueError):
    """The model graph cannot be classified as the supported JSON document."""


def admit_model_serialization(value, *, max_bytes=16_000_000, max_nodes=None,
                              checkpoint=lambda: None, label="Model serialization"):
    """Check private inputs without encoding, copying, normalizing or hashing.

    Immutable revisions retain the original byte-only admission by omitting
    max_nodes. Other callers may additionally cap expanded value occurrences.
    The legacy byte preflight includes pending leave markers conservatively;
    the optional node allowance counts only values that JSON would contain.
    """
    pending = [(value, 0, False)]
    pending_values = 1
    active = set()
    remaining = max_bytes
    nodes = 0

    def refuse(detail):
        raise SerializationShapeError(f"{label} {detail}")

    def node_limit(children=0):
        if max_nodes is not None and nodes + children + pending_values > max_nodes:
            raise CaptureLimit(f"{label} exceeds its expanded node allowance")

    while pending:
        checkpoint()
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        pending_values -= 1
        nodes += 1
        node_limit()
        remaining -= 16
        if remaining < 0:
            raise CaptureLimit(f"{label} exceeds its full transport allowance")
        if depth > _MAX_DEPTH:
            refuse("exceeds its JSON depth allowance")
        if isinstance(item, Enum):
            item = item.value
        if type(item) is str:
            remaining -= len(item) * (1 if item.isascii() else 4)
        elif item is None or type(item) is bool:
            continue
        elif type(item) is int:
            if item.bit_length() > 64:
                refuse("integers must fit the existing JSON input range")
        elif type(item) is float:
            if not isfinite(item):
                refuse("numbers must be finite")
        elif isinstance(item, BaseModel) or type(item) in {dict, list, tuple}:
            if id(item) in active:
                refuse("cannot contain a cyclic model or JSON value")
            if isinstance(item, BaseModel):
                if (set(item.__dict__) != set(type(item).model_fields)
                        or getattr(item, "__pydantic_extra__", None)):
                    refuse("cannot classify this model schema")
                children = item.__dict__.values()
                child_count = len(children)
            elif type(item) is dict:
                child_count = len(item) * 2
                node_limit(child_count)
                if 16 * (child_count + len(pending)) > remaining:
                    raise CaptureLimit(f"{label} exceeds its full structural allowance")
                if any(type(key) is not str for key in item):
                    refuse("JSON object keys must be strings")
                children = chain(item.keys(), item.values())
            else:
                children = item
                child_count = len(children)
            node_limit(child_count)
            if 16 * (child_count + len(pending)) > remaining:
                raise CaptureLimit(f"{label} exceeds its full structural allowance")
            active.add(id(item))
            pending.append((item, depth, True))
            pending.extend((child, depth + 1, False) for child in children)
            pending_values += child_count
        else:
            refuse("permits only model fields and JSON values")
        if remaining < 0:
            raise CaptureLimit(f"{label} exceeds its full transport allowance")
