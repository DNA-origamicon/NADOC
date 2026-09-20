"""Relate observed C2 polarization excursions to nuclear geometry, without fitting."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,write,checked
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from backend.core.dcd_fast import read_layout,read_frame
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral

root=Path('.development-artifacts/cpd-thermal-geometry-diagnostic-v1').resolve()
root.mkdir(exist_ok=False)
campaign=Path('.development-artifacts/cpd-capped-dynamics-v1').resolve()
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
sys.path.insert(0,str(recovery));import drude_model as d
_,atoms,sections=atoms_and_terms((campaign/'candidate.psf').read_text())
serials={int(row[5][1:]):i-1 for i,row in atoms.items() if row[5].startswith('X')}
lookup={n:i for i,n in enumerate(d.ATOM_NAMES)}
parent=serials[lookup['2:C2']]
drude=next(b-1 if a-1==parent else a-1 for a,b in sections['NBOND'][3] if (a-1==parent and atoms[b][5]=='DRUD') or (b-1==parent and atoms[a][5]=='DRUD'))
manifest_path=Path('.development-artifacts/cpd-drude-bonded-h6-endpoints-v1/responses/minimum/linear_response_manifest.json').resolve()
m=json.loads(manifest_path.read_text())
reference_path=checked(m['sources']['target_geometry'])
reference=np.array([a[1:] for a in parse_xyz(reference_path.read_text())[0]])
features=[('distance',['2:C2','2:O2']),('distance',['2:C2','2:N1']),('distance',['2:C2','2:N3']),('distance',['2:N1','2:CM']),('angle',['2:N1','2:C2','2:N3']),('angle',['2:N1','2:C2','2:O2']),('angle',['2:N3','2:C2','2:O2']),('improper',['2:C2','2:N1','2:N3','2:O2']),('improper',['2:N1','2:C6','2:C2','2:CM'])]
def measure(x,kind,names):
    p=x[[lookup[n] for n in names]]
    if kind=='distance':return float(np.linalg.norm(p[0]-p[1]))
    if kind=='improper':return float(_dihedral(*p))
    a,b=p[0]-p[1],p[2]-p[1]
    return float(np.degrees(np.arccos(np.clip(a@b/np.linalg.norm(a)/np.linalg.norm(b),-1,1))))
ref=np.array([measure(reference,k,n) for k,n in features])
records=[]
for case in json.loads((campaign/'plan.json').read_text())['cases']:
    path=campaign/(case['id']+'.dcd');layout=read_layout(path)
    values=[];displacements=[]
    for i in range(layout.n_frames):
        x,_=read_frame(path,layout,i)
        displacements.append(float(np.linalg.norm(x[parent]-x[drude])))
        nuclear=x[[serials[j] for j in range(36)]].astype(float)
        values.append([measure(nuclear,k,n) for k,n in features])
    values=np.array(values);displacements=np.array(displacements)
    worst=int(np.argmax(displacements))
    rows=[]
    for j,(kind,names) in enumerate(features):
        col=values[:,j]
        if kind=='improper':col=ref[j]+(col-ref[j]+180)%360-180
        rows.append({'kind':kind,'atoms':names,'units':'angstrom' if kind=='distance' else 'degrees','qm_reference':float(ref[j]),'trajectory_mean':float(col.mean()),'trajectory_std':float(col.std()),'at_maximum_c2_displacement':float(col[worst]),'pearson_correlation_with_c2_displacement':float(np.corrcoef(col,displacements)[0,1])})
    records.append({'case':case['id'],'features':rows,'source':source(path)})
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Descriptive correlations in four short unaccepted-model trajectories, not causal evidence or a fit objective. Periodic improper angles unwrapped about QM reference.','records':records,'sources':[source(p) for p in (manifest_path,reference_path,campaign/'candidate.psf',Path(__file__))]})
for r in records:
    print(r['case'])
    for f in sorted(r['features'],key=lambda r:abs(r['pearson_correlation_with_c2_displacement']),reverse=True)[:3]:print(f)
