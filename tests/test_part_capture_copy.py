"""Isolated authoring capture and safe fallback for atom-copy specialization."""

from copy import deepcopy

import pytest
from pydantic import ConfigDict, PrivateAttr

from backend.core.models import Design, Nanoparticle, ProteinAsset, ProteinAtom, StreptavidinCoating
from backend.core.part_capture_copy import seed_scalar_atom_copy
from backend.core.part_verification_capture import CaptureLimit, capture


def atom(cls=ProteinAtom):
    return cls(serial=1, name="CA", element="C", res_name="ALA", chain_id="A", res_seq=1,
               x=1.0, y=2.0, z=3.0)


def design_with_atoms(field="nanoparticles"):
    first = atom()
    protein = ProteinAsset(atoms=[first, first], bonds=[(0, 1)], metadata={"first": first})
    return design_with_protein(protein, field)


def design_with_protein(protein, field):
    if field == "protein_assets":
        return Design(protein_assets=[protein])
    return Design(nanoparticles=[Nanoparticle(diameter_nm=20, coating=StreptavidinCoating(
        target_count=1, protein=protein))])


def selected_protein(design, field):
    return (design.protein_assets[0] if field == "protein_assets"
            else design.nanoparticles[0].coating.protein)


@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets"])
def test_capture_matches_deepcopy_and_preserves_internal_aliases_without_source_aliases(monkeypatch, field):
    design = design_with_atoms(field)
    expected = deepcopy(getattr(design, field))

    def unexpected_deepcopy(*_args):
        raise AssertionError("Scalar atom should not recursively copy immutable fields")

    monkeypatch.setattr(ProteinAtom, "__deepcopy__", unexpected_deepcopy)
    isolated = capture(design, seconds=1)
    assert getattr(isolated, field) == expected
    copied = selected_protein(isolated, field)
    original = selected_protein(design, field)
    assert copied.atoms[0] is copied.atoms[1] is copied.metadata["first"]
    assert copied.atoms[0] is not original.atoms[0]
    assert copied.atoms[0].__dict__ is not original.atoms[0].__dict__
    assert copied.atoms[0].model_fields_set is not original.atoms[0].model_fields_set
    copied.atoms[0].x = 5.0
    copied.atoms[0].model_fields_set.clear()
    copied.bonds.clear()
    copied.center_of_mass[0] = 10
    copied.metadata["new"] = []
    assert original.atoms[0].x == 1.0
    assert original.atoms[0].model_fields_set
    assert original.bonds == [(0, 1)]
    assert original.center_of_mass == [0, 0, 0]
    assert "new" not in original.metadata


@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets"])
def test_capture_preserves_aliases_to_atom_fields_and_between_atom_field_dicts(field):
    design = design_with_atoms(field)
    original = selected_protein(design, field)
    other = atom()
    object.__setattr__(other, "__dict__", original.atoms[0].__dict__)
    original.atoms.append(other)
    original.metadata["atom_fields"] = original.atoms[0].__dict__
    expected = deepcopy(original)
    copied = selected_protein(capture(design, seconds=1), field)
    assert copied == expected
    assert copied.atoms[0] is not copied.atoms[2]
    assert copied.atoms[0].__dict__ is copied.atoms[2].__dict__ is copied.metadata["atom_fields"]
    assert copied.atoms[0].__dict__ is not original.atoms[0].__dict__
    copied.metadata["atom_fields"]["x"] = 20
    assert copied.atoms[0].x == copied.atoms[2].x == 20
    assert original.atoms[0].x == original.atoms[2].x == 1


class ExtendedAtom(ProteinAtom):
    model_config = ConfigDict(extra="allow")
    _notes: list = PrivateAttr(default_factory=list)


@pytest.mark.parametrize("fault", ["subclass", "cached", "mutable_field", "extra", "private", "future_schema"])
@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets"])
def test_unreviewed_atom_shape_uses_full_deepcopy(monkeypatch, fault, field):
    value = atom(ExtendedAtom if fault == "subclass" else ProteinAtom)
    if fault == "subclass":
        value._notes.append([])
    elif fault == "cached":
        value.__dict__["cached"] = []
    elif fault == "mutable_field":
        value.__dict__["x"] = []
    elif fault == "extra":
        object.__setattr__(value, "__pydantic_extra__", {"notes": []})
    elif fault == "private":
        object.__setattr__(value, "__pydantic_private__", {"notes": []})
    else:
        monkeypatch.setattr(ProteinAtom, "__pydantic_fields__", {
            **ProteinAtom.model_fields, "future": ProteinAtom.model_fields["serial"]})
    memo = {}
    seed_scalar_atom_copy(value, memo)
    assert id(value) not in memo
    copied = deepcopy(value, memo)
    assert copied == value and copied is not value
    for name, child in value.__dict__.items():
        if isinstance(child, list):
            assert copied.__dict__[name] is not child
    if value.__pydantic_extra__:
        assert copied.__pydantic_extra__["notes"] is not value.__pydantic_extra__["notes"]
    if value.__pydantic_private__:
        key = "_notes" if fault == "subclass" else "notes"
        assert copied.__pydantic_private__[key] is not value.__pydantic_private__[key]
    # Exercise fallback through the actual field capture, including aliases to
    # the opaque atom. Existing hidden-state charging behavior is unchanged.
    source = design_with_protein(ProteinAsset.model_construct(atoms=[value], metadata={"again": value}), field)
    native_deepcopy, calls = ProteinAtom.__deepcopy__, []

    def counted(self, memo=None):
        calls.append(self)
        return native_deepcopy(self, memo)

    monkeypatch.setattr(ProteinAtom, "__deepcopy__", counted)
    captured = selected_protein(capture(source, seconds=1), field)
    assert calls and captured.atoms[0] == value
    assert captured.atoms[0] is captured.metadata["again"]
    assert captured.atoms[0] is not value and captured.atoms[0].__dict__ is not value.__dict__
    if value.__pydantic_extra__:
        assert captured.atoms[0].__pydantic_extra__["notes"] is not value.__pydantic_extra__["notes"]
    if value.__pydantic_private__:
        assert captured.atoms[0].__pydantic_private__[key] is not value.__pydantic_private__[key]


@pytest.mark.parametrize("limits", [{"max_nodes": 20}, {"max_bytes": 20}, {"seconds": 0}])
@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets"])
def test_specialization_keeps_capture_limits_and_does_not_mutate_on_refusal(limits, field):
    design = design_with_atoms(field)
    before = deepcopy(design)
    with pytest.raises(CaptureLimit):
        capture(design, **limits)
    assert design == before


@pytest.mark.parametrize("budget", ["max_nodes", "max_bytes"])
@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets"])
def test_atom_record_accounting_preserves_exact_generic_admission_boundary(monkeypatch, budget, field):
    from backend.core import part_capture_copy

    source = design_with_atoms(field)
    selected_protein(source, field).atoms[0].name = "Unicode atom \u03b1"

    def minimum_budget():
        low, high = 0, 10000
        while low < high:
            value = (low + high) // 2
            try:
                capture(source, seconds=1, **{budget: value})
            except CaptureLimit:
                low = value + 1
            else:
                high = value
        assert low < 10000
        return low

    optimized = minimum_budget()
    monkeypatch.setattr(part_capture_copy, "seed_scalar_atom_copy", lambda *_args: None)
    assert minimum_budget() == optimized
