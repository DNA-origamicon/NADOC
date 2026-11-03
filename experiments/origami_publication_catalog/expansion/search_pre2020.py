"""Archive-backed expanded discovery and full-text evidence triage; never auto-accepts designs."""
from pathlib import Path
import json,urllib.request,urllib.parse,concurrent.futures,xml.etree.ElementTree as ET,re,time,os
ROOT=Path(__file__).resolve().parents[3];ASSETS=ROOT/'experiments/origami_publication_catalog/assets';OUT=ASSETS/'sources/pre2020-expansion';OUT.mkdir(parents=True,exist_ok=True)
assert os.path.ismount('/media/jojo/Archive') and str(OUT.resolve()).startswith('/media/jojo/Archive/')
API='https://www.ebi.ac.uk/europepmc/webservices/rest/'
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'NADOC-research-catalog/0.1'})
 with urllib.request.urlopen(req,timeout=25) as r:return r.read()
queries=['("scaffolded DNA" OR "scaffolded origami" OR "DNA nanostructure" OR "DNA nanostructures") AND (staple OR staples) AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]', '("DNA origami") AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]']
records=json.loads((ASSETS/'sources/discovery.json').read_text())['records'];logs=[]
for q in queries:
 cursor='*';hits=[]
 while True:
  url=API+'search?'+urllib.parse.urlencode({'query':q,'format':'json','pageSize':1000,'resultType':'core','cursorMark':cursor});d=json.loads(get(url));hits+=d['resultList']['result'];nxt=d.get('nextCursorMark')
  if not nxt or nxt==cursor or not d['resultList']['result']:break
  cursor=nxt
 logs.append({'query':q,'hits':d['hitCount'],'retrieved':len(hits)});records+=hits
merged={}
for r in records:
 key=(r.get('doi')or r['source']+':'+r['id']).lower()
 if key not in merged or (r.get('pmcid') and not merged[key].get('pmcid')):merged[key]=r
records=list(merged.values());(OUT/'discovery.json').write_text(json.dumps(records));(OUT/'queries.json').write_text(json.dumps(logs,indent=2));print('DISCOVERED',len(records),logs,flush=True)
XL='{http://www.w3.org/1999/xlink}href'
def text(e):return re.sub(r'\s+',' ',''.join(e.itertext())).strip()
def screen(r):
 pmc=r.get('pmcid');result={k:r.get(k,'') for k in ['doi','title','pmcid','firstPublicationDate','isOpenAccess']};result['publication_types']=r.get('pubTypeList',{}).get('pubType',[])
 result['abstract']=re.sub('<[^>]+>',' ',r.get('abstractText',''));result['status']='no_pmc_fulltext'
 if not pmc:return result
 p=ASSETS/'sources'/f'{pmc}.xml'
 try:
  if not p.exists():
   p=OUT/f'{pmc}.xml'
   if not p.exists():p.write_bytes(get(API+pmc+'/fullTextXML'))
  root=ET.fromstring(p.read_bytes());result['xml_file']=str(p.relative_to(ASSETS));result['status']='fulltext_evidence_triaged'
  paras=[text(e) for tag in ['p','caption','table-wrap','supplementary-material'] for e in root.iter(tag)]
  result['sequence_evidence']=list(dict.fromkeys(x for x in paras if re.search(r'(staple.{0,100}(sequence|table|list)|sequence.{0,100}staple|oligonucleotide.{0,80}(sequence|table))',x,re.I)))
  result['lattice_evidence']=list(dict.fromkeys(x for x in paras if re.search(r'honeycomb|square.lattice|square.grid|parallel helices|DNA.brick|wireframe|wire.frame|truss|non.standard',x,re.I)))
  result['design_evidence']=list(dict.fromkeys(x for x in paras if re.search(r'origami',x,re.I) and re.search(r'design|rectangle|triangle|tube|bundle|shape',x,re.I)))[:20]
  result['characterization_evidence']=list(dict.fromkeys(x for x in paras if re.search(r'cryo.{0,5}(EM|electron)|negative.stain|atomic force microscopy|DNA.PAINT|super.resolution|electron tomography',x,re.I)))[:12]
  result['supplements']=[{'text':text(e),'links':list(dict.fromkeys(n.get(XL) for n in e.iter() if n.get(XL)))} for e in root.iter('supplementary-material')]
  result['repository_links']=sorted({e.get(XL) for e in root.iter() if e.get(XL) and re.search(r'github|zenodo|figshare|dryad|nanobase|emdb|empiar|ebi.ac.uk/pdbe|rcsb|data.4tu',e.get(XL),re.I)})
  result['references']=[{'doi':next((text(i) for i in e.iter('pub-id') if i.get('pub-id-type')=='doi'),''),'citation':text(e)[:650]} for e in root.iter('ref') if 'origami' in text(e).lower()]
 except Exception as e:result['status']='fulltext_access_failed';result['error']=str(e)
 return result
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
 for i,r in enumerate(ex.map(screen,records)):
  results.append(r)
  if (i+1)%100==0:
   (OUT/'screening-progress.json').write_text(json.dumps(results));print('SCREENED',i+1,flush=True)
(OUT/'screening.json').write_text(json.dumps(results,indent=2));print('DONE',len(results),'accessible',sum(r['status']=='fulltext_evidence_triaged' for r in results),'seqcontexts',sum(bool(r.get('sequence_evidence')) for r in results),flush=True)
