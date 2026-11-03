"""Memo seeds for isolated copies of reviewed atoms and crossover trees.

This changes copying work only. It does not omit fields, validate/normalize
authoring, or share mutable model containers with a captured design.
"""

from pydantic import BaseModel
from backend.core.models import ProteinAtom, Crossover, HalfCrossover, Direction


_ATOM_FIELDS = frozenset({"serial", "name", "element", "res_name", "chain_id",
                          "res_seq", "x", "y", "z"})
_SCALARS = frozenset({int, float, str})
_CROSSOVER_FIELDS = frozenset({'id', 'half_a', 'half_b', 'extra_bases', 'process_id'})
_HALF_FIELDS = frozenset({'helix_id', 'index', 'strand'})


def crossover_charge(value, seen):
    """Account for the exact ordinary crossover tree, including endpoint aliases."""
    if (type(value) is not Crossover or Crossover.__deepcopy__ is not BaseModel.__deepcopy__
            or Crossover.model_fields.keys() != _CROSSOVER_FIELDS
            or value.__dict__.keys() != _CROSSOVER_FIELDS
            or value.__pydantic_extra__ is not None or value.__pydantic_private__ is not None):
        return
    fields = value.__dict__
    if (type(fields['id']) is not str
            or type(fields['extra_bases']) not in (str, type(None))
            or type(fields['process_id']) not in (str, type(None))):
        return
    halves = fields['half_a'], fields['half_b']
    for half in halves:
        if (type(half) is not HalfCrossover or HalfCrossover.__deepcopy__ is not BaseModel.__deepcopy__
                or HalfCrossover.model_fields.keys() != _HALF_FIELDS or half.__dict__.keys() != _HALF_FIELDS
                or half.__pydantic_extra__ is not None or half.__pydantic_private__ is not None):
            return
        data = half.__dict__
        if type(data['helix_id']) is not str or type(data['index']) is not int or type(data['strand']) is not Direction:
            return
    size = 4 * (len(fields['id']) + len(fields['extra_bases'] or '') + len(fields['process_id'] or ''))
    nodes = 5
    for index, half in enumerate(halves):
        if id(half) not in seen and (index == 0 or half is not halves[0]):
            nodes += 3
            size += 4 * (len(half.helix_id) + len(half.strand))
    return nodes, size, halves


def seed_crossover_copy(item, memo, pools=None):
    """Copy the already reviewed complete tree, retaining every mutable container."""
    if id(item) in memo:
        return memo[id(item)]
    kind = type(item)
    pool = pools.get(kind) if pools else None
    pooled = bool(pool)
    result = pool.pop() if pooled else kind.__new__(kind)
    memo[id(item)] = result
    fields = memo.get(id(item.__dict__))
    if fields is None:
        fields = result.__dict__ if pooled else {}
        fields.update(item.__dict__)
        memo[id(item.__dict__)] = fields
        if kind is Crossover:
            fields['half_a'] = seed_crossover_copy(item.half_a, memo, pools)
            fields['half_b'] = seed_crossover_copy(item.half_b, memo, pools)
    object.__setattr__(result, '__dict__', fields)
    if pooled:
        result.__pydantic_fields_set__.update(item.__pydantic_fields_set__)
    else:
        object.__setattr__(result, '__pydantic_fields_set__', item.__pydantic_fields_set__.copy())
    object.__setattr__(result, '__pydantic_extra__', None)
    object.__setattr__(result, '__pydantic_private__', None)
    return result


def scalar_atom_charge(value):
    """Return the reviewed scalar field charge without allocating an atom."""
    if (type(value) is not ProteinAtom
            or ProteinAtom.model_fields.keys() != _ATOM_FIELDS
            or value.__dict__.keys() != _ATOM_FIELDS
            or value.__pydantic_extra__ is not None
            or value.__pydantic_private__ is not None):
        return
    size = 0
    for item in value.__dict__.values():
        kind = type(item)
        if kind not in _SCALARS:
            return
        if kind is str:
            size += len(item) * 4
    return len(_ATOM_FIELDS), size


def allocate_atom_copies(count):
    """Allocate bounded empty destinations before acquiring a live source lock.

    These carry no source values or authority. A caller owns this one-use list;
    capture fills each shell only after the normal exact scalar-shape check.
    No collection is forced, disabled or reconfigured.
    """
    if type(count) is not int or not 0 <= count <= 10_000:
        raise ValueError("Atom copy allocation requires a bounded count")
    return [ProteinAtom.model_construct(serial=0, name="", element="", res_name="",
        chain_id="", res_seq=0, x=0., y=0., z=0.) for _ in range(count)]


def seed_scalar_atom_copy(value, memo, atom_copies=None):
    """Copy the exact scalar-only shape; return its field node/byte charge.

    Every value is immutable, while model_copy makes independent __dict__ and
    fields-set containers. A subclass, future schema, cached value, extra or
    private state, or mutated non-scalar field takes ordinary deepcopy instead.
    Returning the charge lets the caller account for this fixed-size record at
    one cooperative clock boundary. Every field retains its original charge.
    """
    charge = scalar_atom_charge(value)
    if charge is None:
        return
    if atom_copies:
        copied = atom_copies.pop()
        copied.__dict__.update(value.__dict__)
        copied.__pydantic_fields_set__.intersection_update(value.__pydantic_fields_set__)
        copied.__pydantic_fields_set__.update(value.__pydantic_fields_set__)
    else:
        copied = value.model_copy(deep=False)
    # deepcopy also memoizes the model's field dict. Preserve aliases from
    # metadata or another atom to that dict, not just aliases to the atom.
    fields = memo.setdefault(id(value.__dict__), copied.__dict__)
    object.__setattr__(copied, "__dict__", fields)
    memo[id(value)] = copied
    return charge


def copy_complete_design(design, atom_copies=None, model_copies=None):
    """Full undo copy, including display/history, with private scalar shells.

    Unlike proof capture this omits no field. The caller owns the source lock;
    scalar aliases use deepcopy's shared memo and all mutable containers remain
    independent. Unreviewed record shapes take the ordinary deepcopy path.
    """
    from backend.core.part_model_copy import copy_model_graph
    memo = {}
    for particle in design.nanoparticles[:1]:
        if particle.coating is not None:
            for atom in particle.coating.protein.atoms[:4100]:
                seed_scalar_atom_copy(atom, memo, atom_copies)
    seen = set()
    for crossover in design.crossovers[:1024]:
        if crossover_charge(crossover, seen) is not None:
            seed_crossover_copy(crossover, memo, model_copies)
    return copy_model_graph(design, memo, model_copies=model_copies)
