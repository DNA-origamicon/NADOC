"""Primary review text and explicit unsuccessful access checks."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.3934/matersci.2015.4.448';p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 ev=evidence(L.ROOT/'assets/research-20261105/wang2015-epigenetic-nanopore.pdf','https://www.aimspress.com/aimspress-data/aimsmates/2015/4/PDF/201504448.pdf','Header, abstract, section1.2 nanopore overview and reference31')
 web=evidence(L.HERE/'batch_0015_rotation_primary.json','https://www.aimspress.com/article/doi/10.3934/matersci.2015.4.448','Publisher review designation/abstract/date and reference31; also records PMC/JoVE browser challenges')
 for e in [ev,web]:
  if e not in p['evidence']:p['evidence'].append(e)
 p.update(title=p['legacy_record']['publication'],publication_type=['review'],review_stage='fulltext_reviewed',relevance='background_or_review',catalog_eligibility='unresolved',access='available',rationale='Primary PDF identifies a review of nanopore epigenetic detection. Inspected abstract and section1.2 discuss origami nanopores as prior hybrid-pore work, citing Bell et al.2012 ref31; no new origami design established in these sections. Review type corrects generic legacy research-article labeling. PDF header says published16November2015, publisher landing page16December2015; preserve date conflict pending reconciliation. Remaining sections and full bibliography not exhaustively reviewed.',unresolved_questions=['Resolve November/December publication-date conflict.','Finish review text and full bibliography; follow Bell nanopore citation and other relevant leads.'],reviewer='Codex primary PDF header/abstract/section1.2/ref31 inspection',run_id='B0015',date=L.DATE)
 L.upsert('publication_reviews',p,'Record review relevance and conflicting primary publication dates')
 L.upsert('discovery_edges',dict(edge_id='B0015:wang:ref31',source_key=key,target_key='10.1021/nl204098n',relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Section1.2 and reference31',reconciliation_state='pending',run_id='B0015',date=L.DATE),'Preserve inspected backward citation')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('First rotating review saved: Wang nanopore review;16of25. JoVE remains unreviewed after browser checks and author-URL404; unrelated narrow search results not evidence.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Find verified public JoVE52486 full text; continue other9unreviewed rotating inputs','FNANO2010,234CV identities and source/citation followups'])
 L.upsert('batches',b,'Save16of25 progress and explicit access limits')
 L.atomic(L.HERE/'batch_0015_rotation_first_audit.json',json.dumps(dict(reviewed_keys=[key],first_pass_count=16,input_count=25,access_failures=['JoVE PDF browser check','PMC4542500/6436813 browser checks','Guessed author2015.SST.jove.pdf URL404'],irrelevant_search='batch_0015_jove_metadata.json returned unrelated records and is not classification evidence',validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
