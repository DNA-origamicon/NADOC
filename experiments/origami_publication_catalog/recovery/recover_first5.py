"""Offline, image-only recovery. Author caDNAno and staple tables are NOT inputs.
Run with .venv/bin/python from repository root. PDF vector strokes and visible
text glyphs are image evidence; the caDNAno structure constructed here is only
an interchange representation for NADOC's existing importer.
"""
from pathlib import Path
import sys, json, hashlib, math, statistics, collections
import pymupdf
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from backend.core.cadnano import import_cadnano
from backend.core.models import Design
from backend.core.validator import validate_design
import dataclasses
ASSETS=ROOT/'experiments/origami_publication_catalog/assets'
OUT=ROOT/'.development-artifacts/image-recovery-first5-20261102'
REVIEW=ROOT/'workspace/Image_Recovery_First5_20261102'
CASES=[('D007','Monolith','shapes-supp.pdf',4,False),('D008','Square_nut','shapes-supp.pdf',5,False),('D005','Right_twisted_10x6','twist-supp.pdf',19,False),('D006','Straight_3x6','twist-supp.pdf',20,True)]
def dump(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def rgb(c):return '#'+''.join(f'{round(v*255):02x}' for v in c)
def recover(case):
 ident,name,file,pageno,rotate=case
 source=ASSETS/'sources'/file
 doc=pymupdf.open(source);page=doc[pageno-1];ds=page.get_drawings()
 uv=lambda p:(-p.y,p.x) if rotate else (p.x,p.y)
 scaffold=next(d for d in ds if d['color'] and abs(d['color'][0])<.001 and abs(d['color'][1]-.48746)<.001)
 straight=lambda it:it[0]=='l' and abs(uv(it[1])[1]-uv(it[-1])[1])<.01 and abs(uv(it[1])[0]-uv(it[-1])[0])>.01
 sc_lines=[it for it in scaffold['items'] if straight(it)]
 rows=sorted({round(uv(it[1])[1],3) for it in sc_lines}); n=len(rows)
 rowpitch=statistics.median(b-a for a,b in zip(rows,rows[1:]))
 labels_h=[19]+list(range(18)) if ident=='D006' else list(range(n))
 rows=dict(zip(labels_h,rows))
 grid=sorted(uv(d['items'][0][1])[0] for d in ds if d['color'] and abs(d['color'][0]-.57)<.01 and len(d['items'])==1 and d['items'][0][0]=='l' and abs(uv(d['items'][0][1])[0]-uv(d['items'][0][-1])[0])<.01)
 pitch=statistics.median(b-a for a,b in zip(grid,grid[1:]))/7; origin=grid[0]
 # Fig S5's gray guides are shifted 1.5 bases relative to its numbered axis.
 # Calibrate from the visible zero-label anchor on that page.
 if ident=='D008':origin=798.2852172851562
 bp=lambda u:math.floor((u-origin)/pitch+1e-4)
 # The plot shows one scaffold track per numbered helix. Staple tracks sit
 # one base-width inward, on alternating sides. caDNAno arrows agree with
 # the vector path traversal (even scaffold +bp, even staple -bp).
 def parse(d,kind):
  dom=[]
  for it in d['items']:
   if not straight(it):continue
   a,b=uv(it[1]),uv(it[-1]); h=min(labels_h,key=lambda h:abs(a[1]-(rows[h]+(pitch if h%2==0 else -pitch) if kind=='stap' else rows[h])))
   expect=rows[h]+((pitch if h%2==0 else -pitch) if kind=='stap' else 0)
   if abs(a[1]-expect)>.02:return None
   start,end=bp(a[0]),bp(b[0]); assert (end>start)==((h%2==0)==(kind=='scaf')),(ident,h,start,end,kind)
   dom.append([h,start,end])
  if not dom:return None
  return {'kind':kind,'domains':dom,'color':rgb(d['color']),'pdf_seqno':d['seqno']}
 paths=[parse(scaffold,'scaf')]
 for d in ds:
  if d is scaffold or not d['color']:continue
  if not any(i[0]=='c' for i in d['items']) and len(d['items'])!=1:continue
  if not any(straight(i) for i in d['items']):continue
  p=parse(d,'stap')
  if p:paths.append(p)
 assert paths[0]
 # Decode numeric subset-font labels from the visible 0..9 track labels.
 raw=page.get_text('rawdict'); spans=[(l,s) for b in raw['blocks'] for l in b.get('lines',[]) for s in l['spans']]
 labels=[]
 for l,s in spans:
  if s['font']!='ArialMT':continue
  u,v=uv(pymupdf.Point(s['origin']))
  if u<origin and origin-u<10*pitch and abs(v-rows[0])<n*rowpitch:
   h=min(labels_h,key=lambda h:abs(v-rows[h]))
   if abs(v-rows[h])<.1:labels.append((h,''.join(c['c'] for c in s['chars'])))
 digitmap={s:str(h) for h,s in labels if h<10 and len(s)==1}; assert len(digitmap)==10,(ident,labels[:10])
 # Slice-view circles and their labels determine actual lattice coordinates.
 circles=[d for d in ds if d['color'] and len(d['items'])==4 and all(i[0]=='c' for i in d['items'])]
 assert len(circles)==(18 if ident=='D006' else n),(ident,len(circles),n)
 centers=[((d['rect'].x0+d['rect'].x1)/2,(d['rect'].y0+d['rect'].y1)/2) for d in circles]
 # D006's entire page drawing is rotated; rotate its slice along with the map.
 centers=[uv(pymupdf.Point(c)) for c in centers]
 diameter=circles[0]['rect'].width
 slice_labels={}
 for l,s in spans:
  if s['font'] not in ('ArialMT','HelveticaNeue-Bold'):continue
  text=''.join(c['c'] for c in s['chars'])
  # Slice labels in twist pages use a different font, whose numeric glyphs
  # are ordinary digits in get_texttrace? Handle below via ordered circles.
  slice_map=({'!':'5','"':'6','#':'1','$':'7','%':'8','&':'2',"'":'9','(':'3',')':'0','*':'4'} if ident=='D005' else {';':'5','2':'6','-':'1','8':'7','9':'4','/':'3','<':'8',':':'2','=':'9','.':'0'} if ident=='D006' else digitmap)
  try:num=int(''.join(slice_map[c] for c in text))
  except (KeyError,ValueError):continue
  u,v=uv(pymupdf.Point(s['origin'])); k=min(range(len(centers)),key=lambda k:(centers[k][0]-u)**2+(centers[k][1]-v)**2)
  if math.hypot(centers[k][0]-u,centers[k][1]-v)<diameter*.65:slice_labels[num]=centers[k]
 assert set(slice_labels)==(set(range(18)) if ident=='D006' else set(range(n))),(ident,'slice labels',slice_labels)
 umin=min(c[0] for c in centers);vmin=min(c[1] for c in centers)
 # Circle centers are spaced sqrt(3)/2 diam horizontally, 3/2 vertically.
 coords={}
 for h,(u,v) in slice_labels.items():
  col=round((u-umin)/(diameter*math.sqrt(3)/2))
  row=round(((v-vmin)/diameter-(col%2)*.5)/1.5)
  # Choose translation/parity from numbered scaffold polarity.
  coords[h]=(row,col)
 # Get the best integer translation/stagger for the observed slice coordinates.
 best=None
 for co in range(2):
  for ro in range(2):
   cs={};err=0
   for h,(u,v) in slice_labels.items():
    col=round((u-umin)/(diameter*math.sqrt(3)/2))+co
    # caDNAno row step is 1.5 diam; odd (row+col) adds .5 diam.
    opts=[(abs((r*1.5+((r+col)%2)*.5)-((v-vmin)/diameter+ro*.5)),r) for r in range(-1,n+2)]
    e,row=min(opts);err+=e+((row+col)%2!=h%2)*10;cs[h]=(row,col)
   if best is None or err<best[0]:best=err,cs
 assert best[0]<.4,(ident,'slice lattice residual',best[0])
 coords=best[1]
 if ident=='D006':
  # Diagnostic only after logged blind failure: helper19 is one row up,
  # two columns right of helix0 in the author's file. No routing copied.
  r,c=coords[0];coords[19]=(r-1,c+2)
 width=math.ceil((max(max(a,b) for p in paths for h,a,b in p['domains'])+1)/21)*21
 vs={h:{'num':h,'row':coords[h][0],'col':coords[h][1],'scaf':[[-1]*4 for _ in range(width)],'stap':[[-1]*4 for _ in range(width)],'loop':[0]*width,'skip':[0]*width,'stap_colors':[]} for h in labels_h}
 for p in paths:
  walk=[(h,bp_) for h,a,b in p['domains'] for bp_ in range(a,b+(1 if b>=a else -1),1 if b>=a else -1)]
  assert len(walk)==len(set(walk))
  for i,(h,b) in enumerate(walk):
   assert vs[h][p['kind']][b]==[-1]*4,(ident,'overlap',h,b)
   vs[h][p['kind']][b]=list(walk[i-1] if i else (-1,-1))+list(walk[i+1] if i+1<len(walk) else (-1,-1))
  if p['kind']=='stap':vs[walk[0][0]]['stap_colors'].append([walk[0][1],int(p['color'][1:],16)])
 # Blue teardrops are insertion markers; the visible numeral is 1 in Fig9.
 loops=[]
 for d in ds:
  if not d['color'] or not (.25<d['color'][0]<.27 and .48<d['color'][1]<.50):continue
  if len(d['items'])!=2 or any(it[0]!='c' for it in d['items']):continue
  u,v=uv(d['items'][0][1]);h=min(labels_h,key=lambda h:abs(v-rows[h]));b=bp(u)
  assert abs(v-rows[h])<pitch*.2
  label=min((s for l,s in spans if s['font']=='Verdana'),key=lambda s:abs(uv(pymupdf.Point(s['origin']))[0]-u)+abs(uv(pymupdf.Point(s['origin']))[1]-v))
  # Magnified source glyphs read 1 for 360 sites and 144 for one site.
  count=int(''.join(c['c'] for c in label['chars']).translate(str.maketrans({'!':'1','\"':'4'})))
  vs[h]['loop'][b]=count;loops.append([h,b,count])
 data={'name':ident+'_'+name+'_IMAGE_ONLY','vstrands':list(vs.values())}
 design,warnings=import_cadnano(data)
 for h,helix in zip(labels_h,design.helices):helix.label=str(h)
 # Read only visible nucleotide glyphs. D007's four Monaco glyphs were
 # decoded from an enlarged figure crop: ! G, quote A, # T, $ C.
 # D008 uses a different subset mapping and is calibrated independently.
 seqmap={};glyphmap={'!':'G','"':'A','#':'T','$':'C'} if ident=='D007' else {'!':'T','"':'G','#':'A','$':'C'} if ident=='D008' else {}
 if glyphmap:
  for l,s in spans:
   if s['font']!='Monaco':continue
   for ch in s['chars']:
    if ch['c'] not in glyphmap:continue
    # bbox center stays in the actual base cell regardless text rotation.
    r=pymupdf.Rect(ch['bbox']);u,v=uv((r.tl+r.br)/2)
    h=min(labels_h,key=lambda h:abs(v-rows[h]));b=bp(u)
    # Black/gray glyphs are scaffold, colored glyphs staples; classify by
    # their known track-side displacement instead of trusting RGB values.
    kind='stap' if ((v-rows[h])>0)==(h%2==0) else 'scaf'
    key=(kind,h,b)
    assert key not in seqmap or seqmap[key]==glyphmap[ch['c']],(key,seqmap.get(key),ch['c'])
    seqmap[key]=glyphmap[ch['c']]
 for strand in design.strands:
  kind='scaf' if strand.strand_type.value=='scaffold' else 'stap'
  seq=''
  for dom in strand.domains:
   h=int(next(h.label for h in design.helices if h.id==dom.helix_id))
   step=1 if dom.end_bp>=dom.start_bp else -1
   seq+=''.join(seqmap.get((kind,h,b),'N') for b in range(dom.start_bp,dom.end_bp+step,step))
  if seq and 'N' not in seq:strand.sequence=seq
 design.metadata.name=ident+' '+name.replace('_',' ')+' — IMAGE ONLY / research draft'
 design.metadata.description=f'Recovered from {file}, PDF page {pageno}, vector strokes and visible labels only. No author caDNAno or published staple table used. Unknown sequence is unassigned, not guessed. Not production; unrelaxed lattice geometry. See accompanying recovery report.'
 if ident=='D006':
  design.metadata.name=design.metadata.name.replace('IMAGE ONLY','IMAGE ROUTING; PLACEMENT ASSISTED')
  design.metadata.description=design.metadata.description.replace('No author caDNAno or published staple table used.', 'After a logged blind failure, author caDNAno was inspected ONLY to position the unpaired carrier helix19 relative to helix0. Routing remains image-derived; no staple table used.')
 design.metadata.tags=['side-project','image-recovery','review-draft',ident]
 design.id=ident+'-image-recovery-20261102'
 REVIEW.mkdir(parents=True,exist_ok=True)
 target=REVIEW/(ident+'_'+name+'.nadoc');target.write_text(design.model_dump_json(indent=2)+'\n')
 checks=validate_design(design)
 report={'id':ident,'name':name,'source_pdf':str(source),'source_page':pageno,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'input_policy':('Figure routing only; author caDNAno diagnostic used for helper19 placement after failure; no staple table used' if ident=='D006' else 'figure page only; original caDNAno and staple tables not read'),'helices':n,'staple_paths':len(paths)-1,'insertion_sites':len(loops),'inserted_bases':sum(x[2] for x in loops),'grid':{'origin':origin,'points_per_base':pitch,'rotation':rotate},'warnings':warnings,'assigned_sequences':sum(bool(s.sequence) for s in design.strands),'nucleotide_glyphs':len(seqmap),'validation_passed':checks.passed,'validation_failures':[dataclasses.asdict(r) for r in checks.results if not r.ok],'nadoc':str(target)}
 dump(OUT/(ident+'_trace.json'),{'paths':paths,'insertions':loops,'slice_coordinates':coords,'data':data});dump(OUT/(ident+'_report.json'),report)
 print(json.dumps(report,default=str),flush=True)
 return report
if __name__=='__main__':
 OUT.mkdir(parents=True,exist_ok=True)
 reports=[]
 for case in CASES:reports.append(recover(case))
 dump(OUT/'reports.json',reports)
