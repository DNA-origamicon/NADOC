"""Conservative retained-object charges without a million-entry visited set."""
import sys
from dataclasses import fields, is_dataclass


def retained_bytes(value, depth=0):
    """Charge shared leaves repeatedly; this intentionally overcounts ownership.

    Array payloads include their Python-object strings where applicable. Only
    known data containers are traversed, never arbitrary object graphs/cycles.
    """
    size = sys.getsizeof(value)
    if depth > 8:
        return size
    if hasattr(value, 'dtype') and hasattr(value, 'nbytes'):
        size = max(size, int(value.nbytes) + 128)
        if value.dtype.hasobject:
            size += sum(sys.getsizeof(item) for item in value.flat)
        return size
    if isinstance(value, dict):
        return size + sum(retained_bytes(k, depth+1) + retained_bytes(v, depth+1) for k,v in value.items())
    if isinstance(value, (list, tuple)):
        return size + sum(retained_bytes(v, depth+1) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        return size + sum(retained_bytes(getattr(value, f.name), depth+1) for f in fields(value))
    return size


def topology_bytes(universe):
    topology = getattr(universe, '_topology', None)
    if topology is None:
        return retained_bytes(universe)
    arrays = [getattr(attr, 'values', None) for attr in topology.attrs]
    tt = getattr(topology, 'tt', None)
    arrays += [getattr(tt, key, None) for key in ('_AR', '_RS', '_RA', '_SR')]
    # Lazy topology tables, indices, allocator overhead and atom/residue groups.
    return int(1.25 * (sum(retained_bytes(v) for v in arrays) + topology.n_atoms * 64))
