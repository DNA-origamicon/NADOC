"""Unbinned WHAM/MBAR for fixed-temperature, fixed-window native MD sampling.

Common physical energies cancel when fitting windows at the same temperature.
Biases are the single pair potential, not the sum of both LTCOMTrap reports.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


def tabulated_bias(distance, centers, stiffness, grid_step=.005, grid_max=7.):
    distance=np.asarray(distance,dtype=float)
    if np.any(~np.isfinite(distance)) or np.any(distance<0) or np.any(distance>=grid_max):
        raise ValueError('Sample outside the tabulated bias domain.')
    left=np.floor(distance/grid_step)*grid_step
    fraction=(distance-left)/grid_step
    centers=np.asarray(centers)[:,None]
    return .5*stiffness*((1-fraction)*(left-centers)**2+fraction*(left+grid_step-centers)**2)


def solve(bias, counts, thermal_energy):
    """Return target weights, overlap matrix, and dimensionless free energies."""
    u=np.asarray(bias,dtype=float)/thermal_energy
    counts=np.asarray(counts,dtype=float)
    if u.ndim!=2 or len(counts)!=len(u) or np.any(counts<=0) or int(counts.sum())!=u.shape[1] or not np.isfinite(u).all():
        raise ValueError('Invalid umbrella samples/counts.')
    logn=np.log(counts)
    def objective(x):
        f=np.r_[0.,x]
        logits=logn[:,None]+f[:,None]-u
        den=logsumexp(logits,axis=0)
        grad=np.exp(logits-den).sum(axis=1)-counts
        return (den.sum()-counts@f)/counts.sum(),grad[1:]/counts.sum()
    result=minimize(objective,np.zeros(len(counts)-1),jac=True,method='L-BFGS-B',options={'ftol':1e-14,'gtol':1e-10,'maxiter':5000,'maxls':50})
    if np.max(np.abs(objective(result.x)[1]))>1e-7:
        raise ValueError('Umbrella normalization did not converge.')
    f=np.r_[0.,result.x]
    den=logsumexp(logn[:,None]+f[:,None]-u,axis=0)
    logw=-den;logw-=logsumexp(logw);weights=np.exp(logw)
    window_weights=np.exp(f[:,None]-u-den)
    overlap=(window_weights@window_weights.T)*counts[None,:]
    return weights,overlap,f,den


def statistical_inefficiency(values):
    a=np.asarray(values,dtype=float);a=a-a.mean()
    if len(a)<4 or np.var(a)<1e-15:return 1.
    n=len(a);fft=np.fft.rfft(a,n=2*n)
    ac=np.fft.irfft(fft*fft.conj())[:n]/np.arange(n,0,-1)
    ac/=ac[0]
    total=0.
    for i in range(1,n-1,2):
        pair=ac[i]+ac[i+1]
        if pair<=0:break
        total+=pair
    return float(min(n,max(1.,1+2*total)))


def bulk_yield(p_bound):
    # Single heterodimer finite-size correction, same convention as VMMC.
    if p_bound>=1:return 1.
    ratio=p_bound/(1-p_bound)
    return 2*ratio/(2*ratio+1+np.sqrt(4*ratio+1))


def summarize(samples,centers,stiffness,temperature_c,grid_max,bootstrap=40,seed=7201):
    if len(samples)!=len(centers) or any(len(a)<20 for a in samples):
        raise ValueError('Each window needs at least 20 production samples.')
    counts=[len(a) for a in samples];all_data=np.concatenate(samples)
    bias=tabulated_bias(all_data[:,1],centers,stiffness,grid_max=grid_max)
    weights,overlap,f,_=solve(bias,counts,(temperature_c+273.15)/3000)
    bound=all_data[:,2]>0
    probability=float(np.clip(weights@bound,0,1))
    details=[]
    for a in samples:
        gs=[statistical_inefficiency(a[:,c]) for c in (1,2)]
        details.append({'samples':len(a),'distance_range':[float(a[:,1].min()),float(a[:,1].max())],
            'q_range':[int(a[:,2].min()),int(a[:,2].max())],
            'bound_unbound_transitions':int(np.count_nonzero((a[1:,2]>0)!=(a[:-1,2]>0))),
            'inefficiency':max(gs),'block_length':max(1,min(len(a)//4,int(np.ceil(5*max(gs)))))})
    rng=np.random.default_rng(seed);estimates=[]
    for _ in range(bootstrap):
        resampled=[]
        for a,d in zip(samples,details):
            block=d['block_length'];starts=rng.integers(0,len(a),size=int(np.ceil(len(a)/block)))
            ids=np.concatenate([(np.arange(block)+i)%len(a) for i in starts])[:len(a)]
            resampled.append(a[ids])
        joined=np.concatenate(resampled)
        bw,_,_,_=solve(tabulated_bias(joined[:,1],centers,stiffness,grid_max=grid_max),counts,(temperature_c+273.15)/3000)
        estimates.append(float(np.clip(bw@(joined[:,2]>0),0,1)))
    adjacency=(overlap+overlap.T)>.01
    visited={0}
    while True:
        expanded=visited|{j for i in visited for j in np.flatnonzero(adjacency[i])}
        if expanded==visited:break
        visited=expanded
    reasons=[]
    if len(visited)!=len(counts):reasons.append('Disconnected umbrella overlap graph.')
    if sum(d['bound_unbound_transitions'] for d in details)<20:reasons.append('Too few observed binding/unbinding transitions.')
    if any(d['samples']/d['inefficiency']<20 for d in details):reasons.append('Some windows have fewer than 20 estimated independent samples or an unresolved coordinate.')
    # A single campaign cannot establish lack of hysteresis along hidden coordinates.
    reasons.append('Independent bound-start/unbound-start agreement not yet established.')
    return {'status':'inconclusive','reasons':reasons,'sampling_temperature_c':temperature_c,
        'p_bound_box':probability,'duplex_yield_bulk':float(bulk_yield(probability)),
        'p_bound_block_bootstrap_95ci':np.quantile(estimates,[.025,.975]).tolist() if estimates else None,
        'weight_ess_without_time_correction':float(1/(weights@weights)),
        'overlap':overlap.tolist(),'window_free_energies_kT':f.tolist(),'windows':details,
        'qualification':'Fixed-temperature estimate; no melting temperature is inferred from this point.'}
