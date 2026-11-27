"""Algebraic research-analysis oracles; no molecular simulations."""
import numpy as np
import pytest
from tools.oxdna_tm_research.analyze import weighted_counts, passages
from tools.oxdna_tm_research.distance import parse_rows, table
from tools.oxdna_tm_research.nearest_neighbor import tm
from backend.core.oxdna_vmmc_precision import yield_curve


def test_inverse_bias_recovers_known_box_ratio_and_bulk_melting():
    # Physical box ratio=2; bias 1/2 on bound makes sampled occupancies equal.
    ts=np.array([60.,70.,80.]); energy=np.zeros((3,4));q=np.array([0,1,0,1])
    counts,weights=weighted_counts(energy,ts,70,q,[1,.5,1,.5])
    np.testing.assert_allclose(yield_curve(counts.sum(axis=0)),.5)
    np.testing.assert_allclose(weights.sum(axis=1),1)
    # Temperature-dependent constant energy offsets cannot change probabilities.
    offset=energy+np.array([.3,-.2,.5])[:,None]
    shifted,_=weighted_counts(offset,ts,70,q,[1,.5,1,.5])
    np.testing.assert_allclose(yield_curve(shifted.sum(axis=0)),.5)
    with pytest.raises(ValueError): weighted_counts(energy,ts,71,q,[1,1,1,1])


def test_two_coordinate_histogram_keeps_bin_identity_and_counts():
    # Two q states and two distance bins, intentionally unordered rows.
    text='1 1 0 0 0\n0 1 10 20 30\n1 0 40 50 60\n0 0 1 2 3\n'
    parsed=parse_rows(text,1,1)
    np.testing.assert_array_equal(parsed[:,0],[0,1,2,3])
    np.testing.assert_allclose(parsed[[0,2],3].sum(),33)
    np.testing.assert_allclose(parsed[[1,3],3].sum(),60)
    np.testing.assert_array_equal(table(np.ones(4),1)[:,:2],[[0,0],[1,0],[0,1],[1,1]])
    with pytest.raises(AssertionError):parse_rows(text.replace('0 1 10','0 0 10'),1,1)


def test_endpoint_round_trips_ignore_partial_contacts():
    assert passages(np.array([0,1,0,7,8,7,0,2,8]),8)==dict(passages=3,round_trips=1)
    assert passages(np.array([0,1,0,6,0]),8)==dict(passages=0,round_trips=0)


def test_nn_complement_invariance_and_concentration_response():
    seq='GCGTTGCG';other='CGCAACGC'
    a=tm(seq,.012,.3)
    assert a['tm_c']==pytest.approx(tm(other,.012,.3)['tm_c'])
    assert a['tm_c']>tm(seq,.001,.3)['tm_c']
    assert a['tm_c']>tm(seq,.012,.1)['tm_c']
    with pytest.raises(ValueError):tm('CPD',.012,.3)
