"""Memo seeds for isolated copies of the reviewed scalar atom record.

This changes copying work only. It does not omit atoms, validate/normalize
authoring, or share mutable model containers with a captured design.
"""

from backend.core.models import ProteinAtom


_ATOM_FIELDS = frozenset({"serial", "name", "element", "res_name", "chain_id",
                          "res_seq", "x", "y", "z"})
_SCALARS = frozenset({int, float, str})


def seed_scalar_atom_copy(value, memo):
    """Use Pydantic's shallow model copy only for the exact scalar-only shape.

    Every value is immutable, while model_copy makes independent __dict__ and
    fields-set containers. A subclass, future schema, cached value, extra or
    private state, or mutated non-scalar field takes ordinary deepcopy instead.
    The caller still charges every atom field against the capture budgets.
    """
    if (type(value) is not ProteinAtom
            or ProteinAtom.model_fields.keys() != _ATOM_FIELDS
            or value.__dict__.keys() != _ATOM_FIELDS
            or value.__pydantic_extra__ is not None
            or value.__pydantic_private__ is not None):
        return
    if all(type(item) in _SCALARS for item in value.__dict__.values()):
        copied = value.model_copy(deep=False)
        # deepcopy also memoizes the model's field dict. Preserve aliases from
        # metadata or another atom to that dict, not just aliases to the atom.
        fields = memo.setdefault(id(value.__dict__), copied.__dict__)
        object.__setattr__(copied, "__dict__", fields)
        memo[id(value)] = copied
