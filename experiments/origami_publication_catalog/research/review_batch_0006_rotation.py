"""B0006 balanced rotation and deeper retained-source inspection."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 base=L.ROOT/'assets/research-20261105';pubs=L.read('publication_reviews');b=next(b for b in L.read('batches') if b['batch_id']=='B0006')
 if b['status']=='completed':
  print(L.validate());return
 for doi in b['input_keys'][15:]:
  r=next(r for r in pubs if r['doi']==doi)
  if r['run_id']!='bootstrap-20261105':continue
  file=base/(doi.replace('/','_')+'.json');meta=json.loads(file.read_text())['message'];ev=[evidence(file,'https://api.crossref.org/works/'+doi,'Deposited bibliographic title/type and abstract when present')]
  stage='metadata_screened';rel='uncertain';con=[];note='Deposited metadata has no abstract; title alone does not establish actual design contribution.';q='Acquire primary article/chapter and source material; inspect actual origami use and parent references.'
  if meta.get('type')=='book-chapter':r['publication_type']=['book_chapter'];q='Acquire full chapter, reconcile any earlier journal version, and distinguish tutorial/reused objects from new designs.'
  if doi=='10.1016/j.bpj.2011.11.2121':q='Verify whether this record is a meeting abstract rather than a full article, and reconcile journal counterparts; Crossref journal-article type alone is insufficient.'
  if doi=='10.1063/1.4768929':note='Deposited abstract describes DNA translocation and fluorescence in glass nanopores without identifying an origami object. This does not justify final exclusion without methods.';q='Inspect main experimental DNA substrates; reconcile author preprint arXiv1301.2681 separately from journal date.'
  if doi=='10.1039/c2cc32204h':note='Crossref has no abstract. Search located a primary RSC supplement, but direct acquisition failed; source completeness and design decisions remain unresolved.';q='Retry public source URL https://www.rsc.org/suppdata/cc/c2/c2cc32204h/c2cc32204h.pdf or author archive; inspect assembly and source tables.'
  if doi=='10.1073/pnas.1117813109':
   stage='design_sources_reviewed';rel='design_bearing';con=['reused_design','modified_design'];ev=[evidence(base/'schulman-replication.pdf','https://www.dna.caltech.edu/Papers/crystal-self-replication2012.pdf','PDF pp.2,5 Results/Tile Design and Assembly'),evidence(base/'schulman-replication-si.pdf','https://www.dna.caltech.edu/Papers/crystal-self-replication2012_SI.pdf','PDF p.3 Fig2; p.22 Sequence Design')];note='A32-helix M13mp18 origami seed uses192 inherited staples plus adapter strands whose sticky ends are changed to program OIIO tile-crystal growth. Non-origami daughter crystals do not erase origami-seed reuse.';q='Inspect Supplemental Methods12.9 and parent reference4 for complete adapter/core mapping; keep tile crystal sequences distinct from origami seed variants.'
  if doi=='10.1038/ncomms2095':
   stage='fulltext_reviewed';rel='design_bearing';con=['new_design','modified_design'];ev=[evidence(L.ROOT/'assets/sources/PMC3493638.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC3493638/','Results: Self-assembly in presence of magnesium/sodium; Shape- and design-specific sodium requirements')];note='Experiments test honeycomb6/8/10/12/18/24HBs, a square100HB, and four42HB staple-breaking variants. The100HB formed with magnesium only; that is a condition-specific result, not absence of the design. Four42HB variants share scaffold permutations but differ in nick placement.';q='Reconcile SI spreadsheet and routing for each bundle; apply catalog block/brick scope separately from lattice evidence, and preserve42HB nick-rule variants.'
  r.update(review_stage=stage,relevance=rel,design_contributions=con,catalog_eligibility='unresolved',evidence=ev,rationale=note,unresolved_questions=[q],access='partial',reviewer='Codex primary-section inspection or explicit metadata-only triage',run_id='B0006',date=L.DATE)
  L.upsert('publication_reviews',r,'B0006 balanced rotation; no title-only relevance or exclusion decisions')
 # Preserve existing group IDs while attaching actual inspected spreadsheet/source evidence.
 acs=next(a for a in json.loads((L.ROOT/'acs_acquisition.json').read_text())['records'] if a['doi']=='10.1021/nl502626s')
 p=next(r for r in L.read('publication_reviews') if r['doi']==acs['doi'])
 for did,suffix,sheets in [('S061','si_002.xlsx',['7k-NR_1.5bppt','7k-NR_1.67bppt','7k-NR_1.33bppt']),('S062','si_003.xlsx',['51k-NR_1.5bppt','51k-NR_1.67bppt','51k-NR_1.33bppt'])]:
  d=next(d for d in L.read('design_evidence') if d['design_id']==did);f=next(f for f in acs['files'] if f['name'].endswith(suffix));ev=evidence(L.ROOT/'assets'/f['local_file'],f['url'],'XLSX workbook.xml sheet labels: '+', '.join(sheets))
  d.update(review_run='B0006',evidence=p['evidence'],source_files=[ev],lattice_decision='square_explicit_SI_p7',source_completeness='not_verified',core_variant_composition='Three pitch variants; workbook labels are recorded literally and require matching to10.xbppt SI labels. Sheet content, scaffold-to-staple matching and native JSON remain unverified.',outstanding_checks=p['unresolved_questions'])
  L.upsert('design_evidence',d,'Inspect retained workbook sheet identities while preserving legacy group ID')
 for did in ['D017','D018','D019']:
  d=next(d for d in L.read('design_evidence') if d['design_id']==did);p=next(r for r in L.read('publication_reviews') if r['doi']=='10.1038/ncomms2095');d.update(review_run='B0006',evidence=p['evidence'],lattice_decision='square_explicit_primary_results' if did=='D019' else 'honeycomb_explicit_primary_results',source_completeness='not_verified',core_variant_composition='Primary results identify this bundle family; exact staple/scaffold variant mapping still pending.',outstanding_checks=p['unresolved_questions']);L.upsert('design_evidence',d,'Update original bundle group evidence from inspected primary results')
 p=next(r for r in L.read('publication_reviews') if r['doi']=='10.1021/nn503513p');ev=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC4174095.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC4174095/','Methods: M13 Scaffold Prep, Endotoxin Removal, Nanostructure Synthesis and Purification')
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['rationale']+=' Primary methods describe p7308 scaffold and four design-specific folding sets (DNO, NT, NR and nanorobot), with separate folding magnesium concentrations.';L.upsert('publication_reviews',p,'Add actual primary preparation evidence for all four tested objects')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0006');b.update(status='completed',completed_actions=b['completed_actions']+['Screened ten rotating records: two primary-source design-bearing decisions and eight unresolved metadata cases.','Acquired crystal-replication main article/SI; RSC supplement direct retrieval failed.','Updated five existing design-group IDs with inspected primary or workbook evidence.'],after_counts=L.counts(),validation=[L.validate()],exclusion_audit={'sample':[],'reason':'No final catalog exclusions in B0006.'},unresolved_keys=b['input_keys'],next_queue=['FNANO2017 full schedule review and author/citation discovery','Schulman seed adapter Methods12.9 and parent reference4','Resolve all eight metadata-only B0006 records','Match notched-rectangle workbook sheets and locate native JSON files'])
 L.upsert('batches',b,'Finish25 B0006 first-pass screens; unresolved source checks retained')
 print(L.validate())
if __name__=='__main__':main()
