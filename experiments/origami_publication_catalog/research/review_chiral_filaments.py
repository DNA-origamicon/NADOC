"""Primary filament construction evidence; distinguish particles from bulk phases."""
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1038/nmat4909';base=L.ROOT/'assets/research-20261105'
 ev=evidence(base/'siavashpouri-2017-main.pdf','https://dogiclab.physics.ucsb.edu/publications/PDFs/molecular_engineering.pdf','PDF pp1–3 filament dimensions and twist variants; p9 Methods design/folding/purification/labeling; p10 optical-handle description; original publisher-layout author-hosted copy')
 si=evidence(base/'siavashpouri-2017-si.pdf','https://static-content.springer.com/esm/art%3A10.1038%2Fnmat4909/MediaObjects/41563_2017_BFnmat4909_MOESM1_ESM.pdf','Entire2-page supplement: descriptions of Movies1–8 only, no sequence table or CAD diagram')
 q=['Locate exact native CAD/staple sources for each filament and twist variant;177 staple count is not proof of sequence completeness.','Verify lattice/crossover grid for6-,8-,10-helix designs before catalog acceptance.','Resolve parent-design reuse versus new routing through cited design methods and original sources.','Reconcile arXiv1705.08944 with journal using primary version metadata; retain separate dates/records.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==doi)
 p.update(review_stage='design_sources_reviewed',design_contributions=['new_design','modified_design'],evidence=p['evidence']+[e for e in [ev,si] if e not in p['evidence']],rationale='Author-hosted primary article identifies7560nt scaffold and177 staples for straight6HB; polyT tails and scaffold loops suppress end aggregation. Four6HB twist variants use insertions/deletions; separate8HB and10HB rods change aspect ratio. Bulk phases, filament mixtures, virus controls and optical-trap handles are not additional origami cores. Downloaded SI contains movie captions only.',unresolved_questions=q,reviewer='Codex primary design/Methods section and full2-page SI inspection',access='partial',run_id='DISC0005-chiral-sources',date=L.DATE)
 L.upsert('publication_reviews',p,'Upgrade from abstract to inspectable construction evidence without claiming complete sources')
 specs=[('RDE0015','Six-helix filament family','420nm contour length,6nm diameter;7560nt scaffold;177 staples averaging42nt (range21–49nt). Straight s-6h, rh-6h, lh-6h and2x-lh-6h; predicted twists0,+360,-360,-720 degrees, not measured atomic configurations.'),('RDE0016','Eight-helix filament','310nm contour length,7nm diameter; exact variant-specific staple/routing composition pending.'),('RDE0017','Ten-helix filament','250nm contour length,8nm diameter; exact variant-specific staple/routing composition pending.')]
 for did,name,composition in specs:
  old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or old['publication_keys']==[doi]
  L.upsert('design_evidence',dict(design_id=did,publication_keys=[doi],named_objects=[name],core_variant_composition=composition,lattice_decision='unresolved: helix count alone does not certify lattice',catalog_eligibility='unresolved',source_completeness='not_verified',source_files=[ev,si],evidence=[ev,si],outstanding_checks=q,relationships=[],variant_links=[],legacy_record={},review_run='DISC0005-chiral-sources',date=L.DATE),'Separate filament core families from material phases and label conditions')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0005');a='Reviewed author-hosted chiral-filament primary Methods/variant sections and complete movie-only SI; recorded separate6HB/8HB/10HB groups.'
 if a not in b['completed_actions']:b['completed_actions'].append(a)
 b.update(status='completed',after_counts=L.counts(),validation=[L.validate()],next_queue=['Resume25-record screening rotation with low-keyword and broad strata.','Chiral native CAD/staples and arXiv version metadata; rotary SI alternate access.','FNANO2014 and earlier programs/abstracts; unmatched Dietz leads and citation recursion.'])
 L.upsert('batches',b,'Close this bounded discovery batch with explicit unresolved follow-up queue; goal/routes remain open');print(L.validate())
if __name__=='__main__':main()
