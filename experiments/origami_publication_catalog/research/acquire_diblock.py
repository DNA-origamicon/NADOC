"""Resume public SI acquisition; verify identity without claiming design review."""
import hashlib,json,subprocess
import ledger as L
from acquire_sources import fetch
from review_batch_0001 import evidence

def main():
 key='10.1021/acsnano.6b07291';before=L.counts();base=L.ROOT/'assets/research-20261105'
 fetch('https://api.figshare.com/v2/articles?resource_doi=10.1021%2Facsnano.6b07291&page_size=100','diblock-figshare-search.json')
 fetch('https://api.figshare.com/v2/articles/4524902','diblock-figshare-4524902.json')
 meta=json.loads((base/'diblock-figshare-4524902.json').read_text());assert meta['resource_doi']==key and len(meta['files'])==1
 f=meta['files'][0];assert f['name']=='nn6b07291_si_001.pdf'
 item=fetch(f['download_url'],'diblock-si.pdf');assert item['status']=='available'
 path=base/'diblock-si.pdf';assert path.stat().st_size==f['size'] and hashlib.md5(path.read_bytes()).hexdigest()==f['computed_md5']
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode()
 assert 'Nicole A. Estrich' in text.split('\f')[0] and 'Tetrahedral DNA Origami Design' in text
 ev=evidence(path,f['download_url'],'SI cover title/authors verified; S2 identifies tetrahedral origami routing and staple table. Full design/table review pending.')
 me=evidence(base/'diblock-figshare-4524902.json','https://api.figshare.com/v2/articles/4524902','Parent DOI and sole file identity; size and provider MD5 independently checked.')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [ev,me]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['access']='SI_available; main_pending'
 qs=['Review all diblock SI pages, staple tables and routing figures; resolve tetrahedral design variants and catalog geometry eligibility from evidence.','Acquire diblock main text using public author/repository routes and reconcile its references.','Continue priority author histories/citations and full-backlog rotation; FNANO remains deferred.']
 p['unresolved_questions']=list(dict.fromkeys(p.get('unresolved_questions',[])+qs))
 L.upsert('publication_reviews',p,'Acquire verified public SI; retain existing unreviewed classification pending scientific inspection')
 L.upsert('batches',dict(batch_id='AUTHOR0029',date=L.DATE,status='completed',input_keys=[key],selection='Low-keyword LaBean lead source acquisition',before_counts=before,after_counts=L.counts(),completed_actions=['Downloaded sole publisher Figshare SI through paced resumable acquisition.','Verified parent DOI, cover identity, size and provider MD5; no human assistance needed.','Retained unreviewed scientific classification and queued full table/geometry inspection.'],validation=[L.validate()],unresolved_keys=[key],next_queue=qs),'Save acquisition handoff without promoting unreviewed designs')
 print(L.validate())
if __name__=='__main__':main()
