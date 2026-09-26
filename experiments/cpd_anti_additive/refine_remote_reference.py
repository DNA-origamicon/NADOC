"""Isolated joint refinement using lower-energy endpoint2 training conformer."""
import argparse,copy,json,sys
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive import refine_joint as joint
from experiments.cpd_anti_additive.core_baseline import checked,source
base_loader=joint.load_cases

def load_cases():
    cases=base_loader();art=REPO/'.development-artifacts';audit=json.loads((art/'cpd-anti-remote-unconstrained-v1/endpoint-2-baseline-well/assessment.json').read_text());target=checked(audit['optimized']);frequency=json.loads((art/'cpd-anti-remote-frequency-v1/frequency/frequency_audit.json').read_text());assert frequency['status']=='passed_candidate_harmonic_minimum'
    for c in cases:
        if c['endpoint']!=2:continue
        c['report']=copy.deepcopy(c['report']);c['report']['previous_training_target']=source(c['target']);c['target']=target;c['qm']=np.array([list(map(float,line.split()[1:])) for line in target.read_text().splitlines()[2:] if line.strip()]);c['initial']=c['qm'].copy();c['minimum']=target;c['report']['sources'][0]=source(target)
        for a in c['report']['angles']:a['qm_deg']=joint.angle(c['qm'],[c['names'].index(n) for n in a['atoms']])
        c['report']['reference_scope']='Lower-energy endpoint2 conformer; original retained for retrospective validation; soft-mode stiffness limitation remains'
    return cases

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--typed-input',type=Path,required=True);p.add_argument('--warm-start',type=Path);p.add_argument('--all-angles',action='store_true');p.add_argument('--all-bonds',action='store_true');p.add_argument('--max-nfev',type=int,default=100);a=p.parse_args();joint.load_cases=load_cases;joint.main(a.root.resolve(),a.all_angles,a.typed_input.resolve(),a.warm_start.resolve() if a.warm_start else None,a.all_bonds,a.max_nfev)
