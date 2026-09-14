"""Uncertainty for the published observable sqrt(<Rg^2>), in nm."""
import numpy as np
from experiments.peg_chudoba.analyze_chain import correlation_time
from experiments.peg_chudoba.sampling_diagnostics import split_rhat


def summarize_rms(traces):
    squared = [np.asarray(x, dtype=float)**2 for x in traces]
    if len(squared)<2 or any(len(x)<36 or not np.isfinite(x).all() for x in squared):
        raise ValueError('Require at least two finite replica traces of 36 draws')
    means = np.array([x.mean() for x in squared])
    rms = np.sqrt(means.mean())  # Equal weight per independent replica.
    if rms<=0:raise ValueError('Radius must be positive')
    taus = [correlation_time(x) for x in squared]
    effective = [len(x)/tau if np.var(x)>0 else 0. for x,tau in zip(squared,taus)]
    auto = [x.std(ddof=1)*np.sqrt(tau/len(x)) for x,tau in zip(squared,taus)]
    block = [np.array([b.mean() for b in np.array_split(x,18)]).std(ddof=1)/np.sqrt(18) for x in squared]
    within = np.sqrt(np.sum(np.maximum(auto,block)**2))/len(squared)
    between = means.std(ddof=1)/np.sqrt(len(squared))
    # Delta method applied once to the pooled squared-radius estimate.
    sem = max(within,between)/(2*rms)
    rhat = split_rhat(squared)['maximum'] if len({len(x) for x in squared})==1 else float('inf')
    return dict(rms_rg_nm=float(rms),conservative_sem_nm=float(sem),
                minimum_seed_effective_samples=float(min(effective)),
                rank_folded_split_rhat=float(rhat) if np.isfinite(rhat) else None,
                extension_recommended=bool(rhat>=1.01 or min(effective)<100),
                largest_seed_half_difference_nm=float(max(abs(np.sqrt(x[:len(x)//2].mean())-np.sqrt(x[len(x)//2:].mean())) for x in squared)))
