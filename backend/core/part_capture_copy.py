"""Memo seeds for isolated copies of the reviewed scalar atom record.

This changes copying work only. It does not omit atoms, validate/normalize
authoring, or share mutable model containers with a captured design.
"""

from backend.core.models import ProteinAtom


_ATOM_FIELDS = frozenset({"serial", "name", "element", "res_name", "chain_id",
                          "res_seq", "x", "y", "z"})
_SCALARS = frozenset({int, float, str})


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


def seed_scalar_atom_copy(value, memo):
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
    copied = value.model_copy(deep=False)
    # deepcopy also memoizes the model's field dict. Preserve aliases from
    # metadata or another atom to that dict, not just aliases to the atom.
    fields = memo.setdefault(id(value.__dict__), copied.__dict__)
    object.__setattr__(copied, "__dict__", fields)
    memo[id(value)] = copied
    return charge
