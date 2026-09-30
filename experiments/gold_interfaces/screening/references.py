"""Reproducible historical-window and deterministic PB estimator comparisons."""
import json
import numpy as np
from experiments.electrode_relax.debye_analysis import closed_pb, fit_ion_ratio
from experiments.gold_interfaces.screening.campaign import ROOT, REPO
from experiments.gold_interfaces.screening.analyze import old_reference


def main():
    (ROOT/'historical_comparison.json').write_text(json.dumps(old_reference(),indent=2))
    rows=[]
    for area in (64.,64.52762582044262):
        for stern in (.3,.6):
            for eps in (78.3,100.):
                pb=closed_pb(6,area,64,.25,eps,300.,stern);x=np.arange(.05,6,.1)
                expected=np.array([np.interp(x,pb['x_nm'],pb[k]) for k in ('na_per_nm3','cl_per_nm3')])*area*.1*200
                rows.append(dict(area_nm2=area,stern_nm=stern,assumed_dielectric=eps,pb_debye_nm=pb['debye_nm'],
                    fit=fit_ion_ratio(expected,x,6,.6),interpretation='Deterministic canonical PB profile, not MD; expected counts scaled to 200 frames'))
    (ROOT/'estimator_reference.json').write_text(json.dumps(rows,indent=2))
    z=np.load(REPO/'.development-artifacts/electrode_remote_40ns_20260914/runpod/screening_frame_cache.npz')
    t=z['times'];h=z['h'];x=np.arange(.05,6,.1);rows=[]
    for start in np.arange(20,40,.2):
        selected=(t>start+1e-8)&(t<=start+.2+1e-8)
        rows.append(dict(start_ns=float(start),end_ns=float(start+.2),fit=fit_ion_ratio(h[selected].sum(axis=0),x,6.)))
    values=np.array([r['fit']['lambda_nm'] for r in rows if r['fit']['valid']])
    result=dict(windows=rows,length_quantiles_025_50_975_nm=np.quantile(values,[.025,.5,.975]).tolist(),
        at_bound_count=sum(r['fit']['at_bound'] for r in rows),
        interpretation='Empirical variability among 100 adjacent late-trajectory 200 ps windows. Not a confidence interval; neighboring windows may be correlated.')
    (ROOT/'historical_short_window_variability.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
