"""Evidence-based disposition of the rotated RecA record; no title-only exclusion."""
import ledger as L
from review_batch_0001 import evidence

def main():
 p=next(p for p in L.read('publication_reviews') if p['registry_key']=='10.1103/physreve.87.032702')
 ev=evidence(L.ROOT/'assets/research-20261105/vlassakis-2013-main.html','https://pmc.ncbi.nlm.nih.gov/articles/PMC4973255/','Abstract; Results and Discussion II.A opening comparison with origami; entire Conclusion III')
 p.update(review_stage='fulltext_reviewed',relevance='not_origami',publication_type=['journal_article'],design_contributions=[],catalog_eligibility='excluded',access='partial',evidence=[ev],rationale='Analytical model of stress distribution in RecA-bound dsDNA during homology recognition/strand exchange. Results II.A mentions origami only as a contrasting ssDNA-pairing thermodynamic example. Conclusion enumerates RecA homology-recognition predictions; no origami core, modification or design reuse is presented in these inspected sections. Exclusion is based on primary content, not title or absent keywords.',unresolved_questions=['Bibliography and forward citations remain discovery routes; exclusion applies to this publication, not its citation neighborhood.'],reviewer='Codex primary HTML named-section inspection',run_id='B0009',date=L.DATE)
 L.upsert('publication_reviews',p,'Inspect low-keyword original research and audit reason for non-origami exclusion')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0009')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 reviewed=[k for k in b['input_keys'] if pubs[k].get('run_id')=='B0009' and pubs[k]['review_stage']!='unreviewed']
 b.setdefault('completed_actions',[]).append('Reviewed RecA primary Results II.A and Conclusion; origami is a comparison, not an authored/reused design. Korevaar PMC retrieval was a browser challenge and institutional PDF returned404; both logged as failed.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review four remaining B0009 records: rsif.2012.0740; pnas.1310092110; Albany abstract144; reconfigurable tubules435601.','Continue FNANO2014 enumeration and recursive citation/author discovery.'])
 L.upsert('batches',b,'Checkpoint21/25 first reviews, retain follow-up obligations')
 import json
 L.atomic(L.HERE/'batch_0009_rotation_audit.json',json.dumps(dict(batch_id='B0009',reviewed_count=len(reviewed),input_count=len(b['input_keys']),remaining_keys=[k for k in b['input_keys'] if k not in reviewed],validation=L.validate(),counts=L.counts()),indent=2)+'\n')
 print(L.validate())
if __name__=='__main__':main()
