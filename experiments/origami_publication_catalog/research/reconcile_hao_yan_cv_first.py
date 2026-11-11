"""Three manually checked CV identities; retain raw citations and edition records."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 runid='author-hao-yan-asu-cv'
 e1=evidence(L.HERE/'hao_yan_cv_reconciliation_primary1.json','https://pubmed.ncbi.nlm.nih.gov/29064489/','Primary PubMed title/authors/DOI/date; author-hosted cuboid article header explicitly lists both edition DOIs')
 e2=evidence(L.HERE/'hao_yan_cv_reconciliation_primary2.json','https://pubs.acs.org/doi/10.1021/ja106292x','Publisher title/authors,volume132,pages13545–13552,online8September2010')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 cases=[(167,'10.1038/nchem.2852',e1,'CV prints nchem.20405; primary title and four authors identify nchem.2852. Raw CV retained, DOI discrepancy recorded. Exact publication identity reconciled; no design claim.'),(88,'10.1021/ja106292x',e2,'CV volume138 conflicts with primary volume132. Title,author list,year andpages agree. Existing source review preserved.'),(159,'10.1002/anie.201610133',e1,'CV title/authors identify cuboid vesicles article. Published article header explicitly pairs International anie.201610133 with German ange.201610133; CV volume156 conflicts with International56. Preserve both edition records and their date evidence.')]
 edges={e['edge_id']:e for e in L.read('discovery_edges')}
 for n,target,ev,note in cases:
  edge=edges[runid+':'+str(n)]
  edge.update(target_key=target,reconciliation_state='bibliographic_identity_verified_design_scope_pending',reconciliation_note=note,identity_evidence=ev)
  L.upsert('discovery_edges',edge,'Resolve CV lead against primary bibliographic evidence; original pending target retained in history')
  p=pubs[target]
  if ev not in p['evidence']:p['evidence'].append(ev)
  notes=p.setdefault('bibliographic_reconciliation_notes',[])
  if note not in notes:notes.append(note)
  if n==167:
   p.update(review_stage='metadata_screened',relevance='background_or_review',publication_type=['review'],access='partial',rationale='Primary PubMed record identifies this as a review of programmable nucleic-acid circuitry. Main design attributions and complete bibliography remain uninspected; CV DOI discrepancy resolved by title/authors.',reviewer='Codex primary metadata identity check',run_id=runid,date=L.DATE)
   p['date_evidence']={'date':'2017-09-25','meaning':'Primary PubMed Epub date, distinct from November issue','source':ev,'primary_verified':True}
  L.upsert('publication_reviews',p,'Attach primary CV identity resolution without overwriting existing source review')
 # Edition equivalence is explicit in the published article header, not inferred from DOI prefixes.
 a='10.1002/anie.201610133';g='10.1002/ange.201610133'
 ev=evidence(L.HERE/'hao_yan_cv_reconciliation_primary1.json','https://liuds.chem.tsinghua.edu.cn/research/papers/fga3.pdf','Published article first-page header: International Edition and German Edition DOI pair')
 for key,other in [(a,g),(g,a)]:
  p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
  link={'relation':'alternate_journal_edition','target_key':other,'scope':'Same article explicitly paired by publisher header; source-file and textual equivalence not independently audited','evidence':ev}
  if link not in p['version_links']:p['version_links'].append(link)
  p.update(canonical_work_id='work:'+a,canonical_work_status='edition_relation_verified_publisher_header')
  if ev not in p['evidence']:p['evidence'].append(ev)
  L.upsert('publication_reviews',p,'Unify explicitly paired edition work identity while preserving both publication records')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==runid)
 for ev in [e1,e2]:
  if ev not in run['evidence']:run['evidence'].append(ev)
 run.update(checkpoint='Three of239 CV entries bibliographically reconciled (167,88,159);236 remain pending. Raw source DOI/volume discrepancies preserved. Cuboid edition pair linked; other edition pairs require explicit primary evidence. No author-route closure.',closure_state='in_progress')
 L.upsert('discovery_runs',run,'Checkpoint manual identity reconciliation and remaining denominator')
 audit=dict(cv_entries=239,reconciled_entries=[167,88,159],remaining_entries=236,edition_pairs_linked=1,new_publication_records=0,counts=L.counts(),validation=L.validate())
 L.atomic(L.HERE/'hao_yan_cv_reconciliation_first_audit.json',json.dumps(audit,indent=2)+'\n');print(json.dumps(audit,indent=2))

if __name__=='__main__':main()
