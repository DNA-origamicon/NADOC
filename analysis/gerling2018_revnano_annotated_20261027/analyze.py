"""Audit completed maps without changing annotations or invoking the solver."""
import contextlib,csv,io,json,re,sys
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'.development-artifacts/revnano-gerling2018'))
from REVNANO import revnano
S=(R/'backend/core/p7560.txt').read_text().strip();C=S.translate(str.maketrans('ACGT','TGCA'))
annotations=json.loads((R/'analysis/gerling2018_T_annotations_20261027/annotations.json').read_text())
reports={}
for key in ['42hb13','42hb14']:
 rows=[r for r in annotations if r['key']==key]
 inp=R/f'analysis/gerling2018_T_annotations_20261027/{key}_estimated_unpaired_T.rev'
 with contextlib.redirect_stdout(io.StringIO()):x=revnano.read_rev_file(inp.stem,str(inp.parent),verbose=False)
 st,sc,circular=json.loads((O/key/'contactmap.json').read_text());summary=json.loads((O/key/'summary.json').read_text());log=(O/f'{key}.log').read_text()
 def last_ids(pattern):
  hits=re.findall(pattern,log);return set(json.loads(hits[-1])) if hits else set()
 no_tree=set(summary['no_tree_ids']);zero=last_ids(r'- 0 routes:\s+\d+\s+\(Staples: (\[[^\]]*\])\)');amb=last_ids(r'- >1 routes:\s+\d+\s+\(Staples: (\[[^\]]*\])\)');overlap={int(i) for i in re.findall(r'Omitting staple (\d+) --',log)}
 counts=Counter();mismatches=[];mask_changes=[];audit=[]
 for i,r in enumerate(rows):
  m=st.get(str(i));virtual=[i]+x['extra_staples'].get(i,[])
  reasons=[label for label,ids in [('no routing tree',no_tree),('routes collapsed',zero),('ambiguous route',amb),('overlap omission',overlap)] if set(virtual)&ids]
  intervals=[]
  if m:
   assert m['sequence53']==r['original_sequence'];assert len(m['base_i53'])==len(m['sequence53'])
   expected={p for a in r['proposed']['segments'] if a['kind']=='unpaired_T_candidate' for p in range(a['start_1based']-1,a['end_1based'])}
   actual={p for p,b in enumerate(m['base_i53']) if b<0}
   if expected!=actual:mask_changes.append(r['published_id'])
   for p,b in enumerate(m['base_i53']):
    if b<0:continue
    counts[b]+=1
    if m['sequence53'][p]!=C[b]:mismatches.append([r['published_id'],p+1,b])
    assert sc[str(b)]['staple_id']==i and sc[str(b)]['staple_base_id']==p
   start=0
   for length in m['section_lengths']:
    indices=m['base_i53'][start:start+length]
    if indices[0]>=0:intervals.append(f'{indices[0]}..{indices[-1]} ({length}nt)')
    start+=length
  audit.append({'published_id':r['published_id'],'placed_complete_staple':bool(m),'paired_nt':sum(b>=0 for b in m['base_i53']) if m else 0,'failure_categories':'; '.join(reasons) if not m else '', 'scaffold_intervals_0based':'; '.join(intervals),'original_sequence':r['original_sequence'],'approved_annotation':r['proposed']['annotated_sequence']})
 assert len(sc)==7560 and circular
 assert all(sc[str(i)]['base_letter']==s for i,s in enumerate(S))
 assert len(counts)==summary['stage_results']['stage4_result'][0] and len(st)==summary['stage_results']['stage4_result'][1]
 report={'physical_staples_total':len(rows),'complete_staples_placed':len(st),'complete_staples_percent':round(100*len(st)/len(rows),1),'scaffold_bases_covered':len(counts),'scaffold_coverage_percent':round(100*len(counts)/7560,1),'unplaced_published_ids':[r['published_id'] for r in audit if not r['placed_complete_staple']], 'mismatched_base_pairs':mismatches,'overlapping_scaffold_positions':sum(v>1 for v in counts.values()),'annotation_mask_changed_published_ids':mask_changes,'solver_seconds':summary['solver_seconds'],'solver_error':summary['solver_error'],'failure_categories_counts_nonexclusive':dict(Counter(reason for r in audit if not r['placed_complete_staple'] for reason in r['failure_categories'].split('; ') if reason)),'local_control_results':{str(r['published_id']):r for r in audit if key=='42hb13' and r['published_id'] in [46,142,163,171,174,178]}}
 with (O/f'{key}_staple_results.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(audit[0]));w.writeheader();w.writerows(audit)
 reports[key]=report
(O/'results.json').write_text(json.dumps(reports,indent=2)+'\n')
for key,r in reports.items():print(key,json.dumps(r,indent=2))
