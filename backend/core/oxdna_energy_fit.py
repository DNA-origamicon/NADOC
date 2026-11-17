"""Full-history exponential relaxation diagnosis, with explicit identifiability checks."""
import numpy as np
from scipy.optimize import minimize_scalar


def effective_samples(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    centered = values - values.mean()
    variance = float(centered @ centered)
    if np.max(np.abs(centered)) < 1e-8:
        return float(n)
    spectrum = np.fft.rfft(centered, n=2*n)
    correlations = np.fft.irfft(spectrum * spectrum.conjugate(), n=2*n)[:n] / variance
    nonpositive = np.flatnonzero(correlations[1:] <= 0)
    end = int(nonpositive[0]) + 1 if len(nonpositive) else n
    return float(n / (1 + 2 * correlations[1:end].sum()))


def fit_energy(times, energies, tolerance=.02, min_effective_samples=10):
    """Fit E(t)=E_inf+A exp(-(t-t0)/tau) to EVERY distinct recorded time.

    A flat-history fallback is explicitly a constant model, never a fabricated tau.
    Parameter error estimates are local, residual-correlation adjusted diagnostics,
    not a thermodynamic-equilibrium confidence statement.
    """
    t, y = np.asarray(times, dtype=float), np.asarray(energies, dtype=float)
    result = {'method': 'full-history-exponential-v1', 'samples': len(y), 'passed': False,
              'phase': 'unresolved', 'tolerance': tolerance, 'required_effective_samples': 3*min_effective_samples}
    if len(y) < max(30, 3*min_effective_samples) or len(t) != len(y):
        return {**result, 'reason': 'insufficient samples'}
    if not np.isfinite(t).all() or not np.isfinite(y).all() or np.any(np.diff(t) <= 0):
        return {**result, 'reason': 'nonfinite samples or non-increasing time'}
    span = float(t[-1]-t[0]); x = (t-t[0])/span
    # Global coarse profile followed by bounded refinement; every objective uses all rows.
    def solve(log_tau):
        tau = np.exp(log_tau)
        design = np.column_stack((np.ones(len(x)), np.exp(-x/tau)))
        coeff = np.linalg.lstsq(design, y, rcond=None)[0]
        residual = y-design@coeff
        return float(residual@residual), coeff, residual
    grid = np.linspace(np.log(.001), np.log(100), 65)
    best = int(np.argmin([solve(q)[0] for q in grid]))
    opt = minimize_scalar(lambda q: solve(q)[0], bounds=(grid[max(0,best-1)], grid[min(64,best+1)]), method='bounded', options={'xatol': 1e-12})
    sse, coeff, residual = solve(opt.x)
    tau = float(np.exp(opt.x)); c, a = map(float,coeff)
    neff = effective_samples(residual)
    exponential = np.exp(-x/tau)
    jac = np.column_stack((np.ones(len(x)), exponential, a*exponential*x/tau))
    condition = float(np.linalg.cond(jac))
    identifiable = bool(np.isfinite(condition) and condition < 1e8 and .0011 < tau < 99)
    covariance = np.linalg.pinv(jac.T@jac) * sse/max(1,len(y)-3) * len(y)/max(1,neff)
    remainder = float(a*np.exp(-1/tau))
    gradient = np.array([0., np.exp(-1/tau), remainder/tau])
    remainder_se = float(np.sqrt(max(0.,gradient@covariance@gradient)))
    upper = abs(remainder) + 1.96*remainder_se
    residual_means = [float(v.mean()) for v in np.array_split(residual, min(10,len(y)//10))]
    residual_bias = max(abs(v) for v in residual_means)
    recent = residual[-max(20,len(y)//10):]
    recent_drift = abs(float(np.polyfit(np.linspace(0,1,len(recent)), recent, 1)[0]))
    total_variance = float(np.sum((y-y.mean())**2))
    r2 = 1-sse/total_variance if total_variance > 1e-24 else 1.
    result.update(model='exponential', time_origin=float(t[0]), elapsed_time=span,
                  asymptote=c, amplitude=a, tau=tau*span, elapsed_tau=1/tau,
                  fraction_remaining=float(np.exp(-1/tau)), predicted_remaining_change=abs(remainder),
                  remaining_change_upper_95=upper, endpoint_slope=remainder/(-tau*span),
                  rmse=float(np.sqrt(sse/len(y))), r_squared=float(r2), effective_samples=neff,
                  identifiable=identifiable, residual_block_bias=residual_bias,
                  recent_residual_drift=recent_drift,
                  uncertainty='Approximate local 95% bound, adjusted for residual autocorrelation; not an equilibrium guarantee.')
    # Flat noisy histories have no identifiable exponential time constant. Diagnose
    # the whole history with a bounded linear trend and consistent block means.
    linear = np.column_stack((np.ones(len(x)),x))
    b = np.linalg.lstsq(linear,y,rcond=None)[0]; lr=y-linear@b
    leff=effective_samples(lr)
    lc=np.linalg.inv(linear.T@linear)*float(lr@lr)/max(1,len(y)-2)*len(y)/max(1,leff)
    trend_upper=abs(float(b[1]))+1.96*float(np.sqrt(lc[1,1]))
    means=[float(v.mean()) for v in np.array_split(y,min(10,len(y)//10))]
    flat = (float(np.ptp(means)) <= tolerance and trend_upper <= tolerance
            and leff >= 3*min_effective_samples)
    if flat:
        result.update(model='constant', phase='flat', passed=True, reason='entire history consistent with a flat energy level',
                      asymptote=float(y.mean()), amplitude=0., tau=None, elapsed_tau=None,
                      fraction_remaining=None, identifiable=False, effective_samples=leff,
                      predicted_remaining_change=None, remaining_change_upper_95=None,
                      endpoint_slope=None, linear_drift_upper_95=trend_upper)
    else:
        passed = identifiable and neff >= 3*min_effective_samples and r2 >= .5 and upper <= tolerance and residual_bias <= tolerance and recent_drift <= tolerance
        phase = ('plateau' if passed else 'unresolved' if not identifiable or r2 < .5 or residual_bias > tolerance
                 else 'early_relaxation' if 1/tau < 1 else 'relaxing')
        result.update(passed=bool(passed), phase=phase, reason=('fitted exponential has reached its plateau' if passed else
                      'plateau not demonstrated: remaining change, fit uncertainty, residual structure, or insufficient independent data'))
    return result


def fitted_values(times, fit):
    t=np.asarray(times,dtype=float)
    if 'asymptote' not in fit:
        return []
    if fit['model']=='constant':
        return np.full(len(t),fit['asymptote']).tolist()
    return (fit['asymptote']+fit['amplitude']*np.exp(-(t-fit['time_origin'])/fit['tau'])).tolist()
