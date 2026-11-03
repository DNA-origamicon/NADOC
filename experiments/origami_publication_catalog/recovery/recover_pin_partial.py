"""Conservative raster evidence for D021. NOT a complete reconstructed design.
Never join fragments across an ambiguous raster intersection or infer staples.
"""
from recover_first5 import ROOT,OUT,REVIEW,ASSETS,dump,import_cadnano,validate_design
import pymupdf,numpy as np,hashlib,dataclasses
from PIL import Image
pdf=ASSETS/'sources/PMC5036142-41467_2016_BFncomms12787_MOESM1904_ESM.pdf'
doc=pymupdf.open(pdf); page=doc[18]
assert not page.get_drawings()
for item in page.get_images():
 obj=doc.extract_image(item[0]);(OUT/f'pin-{item[0]}.{obj["ext"]}').write_bytes(obj['image'])
im=np.array(Image.open(OUT/'pin-390.png').convert('RGB'))
blue=np.all(im==[0,102,204],axis=2)
# Label positions transcribed from the actual slice image, in staggered rows.
layout=[[(54,1),(28,3),(30,5),(32,7),(27,2),(29,4),(31,6),(33,8)],
 [(26,2),(8,4),(10,6),(34,8),(25,1),(7,3),(9,5),(11,7),(35,9)],
 [(24,1),(6,3),(0,5),(12,7),(36,9),(53,0),(23,2),(5,4),(1,6),(13,8),(37,10)],
 [(52,0),(22,2),(4,4),(2,6),(14,8),(38,10),(51,1),(21,3),(3,5),(15,7),(39,9)],
 [(50,1),(20,3),(18,5),(16,7),(40,9),(49,2),(19,4),(17,6),(41,8)],
 [(48,2),(46,4),(44,6),(42,8),(47,3),(45,5),(43,7)]]
coords={h:(r,c+1) for r,row in enumerate(layout) for h,c in row}
assert set(coords)==set(range(55)) and all((r+c)%2==h%2 for h,(r,c) in coords.items())
# The raster has 252 visible base cells. Origin is a local image coordinate:
# the screenshot does not show numbered BP ticks, so absolute register is unknown.
pitch=(2155-54)/252;center0=54+pitch/2
vs=[];fragments=[]
for h in range(55):
 expected=32+37.69*h+(8.3 if h%2 else 0)
 ys=range(max(0,round(expected)-3),min(im.shape[0],round(expected)+4))
 y=max(ys,key=lambda y:blue[y].sum())
 # Only cells with visibly blue center pixels are retained; tiny missed runs
 # are left unresolved, never silently filled or declared genuine nicks.
 occupied=[]
 for b in range(252):
  x=round(center0+b*pitch)
  if blue[y,max(0,x-1):x+2].any():occupied.append(b)
 runs=[]
 for b in occupied:
  if not runs or b>runs[-1][-1]+1:runs.append([b])
  else:runs[-1].append(b)
 v={'num':h,'row':coords[h][0],'col':coords[h][1],'scaf':[[-1]*4 for _ in range(252)],'stap':[[-1]*4 for _ in range(252)],'loop':[0]*252,'skip':[0]*252,'stap_colors':[]}
 for run in runs:
  if len(run)<3:continue
  if h%2:run=run[::-1]
  for i,b in enumerate(run):v['scaf'][b]=([h,run[i-1]] if i else [-1,-1])+([h,run[i+1]] if i+1<len(run) else [-1,-1])
  fragments.append({'helix':h,'start':run[0],'end':run[-1],'raster_y':y})
 vs.append(v)
design,warnings=import_cadnano({'name':'D021_PARTIAL_RASTER_EVIDENCE','vstrands':vs})
for h,helix in enumerate(design.helices):helix.label=str(h)
for strand in design.strands:
 strand.name='UNJOINED image fragment '+strand.id
 strand.notes='Evidence fragment only. Ends are extraction boundaries, NOT inferred biological nicks. No inter-helix joins or staple topology recovered.'
design.id='D021-partial-image-evidence-20261102'
design.metadata.name='D021 Pin pore — PARTIAL EVIDENCE ONLY'
design.metadata.description='INCOMPLETE image-recovery attempt, not a recovered origami. 55 slice-view helix positions and blue horizontal scaffold fragments only. No staple paths, no crossover connections, no sequences. Fragment ends are not biological nicks. BP origin is local to the raster; absolute register is unknown. Source: Supplementary Fig24a, PDF page19, DOI10.1038/ncomms12787. No native design file available or used. NOT suitable for synthesis or simulation.'
design.metadata.tags=['side-project','image-recovery','incomplete','evidence-only','D021']
f=REVIEW/'D021_Pin_pore_PARTIAL.nadoc';f.write_text(design.model_dump_json(indent=2)+'\n')
checks=validate_design(design)
report={'id':'D021','status':'FAILED complete recovery; partial evidence saved','source_pdf':str(pdf),'source_page':19,'source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'native_file_used':False,'helices':len(design.helices),'unjoined_scaffold_fragments':len(design.strands),'staples_recovered':0,'sequences_recovered':0,'register':'relative raster cells only; absolute BP offset unknown','failure':'No vector paths. Intersecting gray/routing pixels and endpoint marks prevent an unambiguous complete strand graph using the generalized vector method. No nucleotide letters. No native file available for diagnostics.','validation_passed':checks.passed,'validation_failures':[dataclasses.asdict(r) for r in checks.results if not r.ok],'nadoc':str(f)}
dump(OUT/'D021_report.json',report);dump(OUT/'D021_trace.json',{'fragments':fragments,'slice_coordinates':coords,'raster_calibration':{'center0':center0,'pixels_per_base':pitch,'absolute_register_known':False}})
print(report)
