"""Uncapped enumeration of the deposited Crossref reference list, not fulltext review."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1039/c9nh00529c';rid='backward-castro-review';path=L.ROOT/'assets/research-20261105/castro-review-crossref.json'
 m=json.loads(path.read_text())['message'];refs=m['reference'];assert len(refs)==m['reference-count']==178
 known={p['doi']:p['registry_key'] for p in L.read('publication_reviews') if p['doi']};ev=evidence(path,'https://api.crossref.org/works/10.1039/C9NH00529C','All178 deposited reference objects; matches provider reference-count; not verified against article bibliography')
 targets=set();matched=0
 for i,r in enumerate(refs,1):
  targetdoi=r.get('DOI','').lower();target=known.get(targetdoi,targetdoi or 'reference:'+doi+':'+str(i));targets.add(target);matched+=targetdoi in known
  L.upsert('discovery_edges',dict(edge_id=rid+':'+str(i),source_key=doi,target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Crossref message.reference['+str(i-1)+']; '+r.get('key',''),target_doi=targetdoi,target_year=r.get('year'),raw_reference=r,doi_asserted_by=r.get('doi-asserted-by'),reconciliation_state='matched_registry_doi' if targetdoi in known else 'pending_identity_and_scope',run_id=rid,date=L.DATE),'Retain every deposited reference regardless of title/topic')
 run=dict(run_id=rid,route='backward_citations',query_or_seed=[doi],source_url=ev['url'],date=L.DATE,pagination={'returned':len(refs),'reported_reference_count':m['reference-count'],'complete_for_deposit':True,'verified_against_article':False},provider_total=m['reference-count'],retrieved_count=len(refs),unique_targets=len(targets),deduplicated_additions=len(targets-set(known.values())),additions_unit='Unmatched reference targets, not new eligible publications',evidence=[ev],failures=[{'resource':'https://pubs.rsc.org/en/content/articlehtml/2020/nh/c9nh00529c','methods':['paced downloader','web open'],'status':'HTTP403; fulltext not acquired'}],closure_state='in_progress',checkpoint='All178 Crossref deposited references retained; verify against article when accessible, resolve unmatched targets and recurse eligible papers. No keyword filtering and no field saturation claim.')
 L.upsert('discovery_runs',run,'Save deposited bibliography extraction and primary fulltext gap')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==doi)
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_conflicts']=[{'source':ev,'observed':m.get('published-online'),'resolution':'Crossref year-only2020 conflicts with publisher explicit first-published2019-10-15; retain publisher date.'}]
 q='Fulltext RSC HTML requests returned403; deposited references acquired via Crossref, not a fulltext review.'
 if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 L.upsert('publication_reviews',p,'Record metadata date conflict and access remedy without upgrading review stage')
 audit=dict(deposited_references=len(refs),doi_bearing=sum(bool(r.get('DOI')) for r in refs),no_doi=sum(not r.get('DOI') for r in refs),matched_reference_occurrences=matched,unique_targets=len(targets),unmatched_unique_targets=len(targets-set(known.values())),validation=L.validate())
 L.atomic(L.HERE/'castro_review_reference_audit.json',json.dumps(audit,indent=2)+'\n');print(audit)
if __name__=='__main__':main()
