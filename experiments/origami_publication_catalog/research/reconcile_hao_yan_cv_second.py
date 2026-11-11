"""Resolve two CV identities; preserve a mixed-edition citation as ambiguous."""
import json
import ledger as L
from review_batch_0001 import evidence
def main():
 rid='author-hao-yan-asu-cv'
 ev=evidence(L.HERE/'hao_yan_cv_reconciliation_primary3.json','https://pubmed.ncbi.nlm.nih.gov/23852715/','Primary title,authors,volume/pages/date for entries130/91; layered-crossover abstract and metadata')
 scope=evidence(L.HERE/'hao_yan_cv_scope_primary3.json','https://onlinelibrary.wiley.com/doi/abs/10.1002/anie.201302177','Graphical abstract, first-publication date and SI link; cage PMC access challenge')
 cases=[(130,'10.1002/anie.201302177','Title,five authors,International volume52 and9031–9034pages match. Alternate German-edition identity still pending explicit publisher linkage.'),(91,'10.1002/anie.201006818','Title,International volume50 and2041–2044pages match. CV omits coauthor Erica L Jacovetty; primary full author list retained in evidence. Alternate edition not merged.')]
 edges={e['edge_id']:e for e in L.read('discovery_edges')}
 for n,key,note in cases:
  edge=edges[rid+':'+str(n)];edge.update(target_key=key,reconciliation_state='bibliographic_identity_verified_design_scope_pending',reconciliation_note=note,identity_evidence=ev)
  L.upsert('discovery_edges',edge,'Resolve title/author/volume/page identity without assuming edition equivalence')
 edge=edges[rid+':157'];edge.update(reconciliation_note='CV says International Edition but gives German volume128/pages13024–13027; International primary record is55:12832–12835. Same title/authors support candidates, but edition remains ambiguous.',reconciliation_state='mixed_edition_citation_pending',identity_evidence=ev)
 L.upsert('discovery_edges',edge,'Preserve mixed-edition citation rather than force a target')
 for key,rel,note in [
 ('10.1002/anie.201302177','design_bearing','Primary graphical abstract reports construction of2D/3D origami using modified parallel double-crossover tiles and unidirectional scaffold routing. Exact geometries, scaffold/staple maps and lattice eligibility require main/SI review. Publisher lists25.1MB SI, not yet acquired. First online14July2013 is explicit.'),
 ('10.1002/anie.201006818','uncertain','Primary bibliographic identity verified against CV including missing coauthor. Full article access returned browser challenge; title alone not used to certify design contents or source availability. Main/SI inspection remains necessary.'),
 ('10.1002/anie.201607050','design_bearing','Primary abstract reports layered-crossovers for multilayer wireframe origami: four two-layer parallelogram versions, three-layer triangular-cavity structure and9-/15-layer square lattices. Counts describe reported examples, not independently validated sources. Exact variants and per-object narrow eligibility require main/SI inspection; do not infer filled geometry from square-lattice wording.')]:
  p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
  for e in [ev,scope]:
   if e not in p['evidence']:p['evidence'].append(e)
  assert p['review_stage'] in ['unreviewed','metadata_screened'], 'Do not replace deeper review'
  p.update(review_stage='metadata_screened',relevance=rel,publication_type=['journal_article'],design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,reviewer='Codex primary bibliographic and abstract inspection',run_id=rid,date=L.DATE,unresolved_questions=['Acquire main/SI and verify exact design/source scope.','Resolve alternate editions with explicit evidence; recurse citations and author histories.'])
  L.upsert('publication_reviews',p,'Record primary abstract or limited identity depth')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==rid)
 for e in [ev,scope]:
  if e not in run['evidence']:run['evidence'].append(e)
 run['checkpoint']='Five of239 CV entries identity-resolved:167,88,159,130,91;234 pending including mixed-edition157. Alternate edition candidates remain separate until explicitly linked.'
 L.upsert('discovery_runs',run,'Checkpoint five reconciled entries and mixed-edition ambiguity')
 out=dict(cv_entries=239,resolved_entries=[167,88,159,130,91],remaining_entries=234,mixed_edition_entry=157,new_edition_merges=0,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'hao_yan_cv_reconciliation_second_audit.json',json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
