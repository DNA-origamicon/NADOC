"""Reproducible annotation search; preserve all published sequences and p7560."""
import csv,hashlib,itertools,json,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
S=(R/'backend/core/p7560.txt').read_text().strip();C=S.translate(str.maketrans('ACGT','TGCA'));N=len(S)
SOURCE=R/'analysis/gerling2018_T_annotations_20261027/annotate.py'
PREFIX=SOURCE.read_text().split('\nwb=openpyxl.Workbook()')[0]
original=json.loads((SOURCE.parent/'annotations.json').read_text());refs={k:[r for r in original if r['key']==k] for k in ['42hb13','42hb14']}
results=[];cache={};pools={k:[{} for r in refs[k]] for k in refs};best={}
def save():
 (O/'search_results.json').write_text(json.dumps(results,indent=2)+'\n')
 (O/'best.json').write_text(json.dumps(best,indent=2)+'\n')
def metric(m):return (m['placed'],m['covered'],-max(0,m['candidate_paired_nt']-N))
def record_candidate(key,i,a,model):
 text=a['annotated_sequence'];entry=pools[key][i].setdefault(text,{'annotation':a,'models':[]});entry['models'].append(model)
def run(key,label,annotations,parameters):
 lines=[a['annotated_sequence'] for a in annotations]
 assert len(lines)==len(refs[key])
 for line,row in zip(lines,refs[key]):assert line.replace('*','')==row['original_sequence']
 digest=hashlib.sha256('\n'.join(lines).encode()).hexdigest()
 if (key,digest) in cache:return cache[key,digest]
 dest=O/key/label;dest.mkdir(parents=True,exist_ok=True)
 inp=dest/'input.rev';inp.write_text('# Exploratory annotations; full published sequences retained\nCIRCULAR\n'+S+'\n'+'\n'.join(lines)+'\n')
 (dest/'annotations.json').write_text(json.dumps(annotations,indent=2)+'\n')
 with (dest/'solver.log').open('w') as f:
  command=[str(R/'.venv/bin/python'),str(globals().get('RUNNER_PATH',R/'tools/revnano_accel/run.py')),str(inp),'--output',str(dest/'solver')]
  for name,value in globals().get('RESOURCE_OPTIONS',{'workers':4}).items():command.extend(['--'+name.replace('_','-'),str(value)])
  for name in ['mu_min','sigma','beta','seven_route_bonus']:
   if name in parameters:command.extend(['--'+name.replace('_','-'),str(parameters[name])])
  if parameters.get('ordered_pruning'):command.append('--ordered-pruning')
  proc=subprocess.run(command,cwd=R,stdout=f,stderr=subprocess.STDOUT)
 summ=json.loads((dest/'solver/summary.json').read_text());placed=[];covered=0
 for name,field,default in [('mu_min','MU_MIN',6),('sigma','SIGMA',4),('beta','BETA',.3),('seven_route_bonus','seven_route_bonus',0)]:
  assert summ['scientific_parameters'].get(field,default)==parameters.get(name,default),(label,'parameter mismatch',name)
 assert summ.get('ordered_pruning',{}).get('enabled',False)==bool(parameters.get('ordered_pruning',False))
 if proc.returncode not in [0,2]:raise RuntimeError((label,proc.returncode,summ))
 if (dest/'solver/contactmap.json').exists():
  st,sc,circ=json.loads((dest/'solver/contactmap.json').read_text());occupied=set()
  assert circ and len(sc)==N
  for sid,m in st.items():
   i=int(sid);placed.append(i);assert m['sequence53']==refs[key][i]['original_sequence']
   expected={p for a in annotations[i]['segments'] if a['kind']=='unpaired_T_candidate' for p in range(a['start_1based']-1,a['end_1based'])}
   assert {p for p,b in enumerate(m['base_i53']) if b<0}==expected
   for p,b in enumerate(m['base_i53']):
    if b<0:continue
    assert b not in occupied and m['sequence53'][p]==C[b];occupied.add(b)
  covered=len(occupied)
 candidate_paired=sum(s['length'] for a in annotations for s in a['segments'] if s['kind']=='paired_candidate')
 blocks=[s for a in annotations for s in a['segments'] if s['kind']=='paired_candidate']
 result={'key':key,'label':label,'path':str(dest.relative_to(R)),'parameters':parameters,'annotation_sha256':digest,'placed':len(placed),'covered':covered,'placed_indices':sorted(placed),'candidate_paired_nt':candidate_paired,'multiple7_blocks':sum(s['length']%7==0 for s in blocks),'paired_blocks':len(blocks),'seconds':summ['solver_seconds'],'solver_error':summ.get('solver_error'),'execution_error':summ.get('execution_error'),'changed_staples':sum(a['annotated_sequence']!=r['proposed']['annotated_sequence'] for a,r in zip(annotations,refs[key]))}
 results.append(result);cache[key,digest]=result
 if key not in best or metric(result)>metric(best[key]):best[key]=result
 save();print(key,label,'placed',len(placed),'covered',covered,'candidate',candidate_paired,'BEST',best[key]['label'],flush=True)
 return result
# Baseline archived output reused, then independently re-audited by search runs.
for key in refs:
 for i,r in enumerate(refs[key]):
  for a in [r['proposed']]+r['alternatives']:record_candidate(key,i,a,'approved')
 run(key,'approved',[r['proposed'] for r in refs[key]],{'baseline':True})
for seven,protect in itertools.product([1,2,4],[1,3,8]):
 model=f'seven{seven}_protect{protect}'
 code=PREFIX.replace(' + prior - 1',' + '+str(seven)+'*prior - 1').replace('-len(protected.intersection(range(j,j+g)))','-'+str(protect)+'*len(protected.intersection(range(j,j+g)))')
 env={'__file__':str(SOURCE)};exec(compile(code,str(SOURCE),'exec'),env)
 for key in refs:
  annotations=[]
  for i,r in enumerate(refs[key]):
   a=env['annotate'](r['original_sequence'],key);annotations.append(a['proposed'])
   for v in [a['proposed']]+a['alternatives']:record_candidate(key,i,v,model)
  run(key,model,annotations,{'seven_prior_multiplier':seven,'unique_anchor_protection':protect})
# Additional 5T loop preference in the design whose caption explicitly includes them.
for loopcost in [-2,-5]:
 model=f'fiveTcost{loopcost}'
 code=PREFIX.replace(' + prior - 1',' + 2*prior - 1').replace('-len(protected.intersection(range(j,j+g)))','-3*len(protected.intersection(range(j,j+g)))').replace('(5,.8)',f'(5,{loopcost})')
 env={'__file__':str(SOURCE)};exec(compile(code,str(SOURCE),'exec'),env)
 key='42hb14';annotations=[]
 for i,r in enumerate(refs[key]):
  a=env['annotate'](r['original_sequence'],key);annotations.append(a['proposed'])
  for v in [a['proposed']]+a['alternatives']:record_candidate(key,i,v,model)
 run(key,model,annotations,{'seven_prior_multiplier':2,'unique_anchor_protection':3,'fiveTcost':loopcost})
(O/'candidate_pools.json').write_text(json.dumps(pools,indent=2)+'\n')
print('GRID COMPLETE',flush=True)
