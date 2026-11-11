"""Liquid-interface review and metadata-only news access; uncapped reference retention."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.3762/bjnano.10.153';rid='B0016';path=L.ROOT/'assets/sources/pre2020-expansion/PMC6693411.xml';r=E.parse(path).getroot()
 ev=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6693411/fullTextXML','Reviewtype; liquid-interface characteristics section2.1, origami paragraph/Figure8 in2.2, Conclusions and references144/219 inspected. Remaining broad materials review not fully read.')
 note='Background review of liquid-interface materials. The origami discussion attributes90x65nm theoretical rectangle pieces complexed with cationic lipids and assembled by repeated air-water monolayer compression/expansion to Yonamine2016ref219(10.1039/c6cp01586g). Short-side dangling chains mediate proposed inter-piece links; this is a report of earlier work, not a new origami experiment in the review. Figure8 credits AFM image reproduction from2019ref144(10.1021/acs.langmuir.8b01434), distinct from original researchref219. Preserve both citation paths; do not assume citation error or identical original source. Background relevance and narrow catalog exclusion; no new designgroup.294references retained as leads, not294relevant papers.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='background_or_review',design_contributions=[],catalog_eligibility='excluded',access='main_XML_available',rationale=note,reviewer='Codex targeted review-scope and origami attribution audit',run_id=rid,date=L.DATE,unresolved_questions=['Inspect Yonamine2016primary source and its staple/lattice/parent evidence.','Reconcile Figure8intermediate source ref144 separately from original researchref219.','Remaining broad review sections and294bibliography targets not fully reviewed.'])
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2019-07-30',primary_verified=False,source=ev,meaning='XMLpub-date2019-07-30 without epub/ppub subtype; pre2020supported, exactfirstonline not independently reconciled.')
 L.upsert('publication_reviews',p,'Review-scope exclusion with explicit original and intermediate source paths')
 # Append new reference rows in one atomic write, retaining all existing rows and histories.
 edges=L.read('discovery_edges');known={x['edge_id']:x for x in edges};refs=r.findall('.//ref-list/ref');assert len(refs)==294
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]');dl=ref.find('.//ext-link[@ext-link-type="doi"]')
  target=(doi.text if doi is not None else dl.get('{http://www.w3.org/1999/xlink}href') if dl is not None else 'citation:bjnano-review:'+n)
  row=dict(edge_id='B0016:bjnano-review:'+n,source_key=k,target_key=target.lower(),relation='cites',citation=' '.join(ref.itertext()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE,revision_history=[])
  if row['edge_id'] in known:assert known[row['edge_id']]==row
  else:edges.append(row)
 L.save('discovery_edges',edges)
 nk='10.1016/s1369-7021(06)71752-7';np=next(p for p in L.read('publication_reviews') if p['registry_key']==nk)
 ne=evidence(L.ROOT/'assets/research-20261105/solarnews2006.xml','https://api.elsevier.com/content/article/PII:S1369702106717527?httpAccept=text/xml','PublisherAPI coredata only: DOI/title/MaterialsToday, coverDate2006-12-31, openaccess=true; no article body or references returned.')
 np.update(review_stage='metadata_screened',access='publisher_metadata_only; fulltext_pending',rationale='PublisherAPI confirms identity and open-access flag but returns only coredata, despite full-text-retrieval wrapper. No body/abstract/reference content acquired. Title and single-page bibliographic record suggest news; publication type and design relevance remain unverified. Do not infer missing CUentitlement from ScienceDirect403.',reviewer='Codex publisher response inspection',run_id=rid,date=L.DATE,unresolved_questions=['Acquire actual news body, verify publicationtype and identify underlying original research; metadata response does not resolve design relevance.'])
 if ne not in np['evidence']:np['evidence'].append(ne)
 np['date_evidence'].update(primary_verified=False,publisher_cover_date='2006-12-31',source=ne,meaning='December2006cover date, not proof of exactfirst-online day')
 L.upsert('publication_reviews',np,'Record metadata-only publisher response without fulltext promotion')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Processed22of25inputs=20substantive reviews+2metadataonly. Liquid-interface review excluded with294refs retained;2006solarnews publisherAPI provides coredata only, content unresolved.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' Liquid-interface review: origami paragraph explicitly cites prior Yonamine2016; Figure8reproduction credit separate2019source.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining3firstpassinputs:10.3791/58771,10.4049/jimmunol.202.supp.130.13,10.5539/jmsr.v8n4p14.','Next JoVEpolycation-coating protocol; compare priorPonnuswamysourcegroup.','Follow Yonamine2016 and2019intermediate review; bothmetadataonly accessgaps(Talks/news) stillopen.']);L.upsert('batches',b,'Save22of25processed with explicit2metadata-only inputs');print(L.validate())
if __name__=='__main__':main()
