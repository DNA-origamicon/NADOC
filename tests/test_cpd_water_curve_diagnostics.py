"""Curve acquisition must distinguish a bracketed contact well from incomplete data."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_water_curves import curve_diagnostics

R=np.array([1.5,1.7,1.9,2.1,2.3,2.5,2.7])


def test_bracket_and_interpolated_minimum_have_correct_units_and_offset():
    d=curve_diagnostics(R,4*(R-1.85)**2-6)
    assert d['bracketed'] and d['attractive'] and not d['needs_shape_review']
    assert d['sampled_distance_angstrom']==1.9
    q=d['quadratic_diagnostic']
    assert q['raw_distance_angstrom']==pytest.approx(1.85)
    assert q['raw_energy_kcal_mol']==pytest.approx(-6)
    assert q['curvature_kcal_mol_angstrom2']==pytest.approx(8)
    assert q['inside_neighbor_interval']


@pytest.mark.parametrize('energy',[-R,R,-np.ones(7),np.array([0,-1,-2,-2,-1,0,1])])
def test_boundaries_flat_curves_and_tied_minima_require_review(energy):
    d=curve_diagnostics(R,energy)
    assert not d['bracketed'] and d['needs_shape_review']
    assert d['quadratic_diagnostic'] is None


def test_nonattractive_well_and_secondary_wiggle_are_not_accepted():
    d=curve_diagnostics(R,(R-1.9)**2+1)
    assert d['bracketed'] and not d['attractive'] and d['needs_shape_review']
    d=curve_diagnostics(R,[-1,-2,-3,-2,-2.1,-1,-.5])
    assert d['bracketed'] and not d['monotone_flanks'] and d['needs_shape_review']


@pytest.mark.parametrize('r,e',[(R[::-1],R),(R,np.ones(6)),([1,1,2],[0,-1,0]),([1,2,3],[0,float('nan'),0])])
def test_invalid_or_nonfinite_curve_rejected(r,e):
    with pytest.raises(ValueError):curve_diagnostics(r,e)
