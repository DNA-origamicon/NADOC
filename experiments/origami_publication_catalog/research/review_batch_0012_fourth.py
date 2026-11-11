"""Three downloaded ACS supplements: bounded, source-specific design reviews."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[('10.1021/acs.nanolett.8b00793',
  '10816913-nl8b00793_si_001.pdf',
  '10816913',
  'SIpp2–4assembly/reconfiguration; sequence section beginningp8 and modified strands beginningp13',
  'M13mp18 rectangular origami tiles A/B/C/D assembled with ordinary, functionalized edge and hairpin '
  'staples. AB/CD and AD/CB are alternative dimer pairings of functionalized monomers, not necessarily four '
  'independent core outlines. Fuel/anti-fuel and blocker strands control separation/reassembly; DNAzyme '
  'subunits and cleavable substrates are separate catalytic components. SI has base rectangular staple list '
  'followed by modified edge, DNAzyme, substrate and hairpin strands. Only section '
  'introductions/representative rows inspected; all replacement mappings and full variant inventory remain '
  'open. No complete-source or lattice certification.',
  ['Audit full base/modified tables against each A/B/C/Dcomposition and parent rectangular design.',
   'Acquire main/native diagrams to distinguish core shapes from markings and dimer connectivity.',
   'Retain catalytic accessory strands and dynamic assembly states separately.']),
 ('10.1021/acs.nanolett.8b00592',
  '10871972-nl8b00592_si_001.pdf',
  '10871972',
  'SIpp2–3assembly; S6–S8diagram captions onpp16–18; p19all references',
  'p8064 switchD16 has16active basepair-stacking contacts. Separate self-complementary brick experiments '
  'useA1with active protrusions/deactivated recessions andA2with active recessions/deactivated '
  'protrusions;10T overhangs deactivate blunt-end contacts. Monomers and heterodimer kinetics are distinct '
  'from switch conformational transitions. Methods explicitly reuse preparation/design '
  'refs3GerlingScience2015,347,1446–52 and4BruetzelNanoLetters2016,16,4871–9. S6is graphical switch routing, '
  'S7/S8brick diagrams; full base mapping and sources not audited. p8064preparation citation1 differs from '
  'design lineage. No new core completeness or lattice claim.',
  ['Reconcile switch and both brick variants with parent studies and native files.',
   'Audit full sequences/overhang sets in diagrams and parent supplements.',
   'Separate salt-dependent conformations and dimer assembly states from core designs.']),
 ('10.1021/acs.langmuir.8b00793',
  '11540738-la8b00793_si_001.pdf',
  '11540738',
  'Entire5page SI extracted text: FigsS1–S5captions',
  'SI reports DNA-origami triangles adsorbed onto nanohole arrays and template-stripped gold surfaces. '
  'S4uses1nMtriangles with50mMMgCl2; S5uses10mM. Nanohole diameter, polymer sphere shrinking/cleaning and '
  'gold-film optical characterization concern the substrate, not origami core dimensions or variants. No '
  'staple/scaffold construction recipe is provided in the inspected short SI; main/parent sources required. '
  'Broad design reuse supported by actual triangle experiments, but exact design identity and catalog '
  'eligibility unresolved.',
  ['Acquire main and explicit triangle parent/source; establish scaffold and modified/unmodified staple '
   'composition.',
   'Inspect actual routing/lattice and native or sequence files.',
   'Do not count nanohole/substrate processing conditions as new DNA cores.'])]
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,filename,fileid,locator,note,questions in rows:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/filename,'https://ndownloader.figshare.com/files/'+fileid,locator)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=questions,reviewer='Codex named SI sections and stated image inspection',run_id='B0012',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-supported components and unresolved design checks without catalog promotion')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Reviewed3additional ACS SIs: tile dimer reconfiguration, switchD16 plus bricksA1/A2, and triangle adsorption in nanoholes.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['acsnanolett8b00660 and remainingACS supplements','All10rotating low/broad records in B0012','Full table/native/parent checks for3new SI reviews; citations and FNANO2011'],validation=[L.validate()])
 L.upsert('batches',b,'Save actual10of25first-pass coverage and15unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_fourth_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_reviewed':sum(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys']),'batch_inputs':len(b['input_keys']),'complete_source_certifications':0,'counts':L.counts(),'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
