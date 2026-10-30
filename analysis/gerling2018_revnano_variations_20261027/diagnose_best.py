"""Audit best maps and distinguish unresolved fragments from complete staples."""
from pathlib import Path
from collections import Counter
import csv,json
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
S=(R/'backend/core/p7560.txt').read_text().strip();C=S.translate(str.maketrans('ACGT','TGCA'));N=len(S)
best=json.loads((O/'selected_best.json').read_text());out={}
for key,b in best.items():
 path=R/b['path'];a=json.loads((path/'annotations.json').read_text());st,sc,circ=json.loads((path/'solver/contactmap.json').read_text());ref=json.loads((R/f'backend/data/gerling2018_{key}.json').read_text())['sequences'];diag=json.loads((path/'solver/fragment_diagnostics.json').read_text());summary=json.loads((path/'solver/summary.json').read_text());rows=[];coverage=Counter();fragment_coverage=Counter()
 for p,letter in enumerate(S):assert sc[str(p)]['base_letter']==letter
 for sid,m in st.items():
  i=int(sid);assert m['sequence53']==ref[i]['sequence'];expected={p for seg in a[i]['segments'] if seg['kind']=='unpaired_T_candidate' for p in range(seg['start_1based']-1,seg['end_1based'])}
  assert {p for p,v in enumerate(m['base_i53']) if v<0}==expected
  for p,v in enumerate(m['base_i53']):
   if v<0:continue
   assert m['sequence53'][p]==C[v];assert sc[str(v)]['staple_id']==i and sc[str(v)]['staple_base_id']==p;coverage[v]+=1
 for i,r in enumerate(ref):
  ids=[i]+diag['extra_staples'].get(str(i),[]);blocks=[s for s in a[i]['segments'] if s['kind']=='paired_candidate'];assert len(ids)==len(blocks)
  for vi,seg in zip(ids,blocks):
   route=diag['staples_placed'].get(str(vi),[]);letters=[]
   for first,n in route:
    for k in range(n):fragment_coverage[(first-k)%N]+=1;letters.append(C[(first-k)%N])
   if route:assert ''.join(letters)==seg['sequence']
   reasons=[name for name,field in [('no_tree','staple_ids_with_no_tree'),('collapsed','staple_ids_with_zero_route'),('ambiguous','staple_ids_with_persistent_ambiguous_route'),('overlap','staple_ids_with_overlap_problems')] if vi in (diag.get(field) or [])]
   rows.append({'published_id':r['index'],'paired_block_start_1based':seg['start_1based'],'paired_block_end_1based':seg['end_1based'],'sequence':seg['sequence'],'length':seg['length'],'multiple_of_7':seg['length']%7==0,'whole_staple_placed':str(i) in st,'fragment_placed_before_recomposition':bool(route),'reason':';'.join(reasons),'scaffold_route_0based':json.dumps(route)})
 assert len(coverage)==b['covered'] and all(n==1 for n in coverage.values())
 assert all(n==1 for n in fragment_coverage.values());assert len(fragment_coverage)==summary['stage_results']['stage3_result'][0]
 with (O/f'{key}_fragment_diagnosis.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 controls={}
 if key=='42hb13':
  for pub,first in [(163,3119),(171,3175),(174,398),(178,76)]:
   i=next(i for i,r in enumerate(ref) if r['index']==pub);m=st.get(str(i));actual=[v for v in m['base_i53'] if v>=0] if m else[];controls[str(pub)]=actual==list(range(first,first-19,-1))
  for pub in [46,142]:
   i=next(i for i,r in enumerate(ref) if r['index']==pub);controls[str(pub)]={'placed':str(i) in st,'blocks':[r for r in rows if r['published_id']==pub]}
 out[key]={'final_complete_staples':len(st),'final_scaffold_bases':len(coverage),'stage3_virtual_fragments_placed':sum(r['fragment_placed_before_recomposition'] for r in rows),'stage3_scaffold_bases':len(fragment_coverage),'discarded_fragment_bases_during_whole_staple_recomposition':len(fragment_coverage)-len(coverage),'unresolved_fragment_reasons':dict(Counter(r['reason'] or 'unclassified' for r in rows if not r['fragment_placed_before_recomposition'])),'zero_mismatches':True,'zero_overlap':True,'published_sequences_and_annotation_masks_preserved':True,'reciprocal_indices_valid':True,'local_controls':controls}
(O/'validation_and_diagnostics.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
