"""Further documented-loop and unoccupied-scaffold guided annotation tests."""
from pathlib import Path
base=Path(__file__).with_name('search.py');exec(compile(base.read_text().split('# Baseline archived')[0],str(base),'exec'))
results=json.loads((O/'search_results.json').read_text());best=json.loads((O/'best.json').read_text());cache={(r['key'],r['annotation_sha256']):r for r in results};pools=json.loads((O/'candidate_pools.json').read_text())
for seven,cost5,cost7 in [(1,-3,-3),(1,-6,-6),(1,-9,-9),(2,-6,-6)]:
 model=f'loop57_seven{seven}_cost{cost5}'
 code=PREFIX.replace(' + prior - 1',f' + {seven}*prior - 1').replace('.4*long - .45*(length-long)','.8*long - 2*(length-long)').replace('low_complexity_penalty=6','low_complexity_penalty=20').replace('(5,.8)',f'(5,{cost5})').replace('(7,2.0)',f'(7,{cost7})')
 env={'__file__':str(SOURCE)};exec(compile(code,str(SOURCE),'exec'),env)
 key='42hb14';annotations=[]
 for i,r in enumerate(refs[key]):
  a=env['annotate'](r['original_sequence'],key);annotations.append(a['proposed'])
  for v in [a['proposed']]+a['alternatives']:record_candidate(key,i,v,model)
 run(key,model,annotations,{'seven_prior_multiplier':seven,'fiveTcost':cost5,'sevenTcost':cost7,'long_match_reward':.8,'unmatched_penalty':2})
(O/'candidate_pools.json').write_text(json.dumps(pools,indent=2)+'\n')
def free_score(a,occupied):
 blocks=[s for s in a['segments'] if s['kind']=='paired_candidate'];total=sum(s['length'] for s in blocks);free=0;whole=0
 for s in blocks:
  n=s['length'];fraction=max((sum((p-k)%N not in occupied for k in range(n))/n for p in s['first_scaffold_indices_0based']),default=0)
  free+=fraction*n;whole+=fraction==1
 return (whole/len(blocks),free/total,-sum(s['length']<6 for s in blocks),sum(s['length']%7==0 for s in blocks)/len(blocks))
for round_index in range(2):
 improved=False
 for key in refs:
  initial=metric(best[key]);current=json.loads((R/best[key]['path']/'annotations.json').read_text());st,sc,_=json.loads((R/best[key]['path']/'solver/contactmap.json').read_text());occupied={int(p) for p,b in sc.items() if b['staple_id']>=0}
  choices=[]
  for i in range(len(refs[key])):
   if i in best[key]['placed_indices']:continue
   opts=[v['annotation'] for t,v in pools[key][i].items() if t!=current[i]['annotated_sequence']]
   opts.sort(key=lambda a:free_score(a,occupied),reverse=True)
   if not opts:continue
   a=opts[min(round_index,len(opts)-1)];score=free_score(a,occupied)
   if score>=free_score(current[i],occupied):choices.append((score,i,a))
  choices.sort(reverse=True,key=lambda x:x[0]);print('FREE CANDIDATES',key,round_index,len(choices),flush=True)
  # Test the most promising local changes individually; remaining choices in batches.
  for j,(score,i,a) in enumerate(choices[:16]):
   if i in best[key]['placed_indices']:continue
   current=json.loads((R/best[key]['path']/'annotations.json').read_text());current[i]=a
   run(key,f'free_r{round_index}_single{j}',current,{'free_occupancy_guided':True,'changed_published_id':refs[key][i]['published_id'],'rank':round_index,'local_score':score})
  for group in range(3):
   current=json.loads((R/best[key]['path']/'annotations.json').read_text());changed=[]
   for score,i,a in choices[16+group::3]:
    if i not in best[key]['placed_indices']:current[i]=a;changed.append(refs[key][i]['published_id'])
   if changed:run(key,f'free_r{round_index}_batch{group}',current,{'free_occupancy_guided':True,'changed_published_ids':changed})
  improved|=metric(best[key])>initial
 print('FREE ROUND',round_index,'improved',improved,flush=True)
 if not improved:break
print('OCCUPANCY REFINEMENT COMPLETE',flush=True)
