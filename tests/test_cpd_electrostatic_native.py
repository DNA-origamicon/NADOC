"""Reject scientific evidence mismatches before accepting fixed-geometry HF data."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_electrostatic_pilot import audit_hf_native


TEXT = """
RHF Reference
SCF Algorithm Type is DF.
Energy and wave function converged.
Energy threshold   = 1.00e-12
Density threshold  = 1.00e-12
Basis Set: 6-31G(D)
Geometry (in Angstrom), charge = 0, multiplicity = 1:
 O 0.000000000000 0.000000000000 0.000000000000 15.99491462
 H 0.957200000000 0.000000000000 0.000000000000 1.00782503
 H -0.239987200000 0.927297000000 0.000000000000 1.00782503
@DF-RHF Final Energy: -76.00000000000000
NADOC_DIPOLE_AU 0.200000000000 0.300000000000 0.000000000000
"""
X = np.array([[0., 0., 0.], [.9572, 0., 0.], [-.2399872, .927297, 0.]])


def audit(text=TEXT, **overrides):
    args=dict(elements=['O','H','H'],x_angstrom=X,algorithm='df',energy=-76.,dipole=[.2,.3,0.])
    args.update(overrides)
    return audit_hf_native(text, **args)


def test_accept_matching_df_and_direct_native_evidence():
    assert audit()['passed']
    assert audit(TEXT.replace('Type is DF.', 'Type is DIRECT.').replace('@DF-RHF', '@RHF'), algorithm='direct')['passed']


@pytest.mark.parametrize('old,new', [
    ('Type is DF.', 'Type is DIRECT.'),
    ('Energy threshold   = 1.00e-12', 'Energy threshold   = 1.00e-06'),
    ('Density threshold  = 1.00e-12', 'Density threshold  = 1.00e-06'),
    ('6-31G(D)', 'CC-PVDZ'),
    ('in Angstrom', 'in Bohr'),
    ('charge = 0', 'charge = 1'),
    (' O ', ' N '),
    ('0.957200000000', '0.957200001000'),
    ('-76.00000000000000', '-75.00000000000000'),
    ('0.300000000000', '0.300000100000'),
])
def test_reject_native_method_units_identity_and_numerical_mismatches(old,new):
    with pytest.raises(ValueError):
        audit(TEXT.replace(old,new))


@pytest.mark.parametrize('field,value', [('energy',float('nan')),('dipole',[float('nan'),0,0]),('x_angstrom',X*float('nan'))])
def test_reject_nonfinite_results(field,value):
    with pytest.raises(ValueError):
        audit(**{field:value})


def test_reject_concatenated_calculations_and_missing_evidence():
    with pytest.raises(ValueError):
        audit(TEXT+TEXT)
    with pytest.raises(ValueError):
        audit(TEXT.replace('NADOC_DIPOLE_AU','MISSING'))
