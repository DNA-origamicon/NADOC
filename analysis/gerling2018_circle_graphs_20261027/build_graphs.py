"""Circular contact maps: native route versus conservative sequence-only anchors."""
from pathlib import Path
from collections import defaultdict, Counter
import csv, json, hashlib, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch

ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
raw=SOURCE.read_bytes(); d=json.loads(raw)
ref=json.loads((ROOT/'backend/data/gerling2018_42hb13.json').read_text())
S=(ROOT/'backend/core/p7560.txt').read_text().strip().upper(); N=len(S); assert N==7560
C=S.translate(str.maketrans('ACGT','TGCA'))
sc=next(s for s in d['strands'] if s['strand_type']=='scaffold')
assert sc['sequence']==S[:len(sc['sequence'])], 'Stored scaffold register changed; remap before comparing.'
assert all(not h.get('loop_skips') for h in d['helices']), 'Indels require sequence-aware indexing.'
labels={h['id']:str(h['label'] if h.get('label') is not None else i) for i,h in enumerate(d['helices'])}
def walk(dom):
 a,b=dom['start_bp'],dom['end_bp'];step=1 if a<=b else -1
 return [(dom['helix_id'],bp) for bp in range(a,b+step,step)]
pos={site:i for i,site in enumerate(site for dom in sc['domains'] for site in walk(dom))}
assert len(pos)==len(sc['sequence'])
native=[]
for order,st in enumerate([s for s in d['strands'] if s['strand_type']=='staple' and not s.get('is_reference')],1):
 segments=[]; seqoff=0
 for di,dom in enumerate(st['domains']):
  sites=walk(dom)
  if dom.get('overhang_id'):seqoff+=len(sites);continue
  run=[]
  for k,site in enumerate(sites):
   p=pos[site]
   assert st['sequence'][seqoff+k]==C[p], 'Native staple/scaffold complement mismatch.'
   if run and p!=(run[-1]-1)%N:
    segments.append({'scaffold_indices':run,'helix_label':labels[dom['helix_id']],'domain_index':di});run=[]
   run.append(p)
  if run:segments.append({'scaffold_indices':run,'helix_label':labels[dom['helix_id']],'domain_index':di})
  seqoff+=len(sites)
 native.append({'id':order,'name':st.get('name') or f'Design staple {order}','segments':segments})

def sequence_anchors(minimum):
 # Search all rotations and the circular-origin boundary without rotating design.
 seed=defaultdict(list)
 for p in range(N):seed[''.join(C[(p-k)%N] for k in range(minimum))].append(p)
 staples=[]
 for r in ref['sequences']:
  q=r['sequence']; assignments=[set() for _ in q]; hits=[]
  for a in range(len(q)-minimum+1):
   for p in seed.get(q[a:a+minimum],[]):
    if a and q[a-1]==C[(p+1)%N]:continue
    length=minimum
    while a+length<len(q) and q[a+length]==C[(p-length)%N]:length+=1
    hits.append({'staple_offset':a,'first_scaffold_index':p,'length':length})
    for k in range(length):assignments[a+k].add((p-k)%N)
  # Retain only positions where all exact-match evidence agrees. Runs shorter
  # than the seed threshold are omitted; no arbitrary tie-breaking.
  segments=[]; run=[]; start=None
  def flush():
   if len(run)>=minimum:segments.append({'staple_offset':start,'scaffold_indices':list(run)})
  for a,options in enumerate(assignments):
   p=next(iter(options)) if len(options)==1 else None
   if p is None or (run and p!=(run[-1]-1)%N):flush();run=[];start=None
   if p is not None:
    if start is None:start=a
    run.append(p)
  flush()
  for seg in segments:
   a=seg['staple_offset'];assert q[a:a+len(seg['scaffold_indices'])]==''.join(C[p] for p in seg['scaffold_indices'])
  staples.append({'id':r['index'],'sequence':q,'segments':segments,'ambiguous_query_bases':sum(len(x)>1 for x in assignments),'raw_candidates':hits})
 return staples

def stats(staples):
 counts=Counter(p for st in staples for seg in st['segments'] for p in seg['scaffold_indices'])
 return {'staples_total':len(staples),'staples_with_anchors':sum(bool(st['segments']) for st in staples),'binding_segments':sum(len(st['segments']) for st in staples),'links':sum(max(0,len(st['segments'])-1) for st in staples),'scaffold_bases_covered':len(counts),'covered_bases_outside_native_route':sum(p>=len(pos) for p in counts),'scaffold_positions_with_multiple_mapped_bases':sum(v>1 for v in counts.values())}

published=sequence_anchors(12); ns=stats(native); ps=stats(published)
# Record sensitivity; these alternatives are NOT silently merged into the plot.
sensitivity={str(k):stats(sequence_anchors(k)) for k in [10,12,14,16]}
report={'source':str(SOURCE),'source_sha256':hashlib.sha256(raw).hexdigest(),'reference_sheet':ref['sheet'],'reference_workbook_sha256':ref['workbook_sha256'],'p7560_sha256':hashlib.sha256(S.encode()).hexdigest(),'index_convention':'0-based p7560 index; clockwise from top. Native stored offset0 retained. Offset17 is NOT applied.','native':ns,'published':ps,'sensitivity':sensitivity,'method':'All maximal exact reverse-complement matches >=12nt across circular p7560. Retain only consecutive >=12nt runs with exactly one scaffold assignment per staple base across all candidates. Repeated/conflicting placements omitted. No global exclusion solver. Lines join adjacent retained intervals of the same staple; on sequence panel they may span unresolved domains and are not confirmed crossovers.','limitations':['Sequence panel is a conservative partial anchor graph, not a reconstructed complete design.','Unique >=12nt matches can still occur fortuitously or extend across a biological domain boundary.','No physical helix identity is inferred for published sequences.','Gray on native panel denotes omitted sequence coordinates, not proof of a physical unpaired loop.','No full-scaffold register optimization or REVNANO solve was performed.']}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
(OUT/'contact_maps.json').write_text(json.dumps({'native':native,'published':published},indent=2)+'\n')
for name,staples in [('native',native),('published',published)]:
 with (OUT/f'{name}_binding_intervals.csv').open('w') as f:
  wr=csv.writer(f);wr.writerow(['staple_id','segment','scaffold_first_0based','scaffold_last_0based','length','helix_label','staple_offset_0based'])
  for st in staples:
   for i,seg in enumerate(st['segments']):
    a=seg['scaffold_indices'];wr.writerow([st['id'],i,a[0],a[-1],len(a),seg.get('helix_label','not inferred'),seg.get('staple_offset','')])

def xy(p,r=1):
 t=math.pi/2-2*math.pi*p/N;return np.array([r*math.cos(t),r*math.sin(t)])
def draw(ax,staples,stat,title,subtitle,inferred=False):
 ax.set_aspect('equal');ax.set_xlim(-1.27,1.27);ax.set_ylim(-1.32,1.34);ax.axis('off')
 t=np.linspace(0,2*np.pi,1500);ax.plot(np.cos(t),np.sin(t),color='#d9dee5',lw=7,zorder=1)
 for st in staples:
  for a,b in zip(st['segments'],st['segments'][1:]):
   # Endpoint midpoint is for visual legibility only, not a crossover coordinate.
   pa=xy((a['scaffold_indices'][0]-(len(a['scaffold_indices'])-1)/2)%N,.977)
   pb=xy((b['scaffold_indices'][0]-(len(b['scaffold_indices'])-1)/2)%N,.977)
   path=MPath([pa,pa*.30,pb*.30,pb],[MPath.MOVETO,MPath.CURVE4,MPath.CURVE4,MPath.CURVE4])
   ax.add_patch(PathPatch(path,facecolor='none',edgecolor='#b47721' if inferred else '#315b8a',lw=.65 if inferred else .48,alpha=.43 if inferred else .24,linestyle=(0,(3,2)) if inferred else '-',zorder=2))
  for seg in st['segments']:
   a=seg['scaffold_indices'];u=np.array([xy(a[0]-k) for k in np.linspace(0,len(a)-1,max(2,len(a)))])
   ax.plot(u[:,0],u[:,1],color='#b47721' if inferred else '#247aa0',lw=4,solid_capstyle='butt',zorder=3)
 if inferred:
  occupancy=Counter(p for st in staples for seg in st['segments'] for p in seg['scaffold_indices'])
  conflict=[p for p,n in occupancy.items() if n>1]
  pts=np.array([xy(p,1.025) for p in conflict])
  if len(pts):ax.scatter(pts[:,0],pts[:,1],s=6,color='#cb3b51',zorder=4)
 for p in range(0,N,1000):
  a,b=xy(p,1.035),xy(p,1.065);ax.plot([a[0],b[0]],[a[1],b[1]],color='#697786',lw=.8)
  x,y=xy(p,1.14);ax.text(x,y,str(p),ha='center',va='center',fontsize=9,color='#425166')
 ax.text(0,1.30,title,ha='center',fontsize=16,fontweight='bold',color='#192d43')
 ax.text(0,1.22,subtitle,ha='center',fontsize=10,color='#536275')
 ax.text(0,-1.25,f"{stat['staples_with_anchors']}/{stat['staples_total']} staples shown · {stat['binding_segments']} intervals · {stat['links']} links\n{stat['scaffold_bases_covered']:,} / 7,560 scaffold bases covered",ha='center',va='center',fontsize=10,color='#33475b',linespacing=1.6)

fig,axes=plt.subplots(1,2,figsize=(14,8),facecolor='white')
draw(axes[0],native,ns,'Current NADOC design','Stored topology · original scaffold register')
draw(axes[1],published,ps,'Published staple sequence list','42hb (1)–(3) · unique exact anchors ≥12 nt',True)
fig.suptitle('Gerling 2018 — circular scaffold–staple contact maps',fontsize=20,fontweight='bold',y=.97,color='#192d43')
fig.text(.5,.055,'Rim = p7560 scaffold position (clockwise). Colored rim = mapped binding intervals; gray = not mapped.\nInterior lines join successive mapped intervals of one staple. Dashed lines may span unresolved domains; red ticks flag overlapping assignments.',ha='center',fontsize=11,color='#33475b',linespacing=1.6)
fig.text(.5,.015,'Sequence-derived graph is partial; short or ambiguously placed domains are omitted. Circle layout does not imply a physical circular shape.',ha='center',fontsize=10,color='#6c5261')
fig.subplots_adjust(top=.89,bottom=.13,wspace=.10,left=.025,right=.975)
fig.savefig(OUT/'gerling2018_circle_graphs.png',dpi=180)
fig.savefig(OUT/'gerling2018_circle_graphs.svg')
assert SOURCE.read_bytes()==raw
print(json.dumps(report,indent=2))
