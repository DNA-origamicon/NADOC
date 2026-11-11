"""Three downloaded ACS supplements: bounded, source-specific design reviews."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[('10.1021/acsnano.8b01844',
  '12074702-nn8b01844_si_003.pdf',
  '12074702',
  'SIp1Additional Structural Details; selected experimental/scaffold paragraphs and simulation comparison; '
  'parent references2/3',
  'Modified Rothemund rectangle is284ntwide versus original288,24helices, retains73ntregion; modeled folded '
  'rectangle uses6909ntscaffold and192staples (48of30nt,144of32nt). Experimental MCS/handle lengths433/217nt '
  'and total handles433/295nt are distinct from simulated10ntpolyA replacements.10helix bundle explicitly '
  'uses hexagonal lattice,1768ntscaffold and51staples. Separate Koirala7tile biosensor has14761nt '
  'and44bpduplex locks. Experimental constructs and simulation variants require separate lineage; no '
  'reconstruction or simulation performed. Parentrefs2Kim2014force-control and3Koirala2014mechanochemical '
  'sensing need reconciliation. Native/sequence completeness not established by structural summary.',
  ['Audit full experimental/model sequence differences and handle attachments.',
   'Acquire all native/source files and parent-design exact identities for rectangle,10HB and7tile sensor.',
   'Check per-design lattice/eligibility and preserve simulation-only variants separately.']),
 ('10.1021/jacs.8b03914',
  '12189572-ja8b03914_si_001.pdf',
  '12189572',
  'SIpp2–3design/assembly and RNA-template description; sequence-section headings and capture replacements; '
  'finalrefs',
  '24HB and tripod usep7560; triangle assembled viaRothemund protocol withM13mp18 source. Origami cores '
  'receive capture-strand replacements to attach RNA templates bearing viral assembly origin. RNA length '
  'classes approximately720/1230/1910nt are protein-assembly templates, not different origami scaffold '
  'lengths. Last80ntRNA anchors hybridize to capturing strands;24HBcapture section specifies40ntextensions '
  'andSL/ML/LLspecific sets. Separate base/capture tables exist for24HB,triangle,tripod; exact per-site '
  'replacement coverage not fully audited. Viral-protein and RNA assemblies remain distinct from DNA cores. '
  'Source washing-buffer unit400nmNaCl preserved pending verification.',
  ['Audit all base/capture tables and site-specificSL/ML/LLreplacement sets.',
   'Resolve exact parent/native24HB/tripod/triangle and lattice eligibility individually.',
   'Check RNA/protein composition alongside DNA without treatingRNAtemplates as origami scaffolds.'])]
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,filename,fileid,locator,note,questions in rows:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/filename,'https://ndownloader.figshare.com/files/'+fileid,locator)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=questions,reviewer='Codex named SI sections and stated image inspection',run_id='B0012',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-supported components and unresolved design checks without catalog promotion')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Reviewed final2ACS SIs: force-unravelling experimental/model variants and viral-protein capture platforms.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['All10rotating low/broad records','All10rotating low/broad records in B0012','Full table/native/parent checks for3new SI reviews; citations and FNANO2011'],validation=[L.validate()])
 L.upsert('batches',b,'Save actual15of25first-pass coverage and10unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_sixth_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_reviewed':sum(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys']),'batch_inputs':len(b['input_keys']),'complete_source_certifications':0,'counts':L.counts(),'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
