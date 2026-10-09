"""Descriptive comparison on identical preregistered atom contacts; no inference."""
import json,sys,os
from pathlib import Path
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source
from experiments.cpd_anti_additive.sella_pilot import save,now


def contact_keys(selection):
 identity={idx:(r['segid'],r['resid'],name) for r in selection['residues'] for name,idx in r['atoms'].items()}
 keys=[tuple(sorted(identity[idx] for idx in c['atoms'])) for c in selection['source_close_interstrand_polar_contacts']]
 assert len(keys)==len(set(keys))
 return keys


def compare(control_audit,output):
 root=REPO/'.development-artifacts/cpd-anti-gpu-cube-context-v5';spec=read(root/'observables_registration.json')
 ap=root/'anti/replica-1/validation/aggregate_native_audit_v8.json';a=read(ap);c=read(control_audit);assert a['passed'] and c['passed']
 keys={case:contact_keys(spec['cases'][case]) for case in ['anti','control']};common=sorted(set(keys['anti'])&set(keys['control']));assert common
 values={}
 for case,audit in [('anti',a),('control',c)]:
  assert [v['step'] for v in audit['series']]==list(range(535000,5530001,5000))
  indices=[keys[case].index(k) for k in common]
  all_d=np.array([v['observables']['polar_contact_distances_A'] for v in audit['series']]);assert np.isfinite(all_d).all()
  values[case]=all_d[:,indices]
 blocks=[]
 for n in range(10):
  b={case:dict(contact_fraction=float(np.mean(d[n*100:(n+1)*100]<3.5)),mean_contact_distance_A=float(np.mean(d[n*100:(n+1)*100]))) for case,d in values.items()}
  blocks.append(dict(ns=n+1,**b,anti_minus_control_fraction=b['anti']['contact_fraction']-b['control']['contact_fraction']))
 baseline={}
 endpoints=read(root/'startup_endpoints_lock_v6.json')
 for case in ['anti','control']:
  endpoint=next(v for v in endpoints['records'] if v['case']==case and v['replica']==1)
  ds=np.array(endpoint['observables']['polar_contact_distances_A'])[[keys[case].index(k) for k in common]]
  baseline[case]=dict(contact_fraction=float(np.mean(ds<3.5)),mean_contact_distance_A=float(ds.mean()))
 per_pair=[dict(identity=key,anti_mean_A=float(values['anti'][:,i].mean()),control_mean_A=float(values['control'][:,i].mean()),anti_fraction=float((values['anti'][:,i]<3.5).mean()),control_fraction=float((values['control'][:,i]<3.5).mean())) for i,key in enumerate(common)]
 result=dict(at=now(),common_contacts=len(common),anti_source_contacts=len(keys['anti']),control_source_contacts=len(keys['control']),selection='Intersection of preregistered source-contact identities (segid,resid,atomname),fixed3.5A descriptive distance cutoff; no outcome-driven contact selection.',blocks=blocks,prepared_baseline=baseline,per_pair=per_pair,interpretation='One replica per condition; correlated trajectory frames/blocks are not independent replicates. No significance,equilibrium,kinetic,mechanical or causal lesion effect claim. Additional registered replicas required.',inputs=[source(ap),source(control_audit),source(root/'observables_registration.json'),source(root/'startup_endpoints_lock_v6.json'),source(Path(__file__))],simulation_ready=False)
 save(output,result);print(json.dumps(dict(common_contacts=len(common),prepared_baseline=baseline,blocks=blocks),indent=2))

if __name__=='__main__':compare(Path(sys.argv[1]),Path(sys.argv[2]))
