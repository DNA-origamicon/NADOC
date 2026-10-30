"""Continue saved search with sequence-weighted and solver-guided variations."""
from pathlib import Path
base=Path(__file__).with_name('search.py')
exec(compile(base.read_text().split('# Baseline archived')[0],str(base),'exec'))
results=json.loads((O/'search_results.json').read_text());best=json.loads((O/'best.json').read_text());cache={(r['key'],r['annotation_sha256']):r for r in results};pools=json.loads((O/'candidate_pools.json').read_text())
# Strengthen exact-match support without forcing every block to a multiple of7.
for seven,protect in [(0.5,0.3),(1,0.3),(2,0.3),(1,1),(2,1),(1,3)]:
 model=f'exact_seven{seven}_protect{protect}'
 code=PREFIX.replace(' + prior - 1',' + '+str(seven)+'*prior - 1').replace('-len(protected.intersection(range(j,j+g)))','-'+str(protect)+'*len(protected.intersection(range(j,j+g)))').replace('.4*long - .45*(length-long)','.8*long - 2*(length-long)').replace('low_complexity_penalty=6','low_complexity_penalty=20')
 env={'__file__':str(SOURCE)};exec(compile(code,str(SOURCE),'exec'),env)
 for key in refs:
  annotations=[]
  for i,r in enumerate(refs[key]):
   a=env['annotate'](r['original_sequence'],key);annotations.append(a['proposed'])
   for v in [a['proposed']]+a['alternatives']:record_candidate(key,i,v,model)
  run(key,model,annotations,{'seven_prior_multiplier':seven,'unique_anchor_protection':protect,'long_match_reward':.8,'unmatched_penalty':2,'all_T_paired_penalty':20})
(O/'candidate_pools.json').write_text(json.dumps(pools,indent=2)+'\n')
def candidate_quality(entry):
 a=entry['annotation'];p=[s for s in a['segments'] if s['kind']=='paired_candidate'];total=sum(s['length'] for s in p)
 return (sum(s['length'] for s in p if s['full_scaffold_hit_count']>0)/total - .2*sum(s['length']<6 for s in p) - .5*sum(set(s['sequence'])=={'T'} for s in p),sum(s['length']%7==0 for s in p)/len(p),len(entry['models']))
# Candidate pools are local sequence-supported proposals, not arbitrary base edits.
# Try bounded batches of changes only on unplaced physical staples; accept only
# improvements in complete-staple count, then paired coverage. Global solver may
# reroute even unchanged placed oligos; final maps are independently audited.
for round_index in range(3):
 improved=False
 for key in refs:
  previous=metric(best[key]);missing=[i for i in range(len(refs[key])) if i not in best[key]['placed_indices']]
  # Six groups avoids one large perturbation obscuring useful local changes.
  for group in range(6):
   current=json.loads((R/best[key]['path']/'annotations.json').read_text());changes=[]
   for i in missing[group::6]:
    if i in best[key]['placed_indices']:continue
    options=[e for text,e in pools[key][i].items() if text!=current[i]['annotated_sequence']]
    options.sort(key=candidate_quality,reverse=True)
    if not options:continue
    option=options[min(round_index,len(options)-1)]['annotation'];current[i]=option;changes.append(refs[key][i]['published_id'])
   if changes:run(key,f'guided_r{round_index}_g{group}',current,{'guided_round':round_index,'changed_published_ids':changes,'candidate_rank':round_index})
  improved|=metric(best[key])>previous
 print('GUIDED ROUND',round_index,'improved',improved,flush=True)
 if not improved and round_index>=1:break
print('REFINEMENT COMPLETE',flush=True)
