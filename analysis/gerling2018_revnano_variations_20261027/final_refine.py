"""Reapply expanded annotation alternatives under improved solver settings."""
from pathlib import Path
src=Path(__file__).with_name('solver_sensitivity.py').read_text().split('for key in refs:\n before=')[0]
src=src.replace("'--mu-min',str(parameters['mu_min'])", "'--ordered-pruning','--seven-route-bonus',str(parameters.get('seven_route_bonus',0)),'--mu-min',str(parameters['mu_min'])")
# Unlike settings experiments, deduplicate identical annotations AND settings.
src=src.replace('if False:return None',"if (key,digest,parameters.get('mu_min'),parameters.get('sigma'),parameters.get('beta'),parameters.get('seven_route_bonus',0)) in tested:return tested[(key,digest,parameters.get('mu_min'),parameters.get('sigma'),parameters.get('beta'),parameters.get('seven_route_bonus',0))]")
exec(compile(src,str(Path(__file__).with_name('solver_sensitivity.py')),'exec'))
pools=json.loads((O/'expanded_candidate_pools.json').read_text())
tested={(r['key'],r['annotation_sha256'],r['parameters'].get('mu_min',6),r['parameters'].get('sigma',4),r['parameters'].get('beta',.3),r['parameters'].get('seven_route_bonus',0)):r for r in results}
def score(a,occupied):
 blocks=[s for s in a['segments'] if s['kind']=='paired_candidate'];total=sum(s['length'] for s in blocks);free=0;whole=0
 for s in blocks:
  n=s['length'];f=max((sum((p-k)%N not in occupied for k in range(n))/n for p in s['first_scaffold_indices_0based']),default=0);free+=f*n;whole+=f==1
 return (whole/len(blocks),free/total,-sum(s['length']<4 or set(s['sequence'])=={'T'} for s in blocks),sum(s['length']%7==0 for s in blocks)/len(blocks))
# Prefer a scaffold-capacity-consistent tie without sacrificing placed staples.
for criterion in ['full_match','nonworsening_support']:
 key='42hb14';current=json.loads((R/best[key]['path']/'annotations.json').read_text());changed=[]
 def info(a):
  blocks=[s for s in a['segments'] if s['kind']=='paired_candidate'];n=sum(s['length'] for s in blocks)
  return n,sum(s['longest_exact_substring_nt'] for s in blocks)/n,all(s['full_scaffold_hit_count'] and s['length']>=6 for s in blocks)
 for i in range(len(current)):
  if i in best[key]['placed_indices']:continue
  old=info(current[i]);options=[v['annotation'] for v in pools[key][i].values() if info(v['annotation'])[0]<old[0] and (info(v['annotation'])[2] if criterion=='full_match' else info(v['annotation'])[1]>=old[1])]
  if options:current[i]=min(options,key=lambda a:(info(a)[0],-info(a)[1]));changed.append(refs[key][i]['published_id'])
 p=best[key]['parameters'];params={'mu_min':p.get('mu_min',6),'sigma':p.get('sigma',4),'beta':p.get('beta',.3),'seven_route_bonus':p.get('seven_route_bonus',0),'ordered_pruning':True,'changed_published_ids':changed,'capacity_variant':criterion}
 if changed:run(key,'capacity_'+criterion,current,params)
stalled=0
for round_index in range(12):
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
   if not changes:continue
   p=best[key]['parameters'];params={'mu_min':p.get('mu_min',6),'sigma':p.get('sigma',4),'beta':p.get('beta',.3),'seven_route_bonus':p.get('seven_route_bonus',0),'ordered_pruning':True,'changed_published_ids':changes,'pool':'expanded','round':round_index}
   r=run(key,f'final_r{round_index}_g{group}',current,params);tested[(key,r['annotation_sha256'],params['mu_min'],params['sigma'],params['beta'],params['seven_route_bonus'])]=r
  any_improved|=metric(best[key])>before
 stalled=0 if any_improved else stalled+1
 print('FINAL ROUND',round_index,'improved',any_improved,'consecutive stalled',stalled,flush=True)
 if stalled>=2:break
print('FINAL REFINEMENT COMPLETE',flush=True)
