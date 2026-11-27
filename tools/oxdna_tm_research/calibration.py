"""Limited estimator coverage stress test; not molecular convergence evidence."""
import json
import time
import numpy as np
from backend.core.oxdna_vmmc_precision import precision_report

def main():
    started=time.monotonic();temps=np.arange(64.,78.01,.5); rng=np.random.default_rng(982911)
    results=[]
    # At Tm the heterodimer box bound/unbound ratio is 2.
    # Analytic ratio(T)=2 exp[-0.18(T-70)]. Sampling at T=70 has p=2/3.
    # Persistent binary chains with known stationary law test correlated intervals.
    for persistence in (0., .95, .999):
        covered=available=accepted=0; widths=[]
        for trial in range(200):
            arrays=[]
            for replica in range(4):
                q=np.zeros(2000,dtype=bool); q[0]=replica%2==0
                for j in range(1,len(q)):
                    q[j]=q[j-1] if rng.random()<persistence else rng.random()<2/3
                w=np.exp(-.18*(temps-70))
                arrays.append(np.stack([np.broadcast_to((~q)[:,None],(len(q),len(temps))),q[:,None]*w],axis=1))
            r=precision_report(arrays,temps,target=1,bootstrap=400,max_looks=1,seed=trial)
            if r['ci95_c'] is not None:
                available+=1;covered+=int(r['ci95_c'][0]<=70<=r['ci95_c'][1]);widths.append(r['halfwidth_c'])
            accepted+=int(r['status']=='target_met')
        results.append(dict(persistence=persistence,trials=200,available_intervals=available,intervals_covering_true_tm=covered,target_accepted=accepted,median_halfwidth=None if not widths else float(np.median(widths))))
    print(json.dumps(dict(results=results,elapsed_seconds=time.monotonic()-started,qualification='Synthetic two-state coverage stress test, 200 trials per condition. Too small to validate 95% coverage; cannot represent hidden molecular states.'),indent=2))

if __name__=='__main__': main()
