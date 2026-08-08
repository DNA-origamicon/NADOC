"""Window-exporter element typing — regression for the CHARMM ion mis-typing bug.

Na+ (resname/atomname "SOD") was exported as z=16 (sulfur) because atom-name guessing
took the leading "S"; the fix resolves monatomic ions by resname first.  This pins that
so an ion-atmosphere-aware (Mg2+) origami export can't silently mistype ions again.
"""

from types import SimpleNamespace

from backend.ml.propagator.windows import _ELEMENT_Z, _element_of


def _atom(resname, name, element=""):
    return SimpleNamespace(resname=resname, name=name, element=element)


def test_charmm_ions_typed_by_resname_not_name():
    cases = {  # (resname, atomname) -> expected element / z
        ("SOD", "SOD"): ("NA", 11),  # was mis-typed S(16) before the fix
        ("CLA", "CLA"): ("CL", 17),
        ("POT", "POT"): ("K", 19),  # was mis-typed P(15)
        ("MG", "MG"): ("MG", 12),
        ("CAL", "CAL"): ("CA", 20),  # was mis-typed C(6)
    }
    for (rn, nm), (el, z) in cases.items():
        got = _element_of(_atom(rn, nm))
        assert got == el, f"{rn}/{nm} -> {got}, expected {el}"
        assert _ELEMENT_Z[got] == z


def test_dna_atoms_still_typed_by_name():
    # a phosphate P and a C1' carbon must NOT be caught by the ion map
    assert _element_of(_atom("DA", "P")) == "P"
    assert _element_of(_atom("DG", "C1'")) == "C"
    assert _element_of(_atom("DT", "N3")) == "N"


def test_explicit_element_wins_when_present():
    # if MDAnalysis DOES provide an element, a non-ion residue uses it
    assert _element_of(_atom("DA", "P", element="P")) == "P"
