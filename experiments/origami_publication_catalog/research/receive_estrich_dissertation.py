"""Verify human-assisted dissertation identity without conflating it with ACS SI."""
import access_queue as A
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=A.read();r=next(x for x in rows if x['id']=='ACCESS-a556b23d8f')
 assert r['status']=='received'
 path=L.ROOT/r['file']['local_file']
 ev=evidence(path,r['url'],'PDF1-4 abstract,copyright and title/approval pages; PDF7-9 contents inspected. Nicole Ashley Estrich, Self-Assembly Properties of DNA Origami, Gold Nanostructures, and Diblock Compatibilizers, NCSU PhD2016, Thomas LaBean advisor. Scientific chapters and sequence tables not yet reviewed in this receipt step.')
 assert ev['sha256']==r['file']['sha256']
 status='identity_verified_as_Estrich2016_dissertation; scientific_source_review_pending'
 if r['file']['review_status']!=status:
  r['file']['review_status']=status
  r['events'].append(dict(at=A.now(),action='Title,author,institution,year verified against requested dissertation; related source,not ACS supplement. Original Downloads file untouched.'))
  A.save(rows)
 k='10.1021/acsnano.6b07291';p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['access']='ACS_SI_and_related_Estrich2016_dissertation_available; journal_main_pending'
 q='Human-assisted Estrich2016 dissertation received and identity verified. Review Chapter2 printed31-49,Chapter4 printed85-118,and AppendixA printed169-193 (PDF186-210) for Designs1,2A,2B; compare exact staple variants with ACS SI. Contents locate tables but do not establish complete sources.'
 if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 L.upsert('publication_reviews',p,'Receive and identify requested dissertation; preserve ACS SI distinction and review stage')
 for did in ['RDE0055','RDE0056']:
  d=next(x for x in L.read('design_evidence') if x['design_id']==did)
  for field in ['evidence','source_files']:
   if ev not in d[field]:d[field].append(ev)
  if q not in d['outstanding_checks']:d['outstanding_checks'].append(q)
  L.upsert('design_evidence',d,'Attach acquired related dissertation as pending source review,without design/source promotion')
 print(L.validate())

if __name__=='__main__':main()
