"""Smoke tests for shared fixtures in conftest.py."""

from backend.core.models import Design, LatticeType, StrandType
from backend.core.validator import validate_design

from tests.conftest import make_minimal_design


def test_make_minimal_design_default_round_trip_and_validates():
    d = make_minimal_design()
    assert len(d.helices) == 1
    assert len(d.strands) == 2
    assert d.lattice_type == LatticeType.HONEYCOMB
    assert {s.strand_type for s in d.strands} == {StrandType.SCAFFOLD, StrandType.STAPLE}
    assert Design(**d.model_dump()) == d
    assert validate_design(d).passed


def test_make_minimal_design_two_helix_no_staple_round_trip():
    d = make_minimal_design(n_helices=2, with_staple=False)
    assert len(d.helices) == 2
    assert len(d.strands) == 1
    assert d.strands[0].strand_type == StrandType.SCAFFOLD
    assert Design(**d.model_dump()) == d


def test_make_minimal_design_square_lattice_custom_length():
    d = make_minimal_design(lattice=LatticeType.SQUARE, helix_length_bp=21)
    assert d.lattice_type == LatticeType.SQUARE
    assert d.helices[0].length_bp == 21
    assert d.strands[0].domains[0].end_bp == 20
