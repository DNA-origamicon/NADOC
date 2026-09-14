import pytest

from backend.parameterization.photoproduct_models import (
    ModelConstructionError,
    _model_graph,
)


class _Atom:
    def __init__(self, element: str, charge: int = 0, aromatic: bool = False):
        self.element = element
        self.charge = charge
        self.aromatic = aromatic

    def GetSymbol(self):
        return self.element

    def GetFormalCharge(self):
        return self.charge

    def GetIsAromatic(self):
        return self.aromatic


class _Bond:
    def __init__(self, first: int, second: int, order: float, aromatic: bool = False):
        self.first = first
        self.second = second
        self.order = order
        self.aromatic = aromatic

    def GetBeginAtomIdx(self):
        return self.first

    def GetEndAtomIdx(self):
        return self.second

    def GetBondTypeAsDouble(self):
        return self.order

    def GetIsAromatic(self):
        return self.aromatic


class _Model:
    def __init__(self, atoms, bonds):
        self.atoms = atoms
        self.bonds = bonds

    def GetNumAtoms(self):
        return len(self.atoms)

    def GetAtoms(self):
        return iter(self.atoms)

    def GetBonds(self):
        return iter(self.bonds)


def test_model_graph_preserves_stable_identity_charge_and_bond_order():
    model = _Model(
        [_Atom("C"), _Atom("N", -1, True), _Atom("H")],
        [_Bond(1, 0, 1.5, True), _Bond(1, 2, 1.0)],
    )

    graph = _model_graph(model, ["1:C5", "1:N1", "1:H6"])

    assert graph["schema"] == "nadoc.photoproduct-model-graph.v1"
    assert graph["formal_charge"] == -1
    assert graph["atoms"][1] == {
        "index": 1,
        "key": "1:N1",
        "element": "N",
        "formal_charge": -1,
        "aromatic": True,
    }
    assert graph["bonds"] == [
        {
            "atoms": ["1:C5", "1:N1"],
            "indices": [0, 1],
            "order": 1.5,
            "aromatic": True,
        },
        {
            "atoms": ["1:N1", "1:H6"],
            "indices": [1, 2],
            "order": 1.0,
            "aromatic": False,
        },
    ]


@pytest.mark.parametrize("keys", [["1:C5"], ["1:C5", "1:C5"]])
def test_model_graph_rejects_incomplete_or_duplicate_stable_keys(keys):
    model = _Model([_Atom("C"), _Atom("C")], [_Bond(0, 1, 1.0)])

    with pytest.raises(ModelConstructionError, match="unique stable keys"):
        _model_graph(model, keys)
