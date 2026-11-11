"""Record candidate counterpart links; do not merge conference/journal identities."""
import ledger as L
from review_batch_0001 import evidence

def main():
 path=L.HERE/'fnano2010_pages78_counterpart_search.json'
 rows={p['registry_key']:p for p in L.read('publication_reviews')}
 pairs=[('conference:fnano2010:41727b81915c38','10.1021/nn1035075','https://pubmed.ncbi.nlm.nih.gov/21323323/','PubMed title, first author and BYU affiliation match program; Epub2011-02-16, issue2011-03-22. Exact poster scope remains unverified.'),('conference:fnano2010:4fa9f822be99ac','10.1021/nl101079u','https://scholarworks.boisestate.edu/mse_facpubs/15/','Boise State author-deposited abstract matches Bui, nanotube/quantum-dot topic and affiliation; journal abstract reports43/71nm array periods. ACS search header online2010-08-03 versus issue2010-09-08; conference scope remains unverified.')]
 for source,target,url,note in pairs:
  assert source in rows and target in rows
  ev=evidence(path,url,'Saved search result primary metadata/author-repository abstract; conference program pages7–8')
  L.upsert('discovery_edges',dict(edge_id='fnano2010-counterpart:'+source,source_key=source,target_key=target,relation='possible_journal_counterpart',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='bibliographic_candidate_supported; exact_scope_identity_pending',rationale=note,run_id='fnano-2010',date=L.DATE),'Retain supported candidate without identity merge')
  p=rows[source]
  if ev not in p['evidence']:p['evidence'].append(ev)
  q='Candidate journal counterpart '+target+': '+note
  if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
  L.upsert('publication_reviews',p,'Record candidate counterpart and retain abstract/source questions')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2010')
 run['counterpart_searches']=[dict(queries=['"Jianfei Liu" "Metallization" "DNA origami"','"Hieu Bui" "Quantum dot" "origami" 2010'],evidence_file=str(path.relative_to(L.ROOT)),scope='Two targeted searches; not exhaustive.',additional_routes=['BYU dissertation3143 full text and reference reconciliation','Hieu Bui CUA publication bibliography','Boise State QDNA publication bibliography'],status='two candidate journal links saved; additional routes pending')]
 L.upsert('discovery_runs',run,'Save targeted searches and pending author/source routes')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0010')
 action='Targeted primary metadata/author-repository search supports two candidate journal links; no identity merges or design-source certifications.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()])
 L.upsert('batches',b,'Save counterpart reconciliation progress')
 print(L.validate())
if __name__=='__main__':main()
