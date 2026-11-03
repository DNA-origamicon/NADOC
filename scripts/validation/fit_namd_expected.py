"""Offline model fit; writes candidate_model.json, never installs it automatically."""
from pathlib import Path
import sys
import json,argparse,math
import numpy as np
from scipy.optimize import nnls
parser=argparse.ArgumentParser(description='Fit descriptive NAMD memory models; cross-validate by complete geometry group.')
parser.add_argument('--root',type=Path,required=True,help='Directory containing features.json with archived measured outcomes')
parser.add_argument('--artifacts',type=Path,default=Path(__file__).resolve().parents[2]/'.development-artifacts')
args=parser.parse_args();R=args.root
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.validation.namd_estimator_audit import qualified_feature_rows
from backend.core.namd_allocation_model import QUALIFIED_ENGINE
raw=json.loads((R/'features.json').read_text());rows,excluded=qualified_feature_rows(args.artifacts,raw['rows'])
if not rows:raise ValueError('No qualified completed runs remain after evidence filtering')
for r in rows:
 opts={s[0].lower():' '.join(s[1:]) for line in Path(r['configuration']).read_text().splitlines() if len(s:=line.split())>=2}
 r['x']=r['x'][:5]+[r['x'][1] if float(opts.get('timestep',1))>=3 else 0,r['x'][1] if opts.get('constraints','off').lower() in ('on','yes','true','1') else 0,math.prod(r['features']['neighbor']['grid'])/1000]
models={};validation=[]
for mode in ['resident','offload']:
 group=[x for x in rows if x['mode']==mode];features=np.array([x['x'] for x in group]);X=features.copy();models[mode]={};errors={'ram':[],'gpu':[]}
 # Patch count improved offload holdouts but worsened resident extremes.
 if mode=='resident':X[:,-1]=0
 for resource in ['ram','gpu']:
  y=np.array([x[resource]-(x['pme'] if resource=='gpu' else 0) for x in group]);scale=np.maximum(np.max(X,axis=0),1)
  w=1/np.array([x[resource] for x in group]);models[mode][resource]=(nnls((X/scale)*w[:,None],y*w)[0]/scale).tolist()
  for held in sorted({x['group'] for x in group}):
   train=np.array([x['group']!=held for x in group]);b=nnls((X[train]/scale)*w[train,None],y[train]*w[train])[0]/scale
   for i in np.where(~train)[0]:
    pred=float(X[i]@b)+(group[i]['pme'] if resource=='gpu' else 0);actual=group[i][resource];err=100*(pred/actual-1)
    errors[resource].append(abs(err));validation.append(dict(mode=mode,resource=resource,id=group[i]['id'],held_group=held,expected=pred,actual=actual,error_pct=err))
 models[mode]['validation']={k:dict(method='leave-one-geometry-group-out',cases=len(v),median_absolute_pct=float(np.median(v)),p95_absolute_pct=float(np.percentile(v,95)),maximum_absolute_pct=max(v)) for k,v in errors.items()}
 models[mode]['training_cases']=len(group);models[mode]['feature_ranges']=[[float(features[:,i].min()),float(features[:,i].max())] for i in range(features.shape[1])]
model=dict(qualified_engine_sha256=QUALIFIED_ENGINE,qualified_drivers=['580.178.04'],qualified_threads=[16,32],fit_method='nonnegative least squares minimizing relative error; geometry groups held out together',basis='origami-20261102-qualified-success-expected-v3',estimate_kind='expected_process_peak',features=['intercept','million_atoms','million_restraints','spatial_tile_pair_capacity_mib','million_atoms_neighbor_volume_delta','four_fs_million_atoms','harmonic_constraint_million_atoms','thousand_patches'],qualified_gpu_names=['NVIDIA GeForce RTX 3080 Ti'],modes=models,confidence=None,scope='Single GPU qualified NAMD build; successful completed chains only. Expected process peaks, never an admission bound or time average. Patch count is fitted only for offload. Timestep regime is an empirical profile effect; causal allocation attribution remains incomplete.')
(R/'candidate_model.json').write_text(json.dumps(model,indent=2)+'\n');(R/'cross_validation.json').write_text(json.dumps(validation,indent=2)+'\n');(R/'qualified_features.json').write_text(json.dumps(dict(rows=rows,excluded=excluded),indent=2)+'\n')
for k,v in models.items():print(k,v['validation'],v['gpu'])
