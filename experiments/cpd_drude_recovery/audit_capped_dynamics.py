"""Audit every saved capped trajectory frame; thermal diagnostic, not release."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked,source,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from backend.core.dcd_fast import read_layout,read_frame

parser=argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-capped-dynamics-v1'))
parser.add_argument('--stage', type=Path, default=Path('.development-artifacts/cpd-drude-bonded-equilibrium-v2'))
args=parser.parse_args()
root=args.root.resolve()
plan=json.loads((root/'plan.json').read_text())
for record in plan['execution_inputs']:checked(record)
_,atoms,sections=atoms_and_terms((root/'candidate.psf').read_text())
fitpath=(args.stage/'bonded_fit_plan.json').resolve()
fit=json.loads(fitpath.read_text())
import importlib
sys.path.insert(0,str(Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()))
d=importlib.import_module('drude_model')
lookup={d.ATOM_NAMES[int(row[5][1:])]:i-1 for i,row in atoms.items() if row[5].startswith('X')}
nuclear={i for i,row in atoms.items() if row[5].startswith('X')}
drudes=[]
bonds=[]
for a,b in sections['NBOND'][3]:
    if a in nuclear and b in nuclear:bonds.append((a-1,b-1))
    if atoms[a][5]=='DRUD' or atoms[b][5]=='DRUD':drudes.append((a-1,b-1))
assert len(drudes)==20 and len(bonds)==38
records=[]
for case in plan['cases']:
    label=case['id']
    receipt=json.loads((root/f'{label}.completion.json').read_text())
    assert receipt['plan_sha256']==source(root/'plan.json')['sha256']
    log=(root/f'{label}.log').read_text()
    assert 'End of program' in log and 'FATAL ERROR' not in log
    titles=next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
    energies=[dict(zip(titles,map(float,l.split()[1:]))) for l in log.splitlines() if l.startswith('ENERGY:')]
    assert energies[-1]['TS']==case['steps']
    tail=[r for r in energies if r['TS']*case['timestep_fs']>=2500]
    layout=read_layout(root/f'{label}.dcd')
    assert layout.n_atoms==64 and layout.n_frames>=case['steps']//20
    maxdisp=0.
    stereo_failures=[]
    ranges=[]
    for frame in range(layout.n_frames):
        x,_=read_frame(root/f'{label}.dcd',layout,frame)
        assert np.isfinite(x).all()
        maxdisp=max(maxdisp,max(float(np.linalg.norm(x[a]-x[b])) for a,b in drudes))
        ranges.append([np.linalg.norm(x[a]-x[b]) for a,b in bonds])
        for center in fit['stereochemical_impropers']:
            a,b,c,dd=x[[lookup[n] for n in center['ordered_atoms_candidate']]]
            signed=float(np.dot(b-a,np.cross(c-a,dd-a)))
            if signed*center['observed_signed_volume']<=0:
                stereo_failures.append({'frame':frame,'center':center['stereocenter']})
    ranges=np.array(ranges)
    records.append({'case':label,'duration_ps':5,'timestep_fs':case['timestep_fs'],'seed':case['seed'],'frames_audited':layout.n_frames,'maximum_drude_displacement_angstrom':maxdisp,'inside_original_drude_domain':maxdisp<=.2,'all_lesion_stereocenters_preserved':not stereo_failures,'stereochemistry_failures':stereo_failures,'minimum_nuclear_bond_angstrom':float(ranges.min()),'maximum_nuclear_bond_angstrom':float(ranges.max()),'last_half_mean_reported_warm_temperature_K':float(np.mean([r['TEMP'] for r in tail])),'last_half_mean_reported_drude_temperature_K':float(np.mean([r['DRUDEBOND'] for r in tail])),'sources':[source(p) for p in (root/f'{label}.log',root/f'{label}.dcd',root/f'{label}.completion.json')]})
write(root/'trajectory_audit.json',{'simulation_ready':False,'gate_effect':'none','scope':'Four short vacuum trajectories of the unaccepted capped candidate. Temperatures are diagnostics; no statistical timestep convergence, solvent, DNA or physical-force-field validation follows.','records':records,'sources':[source(p) for p in (root/'plan.json',fitpath,Path(__file__))]})
for r in records:print(r['case'],'maxDrude',r['maximum_drude_displacement_angstrom'],'stereo',r['all_lesion_stereocenters_preserved'],'warm',r['last_half_mean_reported_warm_temperature_K'],'cold',r['last_half_mean_reported_drude_temperature_K'])
