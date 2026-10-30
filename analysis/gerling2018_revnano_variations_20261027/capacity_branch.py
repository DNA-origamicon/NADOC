"""Reapply expanded annotation alternatives under improved solver settings."""
from pathlib import Path
src=Path(__file__).with_name('solver_sensitivity.py').read_text().split('for key in refs:\n before=')[0]
src=src.replace("'--mu-min',str(parameters['mu_min'])", "'--ordered-pruning','--seven-route-bonus',str(parameters.get('seven_route_bonus',0)),'--mu-min',str(parameters['mu_min'])")
# Unlike settings experiments, deduplicate identical annotations AND settings.
src=src.replace('if False:return None',"if (key,digest,parameters.get('mu_min'),parameters.get('sigma'),parameters.get('beta'),parameters.get('seven_route_bonus',0)) in tested:return tested[(key,digest,parameters.get('mu_min'),parameters.get('sigma'),parameters.get('beta'),parameters.get('seven_route_bonus',0))]")
src=src.replace("str(O/'solver_options/run.py')","str(RUNNER)").replace("'--workers','4'","'--workers','2','--parent-mib','512','--worker-mib','256','--budget-mib','1024'")
exec(compile(src,str(Path(__file__).with_name('solver_sensitivity.py')),'exec'))
ROOTSEARCH=O;RUNNER=ROOTSEARCH/'solver_options/run.py'
feasible=max((r for r in results if r['key']=='42hb14' and r['candidate_paired_nt']<=N),key=lambda r:(r['placed'],r['covered']))
O=ROOTSEARCH/'capacity_branch';O.mkdir(exist_ok=True)
results=[];best={'42hb14':feasible};refs={'42hb14':refs['42hb14']};cache={}
def metric(m):return (m['candidate_paired_nt']<=N,m['placed'],m['covered'])
pools=json.loads((ROOTSEARCH/'expanded_candidate_pools.json').read_text())
tested={(r['key'],r['annotation_sha256'],r['parameters'].get('mu_min',6),r['parameters'].get('sigma',4),r['parameters'].get('beta',.3),r['parameters'].get('seven_route_bonus',0)):r for r in results}
def score(a,occupied):
 blocks=[s for s in a['segments'] if s['kind']=='paired_candidate'];total=sum(s['length'] for s in blocks);free=0;whole=0
 for s in blocks:
  n=s['length'];f=max((sum((p-k)%N not in occupied for k in range(n))/n for p in s['first_scaffold_indices_0based']),default=0);free+=f*n;whole+=f==1
 return (whole/len(blocks),free/total,-sum(s['length']<4 or set(s['sequence'])=={'T'} for s in blocks),sum(s['length']%7==0 for s in blocks)/len(blocks))
stalled=0
for round_index in range(6):
 any_improved=False
 for key in refs:
  before=metric(best[key])
  for group in range(6):
   current=json.loads((R/best[key]['path']/'annotations.json').read_text());st,sc,_=json.loads((R/best[key]['path']/'solver/contactmap.json').read_text());occupied={int(p) for p,b in sc.items() if b['staple_id']>=0};missing=[i for i in range(len(refs[key])) if i not in best[key]['placed_indices']];changes=[]
   for i in missing[group::6]:
    options=[v['annotation'] for t,v in pools[key][i].items() if t!=current[i]['annotated_sequence']];options.sort(key=lambda a:score(a,occupied),reverse=True)
    if not options:continue
    choice=options[min(round_index,len(options)-1)]
    if score(choice,occupied)>=score(current[i],occupied):current[i]=choice;changes.append(refs[key][i]['published_id'])
   if not changes or sum(s['length'] for a in current for s in a['segments'] if s['kind']=='paired_candidate')>N:continue
   p=best[key]['parameters'];params={'mu_min':p.get('mu_min',6),'sigma':p.get('sigma',4),'beta':p.get('beta',.3),'seven_route_bonus':p.get('seven_route_bonus',0),'ordered_pruning':True,'changed_published_ids':changes,'pool':'expanded','round':round_index}
   r=run(key,f'final_r{round_index}_g{group}',current,params);tested[(key,r['annotation_sha256'],params['mu_min'],params['sigma'],params['beta'],params['seven_route_bonus'])]=r
  any_improved|=metric(best[key])>before
 stalled=0 if any_improved else stalled+1
 print('FINAL ROUND',round_index,'improved',any_improved,'consecutive stalled',stalled,flush=True)
 if stalled>=2:break
print('FINAL REFINEMENT COMPLETE',flush=True)
