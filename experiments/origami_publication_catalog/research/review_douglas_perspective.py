"""Manual Perspective review plus unfiltered publisher-deposited references."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1126/science.aam9541';rid='douglas-perspective-20261105';base=L.ROOT/'assets/research-20261105'
 meta=json.loads((base/'douglas-perspective-crossref.json').read_text())['message']
 assert meta['DOI']==key and meta['title']==['Bringing proteins into the fold']
 ev=evidence(base/'douglas-2017_Science_persp.txt','https://bionano.ucsf.edu/txt/2017_Science_persp.txt','Complete author-hosted text; reference list absent')
 me=evidence(base/'douglas-perspective-crossref.json','https://api.crossref.org/works/'+key,'DOI, title, author, publication date and all11 deposited references')
 p=next((p for p in L.read('publication_reviews') if p['registry_key']==key),None)
 if p is None:p=dict(registry_key=key,registry_id=None,doi=key,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',legacy_record={},version_links=[])
 p.update(title='Bringing proteins into the fold',authors=['Shawn M. Douglas'],publication_type=['journal_commentary'],date_evidence={'date':'2017-03-24','source':me,'primary_verified':False,'meaning':'Crossref publisher-deposited publication date'},review_stage='fulltext_reviewed',relevance='background_or_review',design_contributions=[],catalog_eligibility='unresolved',evidence=[ev,me],rationale='Author-hosted Perspective explains Praetorius and Dietz protein-stapled DNA folding and contrasts prior DNA/RNA approaches. No own experimental design or Methods is presented in the inspected text. Its reference list is absent; all11 deposited Crossref references are retained separately. Final catalog exclusion awaits complete publisher-layout context.',unresolved_questions=['Inspect complete published pages and reference list; reconcile primary protein-stapled DNA work separately.'],reviewer='Codex complete author-hosted text inspection',access='partial',run_id=rid,date=L.DATE)
 L.upsert('publication_reviews',p,'Review Perspective with explicit text-completeness limitation')
 known={r['registry_key'] for r in L.read('publication_reviews')}
 for i,r in enumerate(meta['reference'],1):
  target=r.get('DOI','').lower() or 'unresolved-reference:'+key+':'+str(i)
  L.upsert('discovery_edges',dict(edge_id='crossref-ref:'+key+':'+str(i),source_key=key,target_key=target,relation='backward_citation',evidence_url=me['url'],local_file=me['local_file'],sha256=me['sha256'],locator='message.reference['+str(i-1)+']',target_metadata=r,reconciliation_state='matched_explicit_doi' if target in known else 'pending_identity_and_scope',run_id=rid,date=L.DATE),'Retain every deposited reference without keyword filtering')
 for e in L.read('discovery_edges'):
  if e.get('run_id')=='author-douglas-20261105' and any('28336623' in u for u in e['target_metadata']['links']):
   e.update(target_key=key,identity_evidence=me,reconciliation_state='matched_author_title_and_crossref; PMID_provider_confirmation_pending');L.upsert('discovery_edges',e,'Reconcile matching author-hosted Perspective and deposited Crossref identity')
 L.upsert('discovery_runs',dict(run_id=rid,route='backward_citations',query_or_seed=key,source_url=me['url'],date=L.DATE,pagination={'complete':True},provider_total=len(meta['reference']),retrieved_count=len(meta['reference']),deduplicated_additions=1,additions_unit='Perspective publication record; references remain leads',evidence=[ev,me],failures=[],closure_state='exhausted',closure_scope='All11 references in this Crossref deposit only; publisher list completeness and target screening pending',checkpoint='Perspective background evidence recorded; no final catalog exclusion'), 'Save bounded reference enumeration and substantive review')
 print(L.validate())
if __name__=='__main__':main()
