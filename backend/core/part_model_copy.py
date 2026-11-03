"""Copy already-accounted authoring graphs without revalidating their models.

Match BaseModel's native deepcopy for its ordinary containers. Custom copy
hooks, container subclasses and non-model objects retain Python's deepcopy.
The caller still charges every field/node/byte and owns the capture deadline.
"""
from copy import deepcopy

from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from backend.core.models import Direction, StrandType, LatticeType

_ATOMIC = frozenset({str, int, float, bool, bytes, type(None), Direction, StrandType, LatticeType})


def model_copy_hint(design):
    """Bounded collection-length hints, carrying no source model or field value."""
    from backend.core.models import Domain, Strand, Helix, Vec3, Crossover, HalfCrossover
    strands = design.strands[:512]
    return {Domain: min(sum(min(len(s.domains), 2000) + min(len(s.routing_seed or ()), 2000) for s in strands), 5000),
        Strand: min(len(design.strands), 512), Helix: min(len(design.helices), 512),
        Vec3: min(len(design.helices) * 2, 1024), Crossover: min(len(design.crossovers), 1024),
        HalfCrossover: min(len(design.crossovers) * 2, 2048)}


def allocate_model_copies(hint):
    """Allocate empty destinations outside the lock, within one fixed ceiling."""
    pools, remaining = {}, 10_000
    for kind, count in hint.items():
        count = min(count, remaining)
        remaining -= count
        pool = pools[kind] = []
        for _ in range(count):
            value = kind.__new__(kind)
            object.__setattr__(value, '__dict__', {})
            object.__setattr__(value, '__pydantic_fields_set__', set())
            object.__setattr__(value, '__pydantic_extra__', None)
            object.__setattr__(value, '__pydantic_private__', None)
            pool.append(value)
    return pools


def copy_model_graph(value, memo=None, *, model_copies=None):
    memo = {} if memo is None else memo

    return _copy(value, memo, model_copies)


def _copy(item, memo, model_copies):
    kind = type(item)
    if kind in _ATOMIC:
        return item
    identity = id(item)
    if identity in memo:
        return memo[identity]
    if kind is dict:
        result = item.copy()
        memo[identity] = result
        for key, child in item.items():
            if type(key) not in _ATOMIC:
                del result[key]
                result[_copy(key, memo, model_copies)] = child if type(child) in _ATOMIC else _copy(child, memo, model_copies)
            elif type(child) not in _ATOMIC:
                result[key] = _copy(child, memo, model_copies)
        return result
    if kind is list:
        result = item.copy()
        memo[identity] = result
        for index, child in enumerate(item):
            if type(child) not in _ATOMIC:
                result[index] = _copy(child, memo, model_copies)
        return result
    if BaseModel in kind.__mro__ and kind.__deepcopy__ is BaseModel.__deepcopy__:
        pool = model_copies.get(kind) if model_copies else None
        pooled = bool(pool)
        result = pool.pop() if pooled else kind.__new__(kind)
        memo[identity] = result
        if pooled:
            fields = memo.get(id(item.__dict__))
            if fields is None:
                fields = result.__dict__
                memo[id(item.__dict__)] = fields
                fields.update(item.__dict__)
                for key, child in item.__dict__.items():
                    if type(key) not in _ATOMIC:
                        del fields[key]
                        fields[_copy(key, memo, model_copies)] = child if type(child) in _ATOMIC else _copy(child, memo, model_copies)
                    elif type(child) not in _ATOMIC:
                        fields[key] = _copy(child, memo, model_copies)
            object.__setattr__(result, '__dict__', fields)
            result.__pydantic_fields_set__.update(item.__pydantic_fields_set__)
        else:
            object.__setattr__(result, '__dict__', _copy(item.__dict__, memo, model_copies))
            object.__setattr__(result, '__pydantic_fields_set__', item.__pydantic_fields_set__.copy())
        object.__setattr__(result, '__pydantic_extra__', _copy(item.__pydantic_extra__, memo, model_copies))
        private = getattr(item, '__pydantic_private__', None)
        object.__setattr__(result, '__pydantic_private__', None if private is None else
            {key: _copy(child, memo, model_copies) for key, child in private.items() if child is not PydanticUndefined})
        return result
    return deepcopy(item, memo)
