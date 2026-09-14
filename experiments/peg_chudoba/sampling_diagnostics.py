"""Cross-replica diagnostics; passing these is not proof of equilibrium.

Rank-normalized and folded split R-hat: Vehtari et al. (2021),
https://doi.org/10.1214/20-BA1221.
"""
import numpy as np
from scipy.special import ndtri
from scipy.stats import rankdata


def _rhat(x):
    n=x.shape[1]
    within=np.var(x,axis=1,ddof=1).mean()
    if within==0:return float('inf')
    between=n*np.var(x.mean(axis=1),ddof=1)
    return float(np.sqrt(((n-1)*within+between)/(n*within)))


def _rank_normalize(x):
    ranks=rankdata(x.ravel(),method='average')
    return ndtri((ranks-3/8)/(x.size+1/4)).reshape(x.shape)


def split_rhat(series):
    """Equal-length chains; split in half, rank-normalize, also test scale.

    The caller must supply the same observable and target ensemble. This
    function never silently thins, pads or infers simulation time from draws.
    Cadence and allocation remain explicit in run manifests. Constant traces
    return infinity rather than a spurious indication of convergence.
    """
    x=np.asarray(series,dtype=float)
    if x.ndim!=2 or x.shape[0]<2 or x.shape[1]<8 or not np.isfinite(x).all():
        raise ValueError('Need at least two finite, equal-length traces with eight samples each')
    half=x.shape[1]//2
    split=np.concatenate([x[:,:half],x[:,-half:]],axis=0)
    rank=_rhat(_rank_normalize(split))
    folded=_rhat(_rank_normalize(abs(split-np.median(split))))
    return dict(rank_normalized=rank,folded=folded,maximum=max(rank,folded))
