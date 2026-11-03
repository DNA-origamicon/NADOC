"""Minimally adjust unplaced annotations of a stronger partial map to fit p7560."""
from pathlib import Path
base=Path(__file__).with_name('search.py');exec(compile(base.read_text().split('# Baseline archived')[0],str(base),'exec'))
ROOTSEARCH=O;seed=json.loads((O/'best.json').read_text())['42hb14'];base_rows=json.loads((R/seed['path']/'annotations.json').read_text());pool=json.loads((O/'expanded_candidate_pools.json').read_text())['42hb14'];oldbest=json.loads((O/'capacity_branch_corrected/best.json').read_text())['42hb14']
O=ROOTSEARCH/'capacity_repair';O.mkdir(exist_ok=True);results=[];best={'42hb14':oldbest};cache={};RESOURCE_OPTIONS={'workers':2,'parent_mib':512,'worker_mib':256,'budget_mib':1024}
def metric(m):return (m['candidate_paired_nt']<=N,m['placed'],m['covered'])
st,sc,_=json.loads((R/seed['path']/'solver/contactmap.json').read_text());occupied={int(p) for p,b in sc.items() if b['staple_id']>=0}
def info(a):
 b=[s for s in a['segments'] if s['kind']=='paired_candidate'];n=sum(s['length'] for s in b)
 support=sum(s['longest_exact_substring_nt'] for s in b)/n
 free=sum(s['length']*max((sum((p-k)%N not in occupied for k in range(s['length']))/s['length'] for p in s['first_scaffold_indices_0based']),default=0) for s in b)/n
 return n,support,all(s['full_scaffold_hit_count'] and s['length']>=6 for s in b),free,sum(s['length']%7==0 for s in b)/len(b)
for criterion in ['full_match','nonworsening_support']:
 for ranking in ['few_changes','free_scaffold']:
  choices=[]
  for i,a in enumerate(base_rows):
   if i in seed['placed_indices']:continue
   old=info(a);options=[v['annotation'] for v in pool[i].values() if info(v['annotation'])[0]<old[0] and (info(v['annotation'])[2] if criterion=='full_match' else info(v['annotation'])[1]>=old[1])]
   if options:
    candidate=min(options,key=lambda v:(info(v)[0],-info(v)[1]));v=info(candidate);choices.append((old[0]-v[0],v[3],v[4],i,candidate))
  choices.sort(key=(lambda c:(c[0],c[1],c[2])) if ranking=='few_changes' else (lambda c:(c[1],c[2],c[0])),reverse=True)
  current=list(base_rows);total=seed['candidate_paired_nt'];changed=[]
  for reduction,free,seven,i,a in choices:
   if total<=N:break
   current[i]=a;total-=reduction;changed.append(refs['42hb14'][i]['published_id'])
  if total>N:print('INSUFFICIENT supported reductions',criterion,ranking,total,flush=True);continue
  p=seed['parameters'];run('42hb14',criterion+'_'+ranking,current,{'mu_min':p.get('mu_min',6),'sigma':p.get('sigma',4),'beta':p.get('beta',.3),'seven_route_bonus':p.get('seven_route_bonus',0),'ordered_pruning':True,'changed_published_ids':changed,'seed_path':seed['path'],'capacity_repair':True})
print('CAPACITY REPAIR COMPLETE',flush=True)
