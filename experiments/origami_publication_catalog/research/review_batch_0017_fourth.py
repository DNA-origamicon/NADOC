"""Resolve a patent identity and retain targeted design evidence with translation limits."""
import ledger as L
from review_batch_0001 import evidence

def main():
 k='epmc:1842';rid='B0017';a=L.ROOT/'assets/research-20261105'
 ev=evidence(a/'cn101050228a.html','https://patents.google.com/patent/CN101050228A/en','Google Patents reproduction with Chinese text and machine English translation: identity,background,Figure1-4 descriptions,Example1 andExample2 inspected; portions oflater examples encountered,not full review. Numeric line-length string visibly concatenated in translation; not a routing source.')
 cover=evidence(a/'cn101050228a.pdf','https://patentimages.storage.googleapis.com/6a/99/80/7fe11be7ec6f16/CN101050228A.pdf','16-page original Chinese patent PDF; coverPDF1 visually inspected: publication2007-10-10,filing2007-03-22,application200710038297.0,inventors include钱璐璐. RemainingPDF not independently read.')
 note='Identity resolved by exact title and patent cover to CN101050228A. Publication2007-10-10 differs from filing2007-03-22 used by legacy registry. Targeted translatedExample1 reports M13mp18 China-map scaffold,219staples+8remainder23mers+2Taiwan-link32mers=229oligos, BsrBI preparation,150x120x2nm and59%well-formed of125. This strongly matches existingRDE0044/Qian2006 family but exact source identity/variant comparison remains open. Example2 describes an inductor-shaped scaffold and silver metallization; do not treat every patent embodiment as experimentally demonstrated. Narrow lattice/source eligibility unresolved. Machine translation concatenates numerical routing lengths; no reconstruction or complete sequence certification.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(publication_type='patent_application',patent_publication_number='CN101050228A',review_stage='fulltext_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='original_PDF_and_translated_HTML_available',rationale=note,reviewer='Codex targeted patent text review and original cover verification',run_id=rid,date=L.DATE,unresolved_questions=['Compare original Chinese description,figures and source tables with Qian2006 China-map paper; do not merge canonical works or certify source identity from matching counts.','Read remaining patent embodiments and claims; distinguish proposed,method-described and experimentally evidenced inductor variants.','Retain/reconcile full patent citations and family links; translated numeric routing string is not reliable.'])
 for e in [ev,cover]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence']=dict(date='2007-10-10',primary_verified=True,source=cover,meaning='Original patent cover publication date;2007-03-22 is filing date.')
 L.upsert('publication_reviews',p,'Resolve patent identity and filing/publication date; retain targeted translation limits')
 d=next(x for x in L.read('design_evidence') if x['design_id']=='RDE0044')
 for e in [ev,cover]:
  if e not in d['evidence']:d['evidence'].append(e)
 n='Related patent CN101050228A Example1 has matching219+8+2oligos,BsrBI,map dimensions andAFM yield; exact publication/design source relationship remains pending. Evidence is targeted translated description plus original cover, not full patent source audit.'
 if n not in d['core_variant_composition']:d['core_variant_composition']+=' '+n
 q='Compare CN101050228A Example1 original Chinese text/figures with Qian2006 sources; inductor embodiments are not automatically part of this China-map group.'
 if q not in d['outstanding_checks']:d['outstanding_checks'].append(q)
 L.upsert('design_evidence',d,'Attach candidate patent counterpart evidence without adding a duplicate design group')
 L.upsert('discovery_edges',dict(edge_id='B0017:cn101050228a:qian2006',source_key=k,target_key='10.1007/s11434-006-2223-9',relation='possible_publication_counterpart',citation='CN101050228A Example1 China-map design compared with existing Qian2006 source notes',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Example1; existingRDE0044 evidence',reconciliation_state='pending_exact_variant_and_source_verification',run_id=rid,date=L.DATE),'Preserve candidate counterpart without canonical merge')
 b=next(x for x in L.read('batches') if x['batch_id']==rid)
 action='Processed4of25:3substantive reviews plus1metadata-only. epmc:1842resolvedCN101050228A;originalcoverdate corrected;China-map counterpart andinductor sourcefollowups retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Nextbalancedinput epmc:1391;21untouchedB0017inputs.','CN101050228A original16pages/remainingembodiments/citations; candidateQian2006match,no sourcecertification.','RothemundSI/citations; EBSAactualPDF; priorityauthorroutes;FNANOdeferred.'])
 L.upsert('batches',b,'Save4of25processed with patent evidence limits')
 print(L.validate())

if __name__=='__main__':main()
