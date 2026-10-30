"""Enumerate a broader bounded pool of exact-domain annotation alternatives."""
from pathlib import Path
from functools import lru_cache
import json
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
S=(R/'backend/core/p7560.txt').read_text().strip();N=len(S);C=S.translate(str.maketrans('ACGT','TGCA'));D=''.join(C[-i%N] for i in range(N));D+=D
pools=json.loads((O/'candidate_pools.json').read_text());original=json.loads((R/'analysis/gerling2018_T_annotations_20261027/annotations.json').read_text())
@lru_cache(None)
def hits(q):
 out=[];i=D.find(q)
 while 0<=i<N:out.append(-i%N);i=D.find(q,i+1)
 return out
for key in pools:
 rows=[r for r in original if r['key']==key];added=0
 for index,row in enumerate(rows):
  q=row['original_sequence'];n=len(q);gaps=[2] if key=='42hb13' else [2,5,7];allpaths=[]
  for left in [1,5,10]:
   if q[:left]!='T'*left:continue
   for right in [1,5,10]:
    if q[-right:]!='T'*right:continue
    end=n-right
    @lru_cache(None)
    def paths(i):
     candidates=[]
     for j in range(i+6,end+1):
      word=q[i:j];h=hits(word)
      if not h or set(word)=={'T'}:continue
      score=.05*len(word)+(1 if len(word)%7==0 else -.1*min(len(word)%7,7-len(word)%7))+.2/len(h)
      if j==end:candidates.append((score,(('P',i,j),)))
      for gap in gaps:
       if j+gap+6>end or q[j:j+gap]!='T'*gap:continue
       for value,tail in paths(j+gap):candidates.append((score+value,(('P',i,j),('U',j,j+gap))+tail))
     return sorted(candidates,reverse=True)[:64]
    for score,parts in paths(left):allpaths.append((score,(('U',0,left),)+parts+(('U',end,n),)))
  for score,parts in sorted(allpaths,reverse=True)[:128]:
   text=''.join(q[a:b] if kind=='P' else '*'+q[a:b]+'*' for kind,a,b in parts)
   if text in pools[key][index]:continue
   segments=[]
   for kind,a,b in parts:
    seg={'kind':'paired_candidate' if kind=='P' else 'unpaired_T_candidate','start_1based':a+1,'end_1based':b,'length':b-a,'sequence':q[a:b]}
    if kind=='P':seg.update(full_scaffold_hit_count=len(hits(q[a:b])),first_scaffold_indices_0based=hits(q[a:b]),longest_exact_substring_nt=b-a)
    segments.append(seg)
   assert text.replace('*','')==q
   pools[key][index][text]={'annotation':{'score':score,'annotated_sequence':text,'segments':segments},'models':['expanded_exact_domains']};added+=1
 print(key,'added',added,'total candidates',sum(len(p) for p in pools[key]),flush=True)
(O/'expanded_candidate_pools.json').write_text(json.dumps(pools,indent=2)+'\n')
