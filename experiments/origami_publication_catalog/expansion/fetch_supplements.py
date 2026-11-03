"""Retrieve small publisher supplements linked from primary full texts."""
from pathlib import Path
import urllib.request,urllib.parse,json,concurrent.futures,hashlib,zipfile,re,time
ROOT=Path(__file__).resolve().parents[3];A=ROOT/'experiments/origami_publication_catalog/assets';O=A/'sources/pre2020-expansion';D=O/'supplements';D.mkdir(exist_ok=True)
while not (O/'screening.json').exists():time.sleep(5)
records=json.loads((O/'screening.json').read_text());jobs=[]
for r in records:
 if not r.get('sequence_evidence') or any('review' in t.lower()for t in r['publication_types']):continue
 doi=r['doi']
 for s in r.get('supplements',[]):
  for f in s['links']:
   if not re.search(r'\.(pdf|xlsx?|docx?|csv|txt|zip)$',f,re.I):continue
   if doi.startswith('10.1038/'):
    url='https://static-content.springer.com/esm/art%3A'+urllib.parse.quote(doi,safe='')+'/MediaObjects/'+f.split('/')[-1]
   elif doi.startswith('10.1039/'):
    code=doi.split('/')[-1];url=f'https://www.rsc.org/suppdata/{code[:2] if code[:1].isdigit() else ""}' if False else ''
    # Use only the explicit supplemental link when it is an absolute URL.
    if f.startswith('http'):url=f
    else:continue
   else:continue
   jobs.append({'doi':doi,'pmcid':r['pmcid'],'url':url,'filename':f.split('/')[-1],'description':s['text']})
jobs=list({j['url']:j for j in jobs}.values())
def fetch(j):
 p=D/(j['pmcid']+'-'+j['filename']);result=dict(j)
 try:
  if not p.exists():
   with urllib.request.urlopen(urllib.request.Request(j['url'],headers={'User-Agent':'NADOC-literature-research'}),timeout=25) as r:
    b=r.read(35*1024*1024+1)
   if len(b)>35*1024*1024:raise ValueError('Supplement exceeds 35 MiB research download cap')
   if not (b.startswith(b'%PDF')or b.startswith(b'PK')or b.startswith(bytes.fromhex('d0cf11e0'))):raise ValueError('Response is not expected PDF/Office/ZIP format')
   p.write_bytes(b)
  b=p.read_bytes();result.update(status='downloaded',local_file=str(p.relative_to(A)),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
 except Exception as e:result.update(status='download_failed',error=str(e))
 return result
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
 for i,r in enumerate(ex.map(fetch,jobs)):
  results.append(r)
  if (i+1)%20==0:print('SUPPLEMENTS',i+1,'/',len(jobs),flush=True)
(O/'supplement_downloads.json').write_text(json.dumps(results,indent=2));print('DONE',len(results),'downloaded',sum(r['status']=='downloaded'for r in results),flush=True)
