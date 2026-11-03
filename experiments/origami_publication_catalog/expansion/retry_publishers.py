from pathlib import Path
import requests,json,re,html,concurrent.futures,hashlib,urllib.parse
O=Path('experiments/origami_publication_catalog/assets/sources/pre2020-expansion');A=O.parents[1];D=O/'supplements'
old=json.loads((O/'supplement_downloads.json').read_text());dis=json.loads((O/'screening.json').read_text());bydoi={r['doi']:r for r in dis};dois={r['doi'] for r in old if r['status']=='download_failed'}
def run(doi):
 r=bydoi[doi];results=[]
 try:
  page=requests.get('https://www.nature.com/articles/'+doi.split('/')[1],timeout=25);page.raise_for_status();(O/(r['pmcid']+'-publisher.html')).write_text(page.text)
  urls=sorted(set(html.unescape(u)for u in re.findall(r'href="([^"]+)"',page.text) if '/esm/'in u and re.search(r'\.(pdf|xlsx|xls|docx|zip)(?:\?|$)',u)))
  for u in urls:
   f=u.split('/')[-1].split('?')[0];p=D/(r['pmcid']+'-'+f);e={'doi':doi,'pmcid':r['pmcid'],'url':u,'filename':f,'description':'Publisher-linked supplementary file'}
   try:
    if not p.exists():
     res=requests.get(u,timeout=25);res.raise_for_status();b=res.content
     if len(b)>35*1024*1024:raise ValueError('Over size cap')
     assert b.startswith((b'%PDF',b'PK',bytes.fromhex('d0cf11e0')));p.write_bytes(b)
    b=p.read_bytes();e.update(status='downloaded',local_file=str(p.relative_to(A)),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
   except Exception as ex:e.update(status='download_failed',error=str(ex))
   results.append(e)
 except Exception as ex:results.append({'doi':doi,'status':'publisher_access_failed','error':str(ex)})
 return results
new=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=5)as ex:
 for r in ex.map(run,sorted(dois)):new+=r
(O/'publisher_retry.json').write_text(json.dumps(new,indent=2));old+=[r for r in new if 'filename'in r];(O/'supplement_downloads.json').write_text(json.dumps(list({r.get('url',str(r)):r for r in old}.values()),indent=2));print('new downloaded',sum(r['status']=='downloaded'for r in new))
