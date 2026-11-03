from pathlib import Path
import json,openpyxl
from collections import Counter
O=Path(__file__).resolve().parent;root=Path('/home/jojo/Work/NADOC')
w=openpyxl.load_workbook('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx',data_only=True)
P=[(i,s) for i,s in list(w['Brick'].values)[1:] if isinstance(s,str)]
tr=str.maketrans('ACGT','TGCA')
results={}
for name in ['m13mp18','p7560','p8064']:
 sc=(root/f'backend/core/{name}.txt').read_text().strip().upper();ref=(sc+sc).translate(tr)[::-1];N=len(sc)
 lookup={}
 for a in range(N):lookup.setdefault(ref[a:a+7],[]).append(a)
 rows=[]
 for idx,raw in P:
  left=10 if raw.startswith('T'*10) else 0;right=10 if raw.endswith('T'*10) else 0
  q=raw[left:len(raw)-right if right else len(raw)];n=len(q)
  # exact segment tiling: minimum number of >=7nt contiguous scaffold pieces
  dp=[None]*(n+1);dp[0]=(0,[],1)
  for a in range(n):
   if dp[a] is None:continue
   for pos in lookup.get(q[a:a+7],[]):
    end=7
    while a+end<n and ref[pos+end]==q[a+end]:end+=1
    for length in range(7,end+1):
     b=a+length;cost=dp[a][0]+1
     block={'query_start':a+left,'length':length,'scaffold_start_0based':(N-1-pos)%N,'scaffold_end_0based':(N-pos-length)%N,'sequence':q[a:b]}
     if dp[b] is None or cost<dp[b][0]:dp[b]=(cost,dp[a][1]+[block],dp[a][2])
     elif cost==dp[b][0]:dp[b]=(cost,dp[b][1],min(1000000,dp[b][2]+dp[a][2]))
  # long anchor coverage regardless of full tiling
  covered=set()
  for a in range(max(0,n-11)):
   if q[a:a+12] in ref:covered.update(range(a,a+12))
  rows.append({'index':idx,'raw':raw,'core':q,'tail5':left,'tail3':right,'tile':dp[n],'anchor12_coverage':len(covered)})
 results[name]={'scaffold_length':N,'fully_tiled':sum(r['tile'] is not None for r in rows),'unique_minimum_tilings':sum(r['tile'] is not None and r['tile'][2]==1 for r in rows),'core_nt':sum(len(r['core']) for r in rows),'anchor12_covered_nt':sum(r['anchor12_coverage'] for r in rows),'segment_counts':dict(Counter(r['tile'][0] for r in rows if r['tile'])),'rows':rows}
 print(name,{k:v for k,v in results[name].items() if k!='rows'})
(O/'brick_scaffold_mapping.json').write_text(json.dumps(results,indent=2)+'\n')
