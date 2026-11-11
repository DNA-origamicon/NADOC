"""Read-only archive inventory; does not instantiate or author molecular structures."""
import hashlib,json,zipfile
import ledger as L
from review_batch_0001 import evidence

def main():
 path=L.ROOT/'assets/sources/acs-expansion-20261104/10560103-nn7b08345_si_001.zip'
 ev=evidence(path,'https://ndownloader.figshare.com/files/10560103','All5archive members inventoried; JSON parsed for metadata only, YAML header inspected, no molecular construction')
 rows=[]
 with zipfile.ZipFile(path) as z:
  for n in z.namelist():
   data=z.read(n);r=dict(name=n,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
   if n.endswith('.json'):
    d=json.loads(data);r.update(internal_name=d.get('name'),vstrand_records=len(d.get('vstrands',[])))
   rows.append(r)
 assert len(rows)==5
 L.atomic(L.HERE/'gap2018_archive_inventory.json',json.dumps({'source':ev,'members':rows,'limitation':'Presence/metadata only; no topology, sequence compatibility or full recipe validation.'},indent=2)+'\n')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']=='10.1021/acsnano.7b08345')
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Retain hashed native-source archive evidence without authoring structures')
 print(L.validate())
if __name__=='__main__':main()
