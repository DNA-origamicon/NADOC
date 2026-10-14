import pytest
import numpy as np

from experiments.cpd_anti_additive.corrected_core_hessian import admit_group,execution_groups,reconstruct_raw_hessian,analytic_gradient_input


def test_chunks_keep_both_sides_of_each_displacement_together():
    first=execution_groups(range(105))
    second=execution_groups(range(105,211))
    assert first[0]==[0]
    assert first[-1]==[103,104]
    assert second[0]==[105,106]
    assert second[-1]==[209,210]
    assert len(first)+len(second)==106
    for bad in ([1],[2,3],[1,3],[0,1,2,3]):
        with pytest.raises(ValueError,match='pair is split'):
            execution_groups(bad)


def test_pair_admission_reserves_checkpoint_time_and_stops_on_slowdown():
    assert admit_group(1000,2,[60])==300
    with pytest.raises(RuntimeError,match='boundary time'):
        admit_group(250,2,[60])
    # The same remaining time becomes inadequate when measured task cost rises.
    assert admit_group(500,2,[60])==300
    with pytest.raises(RuntimeError,match='boundary time'):
        admit_group(500,2,[150])
    assert admit_group(2000,2,[250])==600


def test_raw_hessian_preserves_mass_weighting_pair_signs_and_antisymmetry():
    rng=np.random.default_rng(23)
    masses=np.array([1.,12.,16.])
    weights=np.repeat(np.sqrt(masses),3)
    q=np.linalg.qr(rng.normal(size=(9,9)))[0][:,:6]
    raw=rng.normal(size=(6,6))
    h=.01; x0=rng.normal(size=9); coordinates=[];gradients=[]
    for i in range(6):
        # Deliberately nonconservative linear response to exercise raw asymmetry.
        for sign in (-1,1):
            coordinates.append(x0+sign*h*q[:,i]/weights)
            gradients.append(sign*h*(q@raw[:,i])*weights)
    measured,basis,cartesian=reconstruct_raw_hessian(masses,coordinates,gradients,h)
    assert np.max(abs(measured-raw))<1e-11
    assert np.max(abs(measured-measured.T))>1
    assert np.max(abs(basis+q))<1e-11
    expected=(q@(.5*(raw+raw.T))@q.T)*weights[:,None]*weights[None,:]
    assert np.max(abs(cartesian-expected))<1e-10


def test_raw_hessian_rejects_wrong_step_and_unpaired_or_nonfinite_data():
    x=np.array([[-.01,0.,0.],[.01,0.,0.]])
    g=x.copy()
    with pytest.raises(ValueError,match='orthonormal'):
        reconstruct_raw_hessian([1.],x,g,.005)
    with pytest.raises(ValueError,match='Invalid paired'):
        reconstruct_raw_hessian([1.],x[:1],g[:1],.01)
    g[0,0]=np.nan
    with pytest.raises(ValueError,match='Invalid paired'):
        reconstruct_raw_hessian([1.],x,g,.01)


def test_gradient_input_normalization_preserves_physical_options_and_original():
    inp={'specification':{'driver':'gradient','model':{'method':'mp2','basis':'6-31g(d)'},
                         'keywords':{'FINDIF__DISP_SIZE':.01,'DF_FITTING_CONDITION':1e-10}}}
    normalized=analytic_gradient_input(inp,.01)
    assert normalized['specification']['keywords']=={'DF_FITTING_CONDITION':1e-10}
    assert inp['specification']['keywords']['FINDIF__DISP_SIZE']==.01
    with pytest.raises(ValueError,match='Unexpected displacement'):
        analytic_gradient_input(inp,.02)
    with pytest.raises(ValueError,match='Unexpected displacement'):
        analytic_gradient_input(normalized,.01)
