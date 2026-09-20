"""Audit refined capped minimum and export an isolated nucleotide candidate."""
import json
from pathlib import Path
import sys
import shutil
import warnings
import numpy as np
import openmm as mm
from openmm import app,unit as u
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import FF,source,write
from experiments.cpd_published_comparator.local_benchmarks import REF,checked,volume

root=Path('.development-artifacts/cpd-angle-refinement-v2').resolve()
out=Path('.development-artifacts/cpd-angle-native-v1').resolve();out.mkdir(exist_ok=True); assert not (out/"export_assessment.json").exists()
old=Path('.development-artifacts/cpd-published-comparator-v1').resolve()
fit=json.loads((root/'assessment.json').read_text())
s=mm.XmlSerializer.deserialize((root/'candidate.xml').read_text());x=np.loadtxt(root/'minimum_A.txt')
it=mm.VerletIntegrator(.001);ctx=mm.Context(s,it,mm.Platform.getPlatformByName('Reference'))
def grad(pos):
 ctx.setPositions(pos*u.angstrom)
 return -np.asarray(ctx.getState(getForces=True).getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()
h=np.empty((108,108));step=1e-4
for i in range(108):
 a=x.ravel().copy();b=a.copy();a[i]+=step;b[i]-=step;h[:,i]=(grad(a.reshape(36,3))-grad(b.reshape(36,3)))/(2*step)
c=x-x.mean(axis=0);rigid=np.column_stack([np.tile(v,(36,1)).ravel() for v in np.eye(3)]+[np.cross(np.tile(v,(36,1)),c).ravel() for v in np.eye(3)]);basis=np.linalg.svd(rigid,full_matrices=True)[0][:,6:];minimum=float(np.linalg.eigvalsh(basis.T@((h+h.T)/2)@basis).min())
m=json.loads((REF/'minimum_response_fixed_improper_v1/linear_response_manifest.json').read_text());names=[a['stable_atom_key'] for a in json.loads(checked(m['sources']['stable_atom_map']).read_text())];idx={n:i for i,n in enumerate(names)}
xyz=np.array([list(map(float,l.split()[1:])) for l in checked(m['sources']['target_geometry']).read_text().splitlines()[2:] if l.strip()])
centers=[]
for r in [1,2]:
 for center,order in [('C5',[f'{r}:C4',f'{r}:C6',f'{r}:C7',f'{3-r}:C5']),('C6',[f'{r}:N1',f'{r}:C5',f'{r}:H6',f'{3-r}:C6'])]:
  ids=[idx[n] for n in order];v0=volume(xyz,ids);v1=volume(x,ids);centers.append(dict(center=f'{r}:{center}',reference=v0,candidate=v1,preserved=v0*v1>0))
assert minimum>0 and all(c['preserved'] for c in centers)
assert fit['max_angle_error_deg']<=3 and fit['max_bond_error_A']<=.03
with warnings.catch_warnings():
 warnings.simplefilter('ignore');pars=app.CharmmParameterSet(str(FF/'top_all36_cgenff.rtf'),str(FF/'par_all36_cgenff.prm'),str(old/'comparator_last.prm'))
prm=(old/'comparator_last.prm').read_text().rsplit('END',1)[0]+'\nANGLES\n'
for row in fit['angle_changes']:
 key=tuple(row['types']);a=pars.angle_types[key];line=' '.join(key)+f' {a.k:.12g} {a.theteq+row["delta_deg"]:.12g}'
 ub=pars.urey_bradley_types.get(key)
 if ub is not None and ub.k not in (None,0):line+=f' {ub.k:.12g} {ub.req:.12g}'
 prm+=line+'\n'
(out/'comparator_last.prm').write_text(prm+'END\n')
rtf=(old/'comparator.rtf').read_text().rsplit('END',1)[0]
for r in [1,2]:rtf+=f'DELETE IMPR {r}C5 {r}C4 {r}C6 {r}C5M\n'
(out/'comparator.rtf').write_text(rtf+'END\n');shutil.copyfile(old/'1N4E.pdb',out/'1N4E.pdb')
write(out/'export_assessment.json',{'status':'training_geometry_and_minimum_passed','simulation_ready':False,'minimum_internal_curvature':minimum,'centers':centers,'angle_max_deg':fit['max_angle_error_deg'],'bond_max_A':fit['max_bond_error_A'],'sources':[source(root/'candidate.xml'),source(root/'assessment.json'),source(Path(__file__))]})
print('positive minimum curvature',minimum,'stereocenters',centers)
