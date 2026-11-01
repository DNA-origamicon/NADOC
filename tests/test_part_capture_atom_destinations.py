"""Preallocated destinations preserve the existing live-copy semantics/bounds."""
from copy import deepcopy

import pytest
from backend.core.models import Design, ProteinAsset, ProteinAtom
from backend.core.part_capture_copy import allocate_atom_copies
from backend.core.part_verification_capture import capture, CaptureLimit


def source():
    atom = ProteinAtom(serial=1, name='CA', element='C', res_name='ALA', chain_id='A', res_seq=1,
                       x=1., y=2., z=3.)
    atom.__pydantic_fields_set__.discard('x')
    atom.__pydantic_fields_set__.add('future-marker')
    asset = ProteinAsset(atoms=[atom, atom], metadata={'atom_dict': atom.__dict__})
    return Design(protein_assets=[asset])


@pytest.mark.parametrize('count', [0, 1, 2])
def test_copy_parity_mutable_isolation_and_aliases(count):
    design = source()
    before = deepcopy(design)
    pool = allocate_atom_copies(count)
    candidate = capture(design, seconds=1., atom_copies=pool)
    expected = capture(design, seconds=1.)
    assert candidate == expected
    copied = candidate.protein_assets[0]
    assert copied.atoms[0] is copied.atoms[1]
    assert copied.metadata['atom_dict'] is copied.atoms[0].__dict__
    assert copied.atoms[0].model_fields_set == design.protein_assets[0].atoms[0].model_fields_set
    copied.atoms[0].x = 40.
    copied.atoms[0].model_fields_set.clear()
    assert design == before
    assert design.protein_assets[0].atoms[0].model_fields_set == before.protein_assets[0].atoms[0].model_fields_set


@pytest.mark.parametrize('limit', [{'max_nodes': 10}, {'max_bytes': 10}, {'seconds': 0.}])
def test_destinations_do_not_change_capture_refusals(limit):
    design = source()
    for pool in [None, allocate_atom_copies(2)]:
        with pytest.raises(CaptureLimit):
            capture(design, **limit, atom_copies=pool)


def test_unknown_atom_shape_keeps_deepcopy_fallback():
    design = source()
    design.protein_assets[0].atoms[0].__dict__['future'] = {'mutable': []}
    pool = allocate_atom_copies(2)
    candidate = capture(design, seconds=1., atom_copies=pool)
    assert len(pool) == 2
    candidate.protein_assets[0].atoms[0].__dict__['future']['mutable'].append(1)
    assert design.protein_assets[0].atoms[0].__dict__['future'] == {'mutable': []}


@pytest.mark.parametrize('count', [-1, 10_001, True, 1.5])
def test_destination_allocation_is_bounded(count):
    with pytest.raises(ValueError):
        allocate_atom_copies(count)
