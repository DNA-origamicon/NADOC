"""Descriptive common-contact comparison of the five completed replicas."""
from pathlib import Path
import numpy as np
from experiments.cpd_anti_additive.compare_cube_pair_v9 import contact_keys
from experiments.cpd_anti_additive.validation_gate import read,source
from experiments.cpd_anti_additive.sella_pilot import save,now

def compare(root):
    spec=read(root/'observables_registration.json');endpoints=read(root/'startup_endpoints_lock_v6.json')
    keys={c:contact_keys(spec['cases'][c]) for c in ['anti','control']}
    common=sorted(set(keys['anti'])&set(keys['control']));assert len(common)==28
    paths=[('anti',1,'aggregate_native_audit_v8.json'),('control',1,'native_audit_v9.json'),('anti',2,'aggregate_native_audit_v12.json'),('control',2,'aggregate_native_audit_v14.json'),('anti',3,'aggregate_native_audit_v16.json')]
    results=[];pins=[]
    for case,rep,name in paths:
        p=root/case/f'replica-{rep}/validation'/name;a=read(p);assert a['passed']
        assert [v['step'] for v in a['series']]==list(range(535000,5530001,5000))
        indices=[keys[case].index(k) for k in common]
        d=np.array([v['observables']['polar_contact_distances_A'] for v in a['series']])[:,indices];assert np.isfinite(d).all()
        e=next(v for v in endpoints['records'] if v['case']==case and v['replica']==rep)
        baseline=np.array(e['observables']['polar_contact_distances_A'])[indices]
        results.append(dict(case=case,replica=rep,prepared_fraction=float(np.mean(baseline<3.5)),block_fractions=[float(np.mean(d[i:i+100]<3.5)) for i in range(0,1000,100)],per_contact_fraction=np.mean(d<3.5,axis=0).tolist()))
        pins.append(source(p))
    out=dict(at=now(),common_contacts=common,results=results,inputs=pins+[source(root/'observables_registration.json'),source(root/'startup_endpoints_lock_v6.json'),source(Path(__file__))],interpretation='Fixed preregistered identity intersection and3.5A cutoff. Frames and blocks are correlated,not independent replicates. Retain all outcomes and prepared baselines. Control3 pending; no causal,equilibrium or readiness inference.',simulation_ready=False,minimum_certified=False)
    save(root/'replicate_comparison_v16.json',out)
    print(results)

if __name__=='__main__':compare(Path('.development-artifacts/cpd-anti-gpu-cube-context-v5'))
