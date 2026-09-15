"""Physical limits and known-profile checks for the standalone screening analysis."""
import numpy as np
import pytest
from experiments.electrode_relax.debye_analysis import closed_pb,debye_nm,fit_ion_ratio,bjerrum_nm,planar_potential
from scipy.constants import elementary_charge,epsilon_0


def test_debye_room_temperature_monovalent_reference():
    assert debye_nm(.3*.602214076)==pytest.approx(.5564,abs=.0001)
    assert debye_nm(.075*.602214076)==pytest.approx(2*debye_nm(.3*.602214076))


def test_exact_planar_potential_has_capacitor_slope_and_zero_external_field():
    grid=np.array([-1,0,.25,.75,1,2]);scale=elementary_charge*1e9/(epsilon_0*64)
    assert planar_potential(grid,np.array([0,1]),[-16,16],64)==pytest.approx(16*scale*np.clip(grid,0,1))
    # An unresolved neutral dipole retains its exact jump independently of grid size.
    assert planar_potential(np.array([0,1]),np.array([.331,.337]),[1,-1],64)==pytest.approx([0,-.006*scale])


def test_closed_pb_neutral_plates_are_uniform_and_preserve_ion_inventory():
    m=closed_pb(4,64,39,0)
    assert np.max(np.abs(m['u']))<1e-10
    assert m['center_per_nm3']==pytest.approx(39/(64*3.4),rel=1e-7)


def test_weakly_charged_closed_pb_matches_finite_gap_debye_solution():
    sigma=1e-4;m=closed_pb(4,64,39,sigma)
    x=np.array(m['x_nm']);kappa=1/m['debye_nm'];slope=4*np.pi*bjerrum_nm()*sigma
    analytical=slope*np.sinh(kappa*(x-2))/(kappa*np.cosh(kappa*1.7))
    assert m['u']==pytest.approx(analytical,abs=1e-9)


def test_larger_gap_reduces_midplane_field_at_matched_global_concentration():
    small=closed_pb(4,64,40,.25)
    large=closed_pb(6,64,60,.25)
    assert 0 < large['midplane_field_fraction'] < small['midplane_field_fraction']/3
    for model,number in ((small,40),(large,60)):
        assert np.trapezoid(model['na_per_nm3'],model['x_nm'])*64==pytest.approx(number,rel=2e-5)


def test_ion_ratio_fit_recovers_known_length_and_flags_unidentifiable_limit():
    x=np.arange(.05,4,.1);u=.2*np.sinh((x-2)/.65)+.03
    counts=np.array([1e7*np.exp(-u),1e7*np.exp(u)])
    fit=fit_ion_ratio(counts,x,4)
    assert fit['valid'] and not fit['at_bound']
    assert fit['lambda_nm']==pytest.approx(.65,abs=1e-5)
    assert not fit_ion_ratio(np.zeros((2,len(x))),x,4)['valid']


def test_time_axis_uses_segment_timestep_and_checks_dcd_header():
    from types import SimpleNamespace
    from experiments.electrode_relax.debye_analysis import frame_times_ns,physical_block_frames
    layout=SimpleNamespace(delta_ps=2.,nsavc=500,istart=500,n_frames=3)
    job={'segment':'s','start_time_ns':1.2,'timestep_fs':4}
    manifest={'segments':[{'name':'s','timestep_fs':4}]}
    assert frame_times_ns(job,layout,manifest)==pytest.approx([1.202,1.204,1.206])
    assert physical_block_frames(np.arange(1,1001)*.002)==150
    assert physical_block_frames(np.arange(1,201)*.010)==30
    manifest['segments'][0]['timestep_fs']=2
    with pytest.raises(ValueError,match='disagree'):
        frame_times_ns(job,layout,manifest)


def test_sampling_reports_correlated_frames_as_less_independent_evidence():
    from experiments.electrode_relax.debye_analysis import correlation_diagnostic
    rng=np.random.default_rng(19);noise=rng.normal(size=2000);correlated=np.zeros(2000)
    for i in range(1,len(noise)):correlated[i]=.95*correlated[i-1]+noise[i]
    result=correlation_diagnostic(correlated,.002)
    assert result['effective_frames'] < 200
    assert result['correlation_time_ns'] > .01


def test_water_mode_split_is_invariant_to_added_translation():
    from experiments.electrode_relax.water_mode_check import mode_temperatures,BOLTZMANN
    masses=np.array([[16.,1.,1.]])
    velocities=np.array([[[0.,0.,0.],[1.,0.,0.],[-1.,0.,0.]]])
    rotation=mode_temperatures(masses,velocities)
    translated=mode_temperatures(masses,velocities+np.array([2.,0.,0.]))
    assert rotation['translational_K']==0
    assert translated['rotational_K']==pytest.approx(rotation['rotational_K'])
    assert rotation['rotational_K']==pytest.approx(2/(3*BOLTZMANN))
    assert translated['translational_K']==pytest.approx(72/(3*BOLTZMANN))
