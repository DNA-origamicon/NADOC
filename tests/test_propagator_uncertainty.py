"""Deep-ensemble uncertainty machinery (dev #6). torch-dependent → slow suite."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

pytestmark = pytest.mark.slow  # torch/GPU → test-dedicated session

from backend.ml.propagator.uncertainty import (  # noqa: E402
    EnsembleForceNet,
    calibration_score,
    reliability_curve,
)
from backend.ml.propagator.gnn import radius_edges  # noqa: E402


def _system(n=80, seed=0):
    rng = np.random.default_rng(seed)
    pos = rng.uniform(0, 16, (n, 3)).astype(np.float32)
    z = torch.tensor(rng.integers(1, 9, n))
    edges = torch.tensor(radius_edges(pos, 6.0))
    return z, torch.tensor(pos), edges


def test_ensemble_returns_mean_and_peratom_uncertainty():
    torch.manual_seed(0)
    z, x, edges = _system()
    ens = EnsembleForceNet(k=4, hidden=16, n_layers=2, cutoff=6.0).eval()
    mean, unc = ens(z, x, edges)
    assert mean.shape == x.shape and unc.shape == (x.shape[0],)
    assert (unc >= 0).all()
    # independently-initialised members disagree → strictly positive uncertainty somewhere
    assert unc.max().item() > 0


def test_identical_members_give_zero_uncertainty():
    torch.manual_seed(1)
    z, x, edges = _system()
    ens = EnsembleForceNet(k=3, hidden=16, n_layers=2, cutoff=6.0).eval()
    # copy member 0 into all → perfect agreement → ~0 uncertainty
    sd = ens.members[0].state_dict()
    for m in ens.members:
        m.load_state_dict(sd)
    _mean, unc = ens(z, x, edges)
    assert unc.max().item() < 1e-4


def test_calibration_detects_correlated_uncertainty():
    rng = np.random.default_rng(0)
    err = rng.random(500)
    unc = err + 0.05 * rng.standard_normal(500)  # uncertainty tracks error
    sc = calibration_score(unc, err)
    assert sc["pearson"] > 0.9 and sc["spearman"] > 0.9
    rc = reliability_curve(unc, err, n_bins=10)
    assert rc.shape[1] == 3 and sc["reliability_monotonicity"] > 0.8


def test_calibration_flat_for_random_uncertainty():
    rng = np.random.default_rng(1)
    err = rng.random(500)
    unc = rng.random(500)  # uncorrelated
    assert abs(calibration_score(unc, err)["pearson"]) < 0.2
