"""Exhaust all circular registers, preserving the current scaffold route and staple walks."""
from pathlib import Path
from collections import defaultdict,Counter
import json,openpyxl
O=Path(__file__).resolve().parent;R=Path('/home/jojo/Work/NADOC')
D=json.loads((R/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc').read_text())
sc=next(s for s in D['strands'] if s['strand_type']=='scaffold');S=[s for s in D['strands'] if s['strand_type']=='staple']
def walk(s):
 return [(x['helix_id'],b) for x in s['domains'] if not x.get('overhang_id') for b in range(x['start_bp'],x['end_bp']+(1 if x['end_bp']>=x['start_bp'] else -1),1 if x['end_bp']>=x['start_bp'] else -1)]
pos={x:i for i,x in enumerate(walk(sc))};paths=[[pos[x] for x in walk(s)] for s in S]
P=[(i,s) for i,s in list(openpyxl.load_workbook('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx',data_only=True)['Brick'].values)[1:] if isinstance(s,str)]
tr=str.maketrans('ACGT','TGCA');out={}
for name in ['p7560','p8064','m13mp18']:
 seq=(R/f'backend/core/{name}.txt').read_text().strip().upper();comp=seq.translate(tr);N=len(seq)
 # candidate shifts from a >=7nt contiguous seed in each staple; exhaustive
 # because a full match necessarily contains this seed at the same offset.
 lookup=defaultdict(list)
 for k in range(3,8):
  for a in range(N):lookup[(k,''.join(comp[(a-j)%N] for j in range(k)))].append(a)
 hits=[];scores=Counter()
 for i,path in enumerate(paths):
  for k in range(7,2,-1):
   seeds=[a for a in range(len(path)-k+1) if all(path[a+j]==path[a]-j for j in range(k))]
   if seeds:break
  assert seeds, i
  a=seeds[0]; candidates=set()
  for idx,p in P:
   for b in range(len(p)-len(path)+1):
    for at in lookup.get((k,p[b+a:b+a+k]),[]):candidates.add(((at-path[a])%N,idx))
  pd=dict(P)
  for offset,idx in candidates:
   core=''.join(comp[(offset+j)%N] for j in path)
   if core in pd[idx]:hits.append({'staple_number':i+1,'offset':offset,'published_index':idx,'core_length':len(core),'core':core})
  if name=='p7560':
   core=''.join(comp[j] for j in path)
   original='';j=0
   for dom in S[i]['domains']:
    n=abs(dom['end_bp']-dom['start_bp'])+1
    if not dom.get('overhang_id'):original+=S[i]['sequence'][j:j+n]
    j+=n
   assert core==original,(i,'current sequence mismatch')
 for offset in {h['offset'] for h in hits}:scores[offset]=len({h['staple_number'] for h in hits if h['offset']==offset})
 out[name]={'registers_tested':N,'maximum_staples_with_core_substring_match_at_one_register':max(scores.values(),default=0),'best_registers':scores.most_common(10),'staples_with_any_register_match':len({h['staple_number'] for h in hits}),'hits':hits}
 print(name,{k:v for k,v in out[name].items() if k!='hits'})
(O/'register_scan.json').write_text(json.dumps(out,indent=2)+'\n')
