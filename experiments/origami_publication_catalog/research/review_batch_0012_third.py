"""Next three ACS supplements: component and source discrepancies preserved."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[['10.1021/acs.nanolett.7b05354',
  '10544566-nl7b05354_si_001.pdf',
  '10544566',
  'SIcontents; pp3–4plate/pore characterization; pp26–27leash and dye table',
  'p8064 DNA plate with central pore and duplex leash. AFM reports lateral sizes50.6/55.1nm, height3.1nm and '
  'pore15.4/16.1nm; these measured dimensions do not certify lattice. Source lists leash1–25 separately from '
  'body staples. A1 and A2 share5primeAtto647N leash1*, but A1 donorAtto532 is on34[90]–35[90] whereas A2 '
  'donor is on leash2a*. Leash2a*/2b* split/replacement composition requires auditing against original '
  'leash1/2. Preserve labeled variants and distinct long duplex extension; no reconstruction or simulation. '
  'Published simulation sections/animations identified but not reviewed or executed.',
  ['Audit body/scaffold layout and complete staple list, including ambiguous36[90]–36[89] row at leash '
   'boundary.',
   'Resolve exact split/replacement mapping for A1/A2 and full parent/native design.',
   'Inspect main geometry/lattice and remaining source sections; no completeness claim.']],
 ['10.1021/acsnano.7b08345',
  '10560100-nn7b08345_si_002.pdf',
  '10560100',
  'SIpp2–5gap geometry/control states; finalpp31–32sequence composition and references; companionZIP '
  'inventory',
  'Four base layouts: flat/tube small/large wireframe triangulations, single-duplex edges and2ntvertex '
  'loops. Small triangle base63bp/legs58bp with16or21ntgaps; large128/123bp with81or86ntgaps. Staple-filled '
  'controls, initially gapped structures and enzymatically extended products are distinct '
  'compositions/process states; curved tube and hairpin/partially filled variants add mapping requirements. '
  'ZIP contains4caDNAnoJSONs andsequences.yaml, inspected as source data only. SIp31group descriptions '
  'UFTS/UFTL swap small/large wording; flat-large partial-fill recipe saysCORE+UFFS+LH while usual '
  'flat-large usesUFFL. Preserve discrepancies, do not silently infer correct mixture. No complete-source '
  'certification or final catalog exclusion from this first pass.',
  ['Reconcile YAML subsets and all nativeJSON routings with SIrecipes, including swapped labels andUFFS/UFFL '
   'anomaly.',
   'Acquire main methods/scaffold assignment and map enzyme-generated strands separately from controls.',
   'Perform independent scope/exclusion audit and resolve cited Matthies2016parent.']],
 ['10.1021/acs.nanolett.8b00412',
  '10664101-nl8b00412_si_001.pdf',
  '10664101',
  'SINoteS1assembly; NoteS3geometry paragraphs and cited parent references2/3',
  'p8064 block andp7560 bundle are reused designs: ref2Stein2011FRET ruler andref3Kuzyk2012chiral '
  'plasmonics. Block modified with additional4baseCCCCoverhang oligos to prevent AuNPs catching in edge '
  'scaffold loops. Particle-bindingT19/T8 and3primeT19 strands pair withA15/A9 handles; helix also '
  'usesATT/AAT pairing. AuNPdimers/trimers and connector chemistries are assembly/material variants, not '
  'automatically new DNA cores. NoteS3uses prior block thickness7.66nm, modeled attachment shifts and '
  'assumed2.7nmhelix distance, not an independent lattice certificate. Text labels3prime-thiolT19 but '
  'prints5primeHS-C6 sequence; orientation discrepancy remains unresolved.',
  ['Acquire exact parent/native block/bundle and audit addedCCCC/particle-handle substitutions.',
   'Verify thiol orientation discrepancy against source figures and main methods.',
   'Inspect full sequence/routing sources and all assembly variants; resolve scope independently.']]]
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,filename,fileid,locator,note,questions in rows:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/filename,'https://ndownloader.figshare.com/files/'+fileid,locator)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=questions,reviewer='Codex named SI sections and stated image inspection',run_id='B0012',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-supported components and unresolved design checks without catalog promotion')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Reviewed3additional ACS SIs: voltage plate/leash labels, gap-filling wireframe states and SAXS parent-design/particle assemblies.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['acsnanolett8b00793 and remainingACS supplements','All10rotating low/broad records in B0012','Full table/native/parent checks for3new SI reviews; citations and FNANO2011'],validation=[L.validate()])
 L.upsert('batches',b,'Save actual7of25first-pass coverage and18unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_third_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_reviewed':sum(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys']),'batch_inputs':len(b['input_keys']),'complete_source_certifications':0,'counts':L.counts(),'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
