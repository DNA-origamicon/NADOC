"""Local p7560 register audit, with explicit alternatives for the omitted scaffold segment."""
from pathlib import Path
import json,csv,hashlib
from collections import defaultdict
import openpyxl
O=Path(__file__).resolve().parent;R=Path('/home/jojo/Work/NADOC')
source=R/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
D=json.loads(source.read_text());sc=next(s for s in D['strands'] if s['strand_type']=='scaffold');S=[s for s in D['strands'] if s['strand_type']=='staple']
ref=(R/'backend/core/p7560.txt').read_text().strip().upper();N=len(ref);comp=ref.translate(str.maketrans('ACGT','TGCA'))
def walk(d):return [(d['helix_id'],b) for b in range(d['start_bp'],d['end_bp']+(1 if d['start_bp']<=d['end_bp'] else -1),1 if d['start_bp']<=d['end_bp'] else -1)]
scwalk=[x for d in sc['domains'] for x in walk(d)];position={x:i for i,x in enumerate(scwalk)};L=len(scwalk)
rows=[];mismatches=[]
for i,s in enumerate(S,1):
 offset=0
 for j,d in enumerate(s['domains'],1):
  sites=walk(d);q=s['sequence'][offset:offset+len(sites)];offset+=len(sites)
  if d.get('overhang_id'):continue
  inds=[position[x] for x in sites];expected=''.join(sc['sequence'][p].translate(str.maketrans('ACGT','TGCA')) for p in inds)
  if q!=expected:mismatches.append((i,j))
  rows.append({'staple':i,'strand_id':s['id'],'domain':j,'helix':d['helix_id'],'start_bp':d['start_bp'],'end_bp':d['end_bp'],'sequence':q,'indices':inds,'length':len(q),'crosses_scaffold_break':0 in inds and L-1 in inds})
w=openpyxl.load_workbook('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx',data_only=True)
sets={name:[(i,s) for i,s in list(w[name].values)[1:] if isinstance(s,str)] for name in ['Brick','42hb (1)-(3)']}
# Focus on all staples touching the first scaffold helix, plus complete domains
# wholly within the first126 scaffold bases for a separate downstream check.
h=scwalk[0][0];local=[r for r in rows if r['helix']==h]
first=[r for r in rows if max(r['indices'])<126]
results={}
for label,selected in [('break_helix_stored_route',local),('break_helix_contiguous_circle',local),('first126_stored_route',first),('first60_stored_route',[r for r in rows if max(r['indices'])<60]),('first98_stored_route',[r for r in rows if max(r['indices'])<98])]:
 sheet_results={}
 for name,published in sets.items():
  lengths={r['length'] for r in selected};lookup={n:defaultdict(list) for n in lengths}
  for idx,p in published:
   for n in lengths:
    for j in range(len(p)-n+1):lookup[n][p[j:j+n]].append([idx,j])
  candidates=[]
  for register in range(N):
   hits=[]
   for row in selected:
    inds=row['indices']
    if label=='break_helix_contiguous_circle':inds=[p-L if p>L//2 else p for p in inds]
    q=''.join(comp[(register+p)%N] for p in inds)
    found=lookup[len(q)].get(q,[])
    if found:hits.append({'staple':row['staple'],'domain':row['domain'],'length':len(q),'sequence':q,'published_hits':found})
   candidates.append({'register_0based':register,'matched_domains':len(hits),'matched_nt':sum(x['length'] for x in hits),'long_domains':sum(x['length']>=10 for x in hits),'long_nt':sum(x['length'] for x in hits if x['length']>=10),'hits':hits})
  candidates.sort(key=lambda c:(c['long_nt'],c['matched_nt'],c['matched_domains']),reverse=True)
  sheet_results[name]={'domains':len(selected),'nt':sum(r['length'] for r in selected),'all_domains_match_registers':[c['register_0based'] for c in candidates if c['matched_domains']==len(selected)],'top':candidates[:20],'current_register':next(c for c in candidates if c['register_0based']==0)}
  print(label,name,'domains',len(selected),'nt',sum(r['length'] for r in selected),'top',[(c['register_0based'],c['matched_domains'],c['long_nt']) for c in candidates[:6]],'all',len(sheet_results[name]['all_domains_match_registers']))
 results[label]=sheet_results
summary={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'scaffold_length_model':L,'p7560_length':N,'unrepresented_scaffold_nt':N-L,'start_site':scwalk[0],'end_site':scwalk[-1],'staple_domain_complement_mismatches':mismatches,'paired_domains':len(rows),'paired_nt_checked':sum(r['length'] for r in rows),'start_helix_domains':local,'first126_domains':first}
(O/'scaffold_start_audit.json').write_text(json.dumps({'summary':summary,'sweeps':results},indent=2)+'\n')
with (O/'scaffold_break_domains.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=list(local[0]));writer.writeheader();writer.writerows(local)
print('summary', {k:v for k,v in summary.items() if not k.endswith('_domains')})
