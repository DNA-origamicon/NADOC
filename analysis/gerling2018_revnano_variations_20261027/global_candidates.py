"""Choose mutually compatible exact-domain annotations, then rerun full REVNANO."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
base=Path(__file__).with_name('search.py');exec(compile(base.read_text().split('# Baseline archived')[0],str(base),'exec'))
import resource
resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_array
results=json.loads((O/'search_results.json').read_text());best=json.loads((O/'best.json').read_text());cache={(r['key'],r['annotation_sha256']):r for r in results};pools=json.loads((O/'candidate_pools.json').read_text())
reports=[]
for key in refs:
 for seven_weight in [0.02,0.2]:
  variables=[];coeff=[];row_indices=[];col_indices=[];values=[];lb=[0.]*(len(refs[key])+N);ub=[1.]*(len(refs[key])+N);variant_info=[]
  def var(kind,info,cost):
   index=len(variables);variables.append((kind,info));coeff.append(cost);return index
  def add(row,col,value):row_indices.append(row);col_indices.append(col);values.append(value)
  for i,pool in enumerate(pools[key]):
   for e in pool.values():
    a=e['annotation'];blocks=[s for s in a['segments'] if s['kind']=='paired_candidate']
    if not all(s['full_scaffold_hit_count'] and s['length']>=6 and set(s['sequence'])!={'T'} for s in blocks):continue
    x=var('annotation',(i,a),-1000-.01*sum(s['length'] for s in blocks)-seven_weight*sum(s['length']%7==0 for s in blocks));variant_info.append(x);add(i,x,1)
    for block in blocks:
     row=len(lb);lb.append(0.);ub.append(0.);add(row,x,-1)
     for p in block['first_scaffold_indices_0based']:
      y=var('placement',(i,block,p),0);add(row,y,1)
      for k in range(block['length']):add(len(refs[key])+(p-k)%N,y,1)
  A=coo_array((np.array(values),(np.array(row_indices,dtype=np.int32),np.array(col_indices,dtype=np.int32))),shape=(len(lb),len(variables))).tocsc()
  # HiGHS accepts the forwarded thread option even though scipy labels it extra.
  answer=milp(np.array(coeff),integrality=np.ones(len(coeff),dtype=np.int32),bounds=Bounds(0,1),constraints=LinearConstraint(A,lb,ub),options={'time_limit':60,'mip_rel_gap':0.001,'threads':4})
  label=f'global_exact_seven{seven_weight}';report={'key':key,'label':label,'status':int(answer.status),'message':answer.message,'variables':len(variables),'constraints':len(lb),'selected_staples':0,'selected_paired_nt':0,'mip_gap':getattr(answer,'mip_gap',None)}
  if answer.x is not None:
   selected={};occupied=set();chosen_placements=[]
   for index,(kind,info) in enumerate(variables):
    if answer.x[index]<.5:continue
    if kind=='annotation':i,a=info;assert i not in selected;selected[i]=a
    else:
     i,block,p=info
     assert block['sequence']==''.join(C[(p-k)%N] for k in range(block['length']))
     chosen_placements.append({'published_id':refs[key][i]['published_id'],'staple_start_1based':block['start_1based'],'length':block['length'],'sequence':block['sequence'],'first_scaffold_index_0based':p})
     for k in range(block['length']):
      b=(p-k)%N;assert b not in occupied;occupied.add(b)
   (O/f'{key}_{label}_placements.json').write_text(json.dumps(chosen_placements,indent=2)+'\n')
   (O/f'{key}_{label}_selected.json').write_text(json.dumps(selected,indent=2)+'\n')
   report['selected_staples']=len(selected);report['selected_paired_nt']=len(occupied);report['selected_published_ids']=[refs[key][i]['published_id'] for i in selected]

  reports.append(report);(O/'global_assignment_reports.json').write_text(json.dumps(reports,indent=2)+'\n');print('GLOBAL',report,flush=True)
print('GLOBAL CANDIDATES COMPLETE',flush=True)
