"""Save main-paper variant evidence without certifying unverified source recipes."""
import re
import subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nature04586'; rid='B0017'
 path=L.ROOT/'assets/research-20261105/rothemund2006-main.pdf'
 ev=evidence(path,'https://rothemundlab.caltech.edu/downloads/folding_dna.pdf','Entire main text and Figures1-3 captions, printed297-302 (PDF1-6), read. Figure images not independently audited here. Printed302 bibliography extracted by column; references1-24 retained.')
 notes={
 'S001':'Main300: 26-helix square, linear scaffold, 2.5-turn spacing and predominantly26mer staples. Reported13% well-formed of45 AFM objects. Hourglass appearance is reported deformation of squares, not an independently designed core.',
 'S002':'Main300-301: rectangle uses1.5-turn spacing,32mer staples,circular scaffold and bridged seam;90% well-formed of40. Unbridged variant65% of40. Edge staple omission suppresses stacking; individual staple omissions are defect controls. Figure3 DNA/hexagonal hairpin patterns modify staples without establishing new core geometry.',
 'S003':'Main301: five-pointed star uses1.5-turn spacing and32mer staples. Linear scaffold11% well-formed of70 versus untreated circular scaffold63% of43. Preserve these scaffold preparation variants separately.',
 'S004':'Main301: three-hole disk has an asymmetric scaffold folding path with five seams despite symmetric outline;70% well-formed of90. This does not resolve the SI2 Note12 diagram errors already recorded.',
 'S005':'Main301: triangle comprises three rectangular raster domains with2.5-turn spacing and single covalent scaffold links between domains;less than1% well-formed of199. Deformation and interparticle stacking are observations, not additional authored designs.',
 'S006':'Main301/Figure3: sharp triangle comprises trapezoidal domains with1.5-turn spacing and bridging staples at vertices;88% well-formed of78, versus55% of22 without vertex bridges. Edge staples are merged/broken into extended staples for hexagons and triangular lattices (SI NoteS7);hexagon yield less than2% of70,lattice yield not measured. Preserve bridge,pattern and assembly variants; exact recipes remain pending.',
 'S007':'Main301/Figure3e-i: map rectangle has a different aspect ratio. Edge4T loops/tails reduce stacking;30% monomers of319 versus all aggregated without them. This observation does not make the225-row bridged SI list an experimentally verified unbridged map recipe.'}
 general='Main299: M13mp18 is7249nt;73nt hairpin-containing region avoided,leaving7176nt available but not necessarily all folded;remainder strands up to25nt complement unused sequence. BsrBI cuts within avoided region for linear scaffolds. Figure1 is a33x35nm,900nt design illustration, not independent experimental evidence. Future3D/megabase structures and protein/plasmonic breadboards in Discussion are proposals. AFM well-formed yields use a qualitative15nm defect threshold and are not synthesis completeness measures.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 if ev not in p['evidence']:p['evidence'].append(ev)
 if general not in p['rationale']:p['rationale']+=' '+general
 p['unresolved_questions']=[q for q in p['unresolved_questions'] if not q.startswith('Read mainpaper')]
 q='Main text/captions read; remaining SI, per-variant staple recipes, partial-square evidence and24primary citation identities still require review. Figure images not independently audited in main followup.'
 if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 p.update(reviewer='Codex main-paper text and variant attribution review',run_id=rid,date=L.DATE)
 L.upsert('publication_reviews',p,'Extend source audit with entire main text; preserve unresolved sequence completeness')
 for did,note in notes.items():
  d=next(x for x in L.read('design_evidence') if x['design_id']==did)
  for field in ['evidence','source_files']:
   if ev not in d[field]:d[field].append(ev)
  if note not in d['core_variant_composition']:d['core_variant_composition']+=' '+note
  check='Verify main-described variants against exact SI strand sets and scaffold preparations; main yield does not certify source completeness.'
  if check not in d['outstanding_checks']:d['outstanding_checks'].append(check)
  d.update(source_completeness='not_verified',review_stage='source_reviewed',review_run=rid)
  L.upsert('design_evidence',d,'Attach main-paper variant evidence to stable legacy group')
 raw=subprocess.check_output(['pdftotext','-f','6','-l','6','-x','300','-y','0','-W','310','-H','700',str(path),'-']).decode()
 raw=raw.split('Supplementary Information')[0]
 refs=[(1,'Feynman, R. P. There’s plenty of room at the bottom. Engineering and Science 23(5),22-36 (Caltech, February,1960).')]
 refs.extend((int(m.group(1)),' '.join(m.group(2).split())) for m in re.finditer(r'(?m)^(\d+)\.\s+(.+?)(?=^\d+\.\s+|\Z)',raw,re.S))
 assert [n for n,_ in refs]==list(range(1,25))
 for n,citation in refs:
  L.upsert('discovery_edges',dict(edge_id=f'B0017:rothemund2006:main:{n}',source_key=k,target_key=f'citation:rothemund2006:main:{n}',relation='cites',citation=citation,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=f'Printed302 reference{n}',reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all printed main references without relevance filtering; preserve printed volume26 in ref15')
 b=next(x for x in L.read('batches') if x['batch_id']==rid)
 action='Rothemund main followup: all main text/captions read; S001-S007 scaffold,seam,vertex,pattern and assembly variants recorded;24printed references retained. Still1of25inputs,24remain.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Next balanced input PMC7080001; remaining24 B0017 records.','Rothemund remaining SI and exact per-variant recipes; reconcile24main references.','Priority author/citation discovery continues; FNANO deferred.'])
 L.upsert('batches',b,'Checkpoint main followup without increasing reviewed publication count')
 print(L.validate())

if __name__=='__main__':main()
