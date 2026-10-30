"""Compare individual paired domains and short windows against the Brick tab."""
from pathlib import Path
import csv,json,hashlib
from collections import Counter
import openpyxl
O=Path(__file__).resolve().parent
src=Path('/home/jojo/Work/NADOC/workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc')
pub=Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx')
d=json.loads(src.read_text());S=[s for s in d['strands'] if s['strand_type']=='staple']
w=openpyxl.load_workbook(pub,data_only=True)
P=[(i,s) for i,s in list(w['Brick'].values)[1:] if isinstance(s,str)]
rows=[]
for i,s in enumerate(S,1):
 offset=0
 for j,x in enumerate(s['domains'],1):
  n=abs(x['end_bp']-x['start_bp'])+1;q=s['sequence'][offset:offset+n];offset+=n
  if x.get('overhang_id'):continue
  hits=[{'index':k,'offset_0based':a} for k,p in P for a in range(len(p)-len(q)+1) if p[a:a+len(q)]==q]
  rows.append({'staple_number':i,'strand_id':s['id'],'domain_number':j,'helix':x['helix_id'],'start_bp':x['start_bp'],'end_bp':x['end_bp'],'length':n,'sequence_5to3':q,'matches':hits})
 assert offset==len(s['sequence'])
windows={}
for k in [8,10,12,14,16,18,21]:
 tested=0;hit=0;st=set();ps=set();examples=[]
 for r in rows:
  q=r['sequence_5to3']
  for a in range(len(q)-k+1):
   tested+=1; sub=q[a:a+k];hh=[i for i,p in P if sub in p]
   if hh:
    hit+=1;st.add(r['staple_number']);ps.update(hh)
    if len(examples)<8:examples.append({'staple':r['staple_number'],'domain':r['domain_number'],'domain_offset':a,'sequence':sub,'published_indices':hh})
 windows[k]={'tested_windows':tested,'matching_windows':hit,'staples_with_match':len(st),'published_staples_hit':len(ps),'examples':examples}
summary={'source':str(src.resolve()),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'published_sha256':hashlib.sha256(pub.read_bytes()).hexdigest(),'tab':'Brick','published_count':len(P),'published_total_nt':sum(len(p) for i,p in P),'published_length_range':[min(len(p) for i,p in P),max(len(p) for i,p in P)],'exact_full_staple_matches':sum(any(s['sequence']==p for i,p in P) for s in S),'whole_staple_substring_matches':sum(any(s['sequence'] in p for i,p in P) for s in S),'paired_domains':len(rows),'exact_domain_matches':sum(bool(r['matches']) for r in rows),'by_domain_length':{n:{'total':sum(r['length']==n for r in rows),'matched':sum(r['length']==n and bool(r['matches']) for r in rows)} for n in sorted({r['length'] for r in rows})},'windows':windows}
(O/'brick_results.json').write_text(json.dumps({'summary':summary,'domains':rows},indent=2)+'\n')
with (O/'brick_domain_matches.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
with (O/'published_brick_sequences.csv').open('w') as f:
 writer=csv.writer(f);writer.writerow(['published_index','sequence_5to3','length']);writer.writerows((i,s,len(s)) for i,s in P)
print(json.dumps(summary,indent=2))
