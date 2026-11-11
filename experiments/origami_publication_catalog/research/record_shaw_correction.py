"""Retain correction as a distinct publication and track corrected source references."""
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1038/s41565-019-0404-3';parent='10.1038/s41565-018-0336-3'
 ev=evidence(L.ROOT/'assets/research-20261105/shaw-antibody-correction.pdf','https://www.nature.com/articles/s41565-019-0404-3.pdf','PDF p.1, second correction block only; published 19 February2019')
 if not any(r['registry_key']==key for r in L.read('publication_reviews')):
  L.upsert('publication_reviews',{'registry_key':key,'registry_id':None,'doi':key,'title':'Publisher Correction: Binding to nanopatterned antigens is dominated by the spatial tolerance of antibodies','authors':['Alan Shaw','Ian T. Hoffecker','Ioanna Smyrlaki','Joao Rosa','Algirdas Grevys','Diane Bratlie','Inger Sandlie','Terje Einar Michaelsen','Jan Terje Andersen','Björn Högberg'],'canonical_work_id':'work:'+key,'canonical_work_status':'separate_correction_linked_to_parent','version_links':[{'relation':'corrects','target_key':parent,'evidence':ev}],'publication_type':['publisher_correction'],'date_evidence':{'date':'2019-02-19','source':ev,'primary_verified':True,'meaning':'Publisher displayed online date'},'review_stage':'fulltext_reviewed','relevance':'background_or_review','design_contributions':[],'catalog_eligibility':'excluded','access':'available','evidence':[ev],'rationale':'Complete correction states that SI references48–62 were omitted and an amended file uploaded. No new molecular design is presented. The shared PDF page contains a different correction in its first block; only the second block belongs to this DOI.','reviewer':'Codex primary correction inspection','run_id':'fnano-counterparts-2018','date':L.DATE,'unresolved_questions':['Verify presence of restored references in the retained SI version before certifying source completeness.'],'legacy_record':{},'revision_history':[]},'Retain distinct corrective publication and source-version implication')
 eid='corrects:'+key+':'+parent
 if not any(e['edge_id']==eid for e in L.read('discovery_edges')):
  L.upsert('discovery_edges',{'edge_id':eid,'source_key':key,'target_key':parent,'relation':'corrects','evidence_url':ev['url'],'local_file':ev['local_file'],'sha256':ev['sha256'],'locator':ev['locator'],'reconciliation_state':'explicit_publisher_correction_link','run_id':'fnano-counterparts-2018','date':L.DATE},'Record publisher-stated correction relationship')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0003')
 for k in [key,parent,'10.1038/s41467-018-03601-5']:
  if k not in b['input_keys']:b['input_keys'].append(k)
 b.update(after_counts=L.counts(),validation=[L.validate()],exclusion_audit={'sample':[key],'sampling_method':'Only final exclusion; 100% census audit, no random seed.','reviewer':'Same-agent second pass, not independent.','finding':'Re-read complete second correction block: missing SI references only. First unrelated correction on same page not attributed to this record.'})
 L.upsert('batches',b,'Include inspected candidate papers and correction in conference follow-up batch')
 print(L.validate())

if __name__=='__main__':main()
