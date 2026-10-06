"""Replay eight native outputs and both constrained curvature comparisons."""
import re
from pathlib import Path
import numpy as np
from experiments.cpd_anti_additive.competing_curvature_v3 import validate,ROOT
from experiments.cpd_anti_additive.validation_gate import checked,read,source
from experiments.cpd_anti_additive.sella_pilot import save,now,geometry_audit
p=validate();rows=[];energies={}
for case in p['cases']:
 folder=ROOT/case['label'];result=read(folder/'result.json');data=read(checked(result['input']));native=checked(result['native']).read_text();checked(result['plan'])
 en=[float(v) for v in re.findall(r'^\s*Total Energy\s*=\s*([-+\d.Ee]+)\s*\[Eh\]',native,re.M)]
 assert en and abs(en[-1]-result['energy_hartree'])<1e-10
 table=native.rsplit('-Total Gradient:',1)[1].split('*** tstop()',1)[0]
 parsed=re.findall(r'^\s*(\d+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*$',table,re.M)
 assert [int(r[0]) for r in parsed]==list(range(1,50))
 gradient=np.array([[float(v) for v in r[1:]] for r in parsed]);error=float(abs(gradient-np.array(result['gradient_au'])).max());assert error<6e-13
 residuals=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)];assert residuals and max(residuals)<=p['options']['solver_convergence']
 basin=next(b for b in p['basins'] if b['label']==data['basin']);plan=basin['plan'];graph=read(checked(plan['record']['model_graph']))
 audit=geometry_audit(np.array(data['geometry_bohr']),dict(plan,geometry_bohr=basin['x']),graph);assert audit['constraint_passed'] and audit['chemistry_passed']
 energies[case['label']]=result['energy_hartree'];rows.append(dict(case=case['label'],result=source(folder/'result.json'),native_energy=en[-1],printed_gradient_error=error,torsion_error=audit['torsion_error_deg']))
curves=[]
for b in p['basins']:
 c=[(energies[f"{b['label']}-{h:+.2f}"]+energies[f"{b['label']}-{-h:+.2f}"]-2*b['energy'])/h**2 for h in [.02,.04]]
 difference=abs(c[0]-c[1])/max(abs(v) for v in c);assert min(c)>0 and difference<=.1
 prior=next(r for r in read(ROOT/'assessment.json')['curves'] if r['basin']==b['label']);assert np.array_equal(c,prior['curvatures_hartree_per_bohr2'])
 curves.append(dict(basin=b['label'],curvatures=c,relative_step_difference=difference))
out=ROOT/'native_audit.json';assert not out.exists()
save(out,dict(at=now(),passed=True,native_gradients_verified=8,cases=rows,curves=curves,claim=p['claim'],minimum_certified=False,simulation_ready=False,new_qm_evaluations=0))
print('Verified8 native gradients and both constrained directional curvatures; no minimum certificate.')
