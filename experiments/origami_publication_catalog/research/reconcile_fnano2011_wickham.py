"""Keep conference, thesis and journal candidates distinct."""
import ledger as L
from review_batch_0001 import evidence

def main():
 path=L.HERE/'fnano2011_wickham_primary.json'
 url='https://www.physics.ox.ac.uk/sites/default/files/ShelleyWickham2011.pdf'
 ev=evidence(path,url,'Oxford-hosted thesis title page/abstract indexed excerpt; Hilary Term2011')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 key='thesis:oxford:wickham:2011'
 if key not in pubs:
  p=dict(registry_key=key,registry_id=None,doi='',title='DNA Origami - a substrate for the study of molecular motors',authors=['Shelley Wickham'],canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['thesis'],date_evidence={'date':'2011','source':ev,'primary_verified':True,'meaning':'Thesis Hilary Term2011; exact public availability day unresolved'},review_stage='metadata_screened',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Oxford thesis abstract describes rectangular origami platforms for a burnt-bridges motor, a two-foot motor, branching-track control, and F1-ATPase attachment/rotation. These are reported design/application families, not an audited count of distinct cores. Full chapters, sequence appendices and publication overlaps remain to be inspected.',reviewer='Codex primary abstract inspection',run_id='fnano-2011',date=L.DATE,unresolved_questions=['Inspect thesis chapters/appendices and exact core/variant sources.','Reconcile conference and journal coverage without merging distinct publication types.'],legacy_record={})
  L.upsert('publication_reviews',p,'Retain primary-supported thesis lead')
 source='conference:fnano2011:6540265289c29f'
 for target in [key,'10.1038/nnano.2010.284','10.1038/nnano.2011.253']:
  L.upsert('discovery_edges',dict(edge_id='fnano2011:wickham:candidate:'+target,source_key=source,target_key=target,relation='possible_counterpart',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator='Conference title/topic and author versus primary thesis/journal metadata; exact overlap unverified',reconciliation_state='counterpart_scope_pending',run_id='fnano-2011',date=L.DATE),'Preserve candidate relationships, not identity merges')
 print(L.validate())
if __name__=='__main__':main()
