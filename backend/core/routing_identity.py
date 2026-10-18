"""Stable identities allocated from native routing inputs before construction.

An occupied directed endpoint pair is unique in a part. Geometry, colors,
sequences, saved results and document identity never participate in these IDs.
"""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4, uuid5

from backend.core.models import Crossover, ForcedLigation, Strand

_namespace = ContextVar("native_routing_identity", default=None)


@contextmanager
def identity_scope(seed):
    """A command's explicit namespace, local to this execution/thread.

    Only these native constructors opt in. Legacy callers retain random IDs;
    no model defaults, UUID functions, or other threads are patched.
    """
    token = _namespace.set(UUID(str(seed)) if seed else None)
    try:
        yield
    finally:
        _namespace.reset(token)


def _identifier(kind, values):
    namespace = _namespace.get()
    return (
        str(uuid5(namespace, json.dumps([kind, values], sort_keys=True)))
        if namespace
        else str(uuid4())
    )


def crossover(*, half_a, half_b, **kwargs):
    halves = sorted((h.helix_id, h.index, h.strand.value) for h in (half_a, half_b))
    return Crossover(
        id=_identifier("crossover", halves), half_a=half_a, half_b=half_b, **kwargs
    )


def forced_ligation(**kwargs):
    keys = (
        "three_prime_helix_id",
        "three_prime_bp",
        "three_prime_direction",
        "five_prime_helix_id",
        "five_prime_bp",
        "five_prime_direction",
    )
    return ForcedLigation(
        id=_identifier("forced-ligation", [kwargs[k] for k in keys]), **kwargs
    )


def connector_strand(*, domains, **kwargs):
    slots = [(d.helix_id, d.start_bp, d.end_bp, d.direction.value) for d in domains]
    return Strand(id=_identifier("connector", slots), domains=domains, **kwargs)
