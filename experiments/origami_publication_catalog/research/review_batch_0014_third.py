"""Two downloaded supplements inspected; exact source sets remain open."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[('10.1021/jacs.8b10609', '13729112-ja8b10609_si_001.pdf', '13729112', 'SI S1 sample preparation; S2 geometry description; S4/FigsS7–8; S5 TableS1–14 headings', 'Equilateral triangular tile comprises three isosceles domains, each with32 helices, with ssDNA bridges/loops; M13mp18 7249nt starts at supplier nucleotide5087. This is a new triangular tile family with edge-modified assembly variants, not automatic reuse of the conventional Rothemund triangle. Tables separate interior/bridge staples, inert hairpin-capped edges, stacking edges,48 negation strands, symmetric/asymmetric tiles and stacking-plus2nt sticky ends; TablesS8–14 specify two small-hexagon and five large-hexagon tile types. FigS7 additionally identifies rhombic-triacontahedron, unbounded-array and dome-containing hexagon assemblies. Multitile assembly explicitly adds a full negation-strand set before mixing. These assemblies and edge variants are not counted as independent cores. Complete table/map correspondence, supplier scaffold origin convention, native sources and narrow lattice eligibility remain unresolved; no molecular reconstruction performed.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc);p=pubs[key]
  if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main article, native/parent sources, exact scaffold and all variant compositions.','Audit complete base and replacement oligo sets against diagrams; resolve narrow catalog eligibility.','Enumerate bibliography and follow backward/forward citations and author routes.'],reviewer='Codex named SI sections and tables',run_id='B0014',date=L.DATE)
  L.upsert('publication_reviews',p,'Record primary supplement design evidence without source-completeness inference')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0014');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='Sevenof25 inputs screened; triangular tile core and edge/negation/assembly distinctions recorded without complete-source certification.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],validation=[L.validate()],next_queue=['acsami8b15629 and remaining8ACS SI','Ten rotating2015records','All source and discovery followups; FNANO2010'])
 L.upsert('batches',b,'Save7of25first-pass coverage and concrete remaining queue')
 L.atomic(L.HERE/'batch_0014_third_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=7,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
