"""Resolve a printed DOI typo using retained primary publisher metadata."""
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1038/nmat4909';ev=evidence(L.ROOT/'assets/research-20261105/siavashpouri-2017-canonical.html','https://www.nature.com/articles/nmat4909','citation_title/doi/author/online_date metadata; publisher abstract; full article subscription preview')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==doi)
 p.update(review_stage='metadata_screened',relevance='design_bearing',design_contributions=['modified_design','uncertain'],access='partial',catalog_eligibility='unresolved',evidence=[ev],date_evidence={'date':'2017-05-22','source':ev,'primary_verified':True,'meaning':'Publisher online date; issue2017-08 separate'},rationale='Publisher abstract explicitly reports DNA-origami filaments with controlled particle geometry assembled into cholesteric phases, ribbons and membranes. Full design/variant routing and source completeness not reviewed.',unresolved_questions=['Inspect main Methods/Results and SI to identify filament cores, geometry variants and original-template reuse.','Keep particle design distinct from bulk colloidal assembly and material phases.','Verify lattice eligibility and complete staple/source sets.'],reviewer='Codex primary publisher abstract and bibliographic metadata',run_id='DISC0005-dietz-reconcile',date=L.DATE)
 L.upsert('publication_reviews',p,'Verify primary identity/date and retain abstract-level design evidence')
 e=next(e for e in L.read('discovery_edges') if e.get('run_id')=='author-dietz-20261105' and e.get('target_metadata',{}).get('printed_number')=='47')
 e.update(target_key=doi,reconciliation_state='matched_primary_title_authors_doi; laboratory_typo_preserved',identity_evidence=ev,identity_note='Lab text prints10.1138/nmat4909; primary publisher explicitly states10.1038/nmat4909. Original target metadata retained unchanged. Old lab hyperlink returned Browse Articles index, not article; acquisition failure recorded.')
 L.upsert('discovery_edges',e,'Resolve malformed printed DOI against primary source without silently editing lab evidence')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0005');a='Resolved Dietz entry47 DOI typo using primary publisher metadata; screened chiral-filament abstract and retained source gaps.'
 if a not in b['completed_actions']:b['completed_actions'].append(a)
 for field in ['input_keys','unresolved_keys']:
  if doi not in b[field]:b[field].append(doi)
 b.update(after_counts=L.counts(),validation=[L.validate()]);L.upsert('batches',b,'Save primary identity correction and screening');print(L.validate())
if __name__=='__main__':main()
