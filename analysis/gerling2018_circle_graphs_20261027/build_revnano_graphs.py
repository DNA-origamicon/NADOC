"""Update circular maps from audited REVNANO results, retaining original plots."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,math,shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
RUN=R/'analysis/gerling2018_revnano_annotated_20261027';N=7560
old=json.loads((O/'report.json').read_text())
assert hashlib.sha256(Path(old['source']).read_bytes()).hexdigest()==old['source_sha256'], 'Native design changed; regenerate native intervals first.'
native=json.loads((O/'contact_maps.json').read_text())['native']
audit=json.loads((RUN/'results.json').read_text());maps={};metrics={}
for key in ['42hb13','42hb14']:
 st,sc,circular=json.loads((RUN/key/'contactmap.json').read_text());assert circular and len(sc)==N
 ref=json.loads((R/f'backend/data/gerling2018_{key}.json').read_text())['sequences'];rows=[]
 for sid,item in sorted(st.items(),key=lambda x:int(x[0])):
  source=ref[int(sid)];assert source['sequence']==item['sequence53']
  segments=[];offset=0
  for length in item['section_lengths']:
   indices=item['base_i53'][offset:offset+length]
   if indices[0]>=0:
    assert all(b==(indices[0]-k)%N for k,b in enumerate(indices))
    segments.append({'scaffold_indices':indices,'staple_offset':offset})
   else:assert all(b==-1 for b in indices)
   offset+=length
  rows.append({'id':source['index'],'segments':segments})
 maps[key]=rows
 with (O/f'{key}_revnano_binding_intervals.csv').open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['published_staple_id','segment','scaffold_first_0based','scaffold_last_0based','length','staple_offset_0based'])
  for row in rows:
   for i,seg in enumerate(row['segments']):
    a=seg['scaffold_indices'];w.writerow([row['id'],i,a[0],a[-1],len(a),seg['staple_offset']])
for key,rows,total in [('native',native,len(native)),('42hb13',maps['42hb13'],213),('42hb14',maps['42hb14'],176)]:
 counts=Counter(p for row in rows for seg in row['segments'] for p in seg['scaffold_indices'])
 metrics[key]={'shown':len(rows),'total':total,'intervals':sum(len(r['segments']) for r in rows),'links':sum(max(0,len(r['segments'])-1) for r in rows),'covered':len(counts),'overlap_positions':sum(n>1 for n in counts.values())}
 if key!='native':assert len(counts)==audit[key]['scaffold_bases_covered'] and not metrics[key]['overlap_positions']
def xy(p,r=1):
 t=math.pi/2-2*math.pi*p/N;return np.array([r*math.cos(t),r*math.sin(t)])
def draw(ax,rows,key,title,subtitle,color):
 ax.set_aspect('equal');ax.set_xlim(-1.27,1.27);ax.set_ylim(-1.32,1.34);ax.axis('off')
 t=np.linspace(0,2*np.pi,1500);ax.plot(np.cos(t),np.sin(t),color='#d9dee5',lw=7,zorder=1)
 for row in rows:
  for a,b in zip(row['segments'],row['segments'][1:]):
   pa=xy(a['scaffold_indices'][0]-(len(a['scaffold_indices'])-1)/2,.977)
   pb=xy(b['scaffold_indices'][0]-(len(b['scaffold_indices'])-1)/2,.977)
   path=MPath([pa,pa*.30,pb*.30,pb],[MPath.MOVETO,MPath.CURVE4,MPath.CURVE4,MPath.CURVE4])
   ax.add_patch(PathPatch(path,facecolor='none',edgecolor=color,lw=.55,alpha=.30,zorder=2))
  for seg in row['segments']:
   a=seg['scaffold_indices'];u=np.array([xy(a[0]-k) for k in np.linspace(0,len(a)-1,max(2,len(a)))])
   ax.plot(u[:,0],u[:,1],color=color,lw=4,solid_capstyle='butt',zorder=3)
 for p in range(0,N,1000):
  a,b=xy(p,1.035),xy(p,1.065);ax.plot([a[0],b[0]],[a[1],b[1]],color='#697786',lw=.8)
  x,y=xy(p,1.14);ax.text(x,y,str(p),ha='center',va='center',fontsize=9,color='#425166')
 ax.text(0,1.30,title,ha='center',fontsize=16,fontweight='bold',color='#192d43')
 ax.text(0,1.22,subtitle,ha='center',fontsize=10,color='#536275')
 m=metrics[key]
 ax.text(0,-1.25,f"{m['shown']}/{m['total']} complete staples · {m['intervals']} intervals · {m['links']} links\n{m['covered']:,} / 7,560 scaffold bases ({100*m['covered']/N:.1f}%)",ha='center',va='center',fontsize=10,color='#33475b',linespacing=1.6)
def plot(panels,stem):
 fig,axes=plt.subplots(1,2,figsize=(14,8),facecolor='white')
 for ax,panel in zip(axes,panels):draw(ax,*panel)
 fig.suptitle('Gerling 2018 — REVNANO circular contact maps',fontsize=20,fontweight='bold',y=.97,color='#192d43')
 fig.text(.5,.055,'Rim = p7560 index (0-based, clockwise). Colored = mapped binding; gray = not mapped in this result.\nInterior lines connect successive binding intervals of the same complete staple; loopout bases are excluded from the rim.',ha='center',fontsize=10.5,color='#33475b',linespacing=1.6)
 fig.text(.5,.015,'REVNANO maps are partial and sequence-consistent; physical geometry remains unverified. Circle layout is not the physical shape.',ha='center',fontsize=10,color='#6c5261')
 fig.subplots_adjust(top=.89,bottom=.13,wspace=.10,left=.025,right=.975)
 for suffix in ['png','svg']:fig.savefig(O/f'{stem}.{suffix}',dpi=180)
 plt.close(fig)
for suffix in ['png','svg']:
 oldplot=O/f'gerling2018_circle_graphs.{suffix}';archive=O/f'gerling2018_circle_graphs_pre_revnano.{suffix}'
 if oldplot.exists() and not archive.exists():shutil.copy2(oldplot,archive)
p13=(maps['42hb13'],'42hb13','REVNANO · page 3','42hb (1)–(3) · approved T annotations','#b47721')
p14=(maps['42hb14'],'42hb14','REVNANO · page 7','42hb (1)–(4) · approved T annotations','#8b579c')
plot([(native,'native','Current NADOC design','Stored topology · original scaffold register','#247aa0'),p13],'gerling2018_circle_graphs')
plot([p13,p14],'gerling2018_revnano_both_lists')
(O/'revnano_plot_report.json').write_text(json.dumps({'metrics':metrics,'inputs':{k:hashlib.sha256((RUN/k/'contactmap.json').read_bytes()).hexdigest() for k in maps},'native_source_sha256':old['source_sha256'],'scaffold_register':'Native stored offset0; REVNANO full circular p7560, no artificial rotation.','method':'Only final complete physical staples. Links join binding-interval midpoints in staple order; not measured crossover positions. Gray denotes unrepresented positions, not verified physical single-stranded regions. Original anchor-only plot archived as pre_revnano.','maps':maps},indent=2)+'\n')
print(json.dumps(metrics,indent=2))
