"""Three downloaded ACS supplements: bounded, source-specific design reviews."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[
 ('10.1021/acssynbio.7b00278','10437774-sb7b00278_si_001.pdf','10437774','TablesS1–S3 text and FigsS1–S11 captions; routing image not fully audited',
 'M13mp18-based six-face DNA box, each face approximately25x25x2nm per FigS2. TableS1 includes native staples and six Cy3-complement handles; TableS2 separately lists face-joining strands, scaffold modifications1/2, complementary replacements and two i-motif strands10[55]/31[112]. Non-M13 scaffold regions and mismatch spacers require explicit composition mapping. TableS3 replaces13[35]/36[111] with rhodamine/dabcyl for FRET; Cy3 reporter is a separate hybridizing oligo. GFP cargo and HIV-Tat coating/charge-ratio conditions are distinct from DNA core variants. Closed/open/disintegrated pH conditions are not automatically separate authored cores. CanDo figures are published simulation output, not native authoring files; no simulation performed.',
 ['Acquire main methods to resolve exact scaffold modifications and parent design.','Audit full TableS1/S2 inventory and colored routing, including all variant replacement sets.','Determine lattice/source eligibility independently; no complete-source certification.']),
 ('10.1021/jacs.7b09024','10454830-ja7b09024_si_001.pdf','10454830','SIp2 design/assembly; p5TableS1; pp6–9 routing captions/scaffold preparation; p22Au barcode; p25refs; p26sequence section introduction',
 'Four named constructs: small tetrahedron ST and rod SR use425nt fragment cut fromp7560 with BsaAI; large tetrahedron LT and rod LR usep7560. TableS1 lists body masses384/396/6456/6144bp and fluorescent loading sites24/28/36/36 respectively; scaffold nt and paired body bp must remain distinct. ST/SR handles extend both5prime and3prime ends; LR36handles on Face1 and LT5prime red staples. LR-Au barcode uses5nmAuNPs attached viaDNA; distinguish modification from original rod. Section3 begins withp7560 sequence and later per-construct tables, not yet fully audited. Tetrahedron/rod labels alone do not establish lattice or catalog eligibility. Both folded structures and scaffold controls enter uptake comparisons.',
 ['Audit p425 sequence/cut endpoints/helper strands and all sequence tables against diagrams.','Inspect individual ST/SR/LT/LR packing and completeness; separate LR-Au composition.','Acquire main/parent/native files; resolve all3SI references.']),
 ('10.1021/acs.nanolett.8b00332','10498540-nl8b00332_si_001.pdf','10498540','SIpp13–17 design/device/assembly; p13rendered1600px; contents',
 'M13 DNA origami frame hosts HPV/OANI conjugate device. Renderedp13 shows rectangular cavity with two inward projections and graphical sequence/routing map; individual bases not transcribed or validated. P15 lists six involved staples84-1/72-1/44-1/98-2/84-2/18-2 plus distinct HPV/OANI template strands. HPV homo-X, OANI homo-X and HPV-OANI are device compositions, not proven separate origami cores. P17 provides frame assembly and separate conjugate/template assembly. Full baseframe staples are not present as ordinary extracted text onp13; graphical source must be inspected or native source found. Printed thermal wording says increasing65to25, an internal inconsistency retained without silently repairing protocol.',
 ['Acquire main and parent/native frame; audit graphical sequence map at adequate resolution.','Map six device staples to replaced baseframe strands and exact conjugate/template composition.','Inspect molecular-conjugate synthesis and remaining sections as needed; lattice eligibility unresolved.'])]
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,filename,fileid,locator,note,questions in rows:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/filename,'https://ndownloader.figshare.com/files/'+fileid,locator)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=questions,reviewer='Codex named SI sections and stated image inspection',run_id='B0012',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-supported components and unresolved design checks without catalog promotion')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Reviewed3additional ACS SIs: Inside-Out Viruses box/i-motif/dye variants; uptake ST/SR/LT/LR; molecular electro-optical frame/device compositions.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['acsnanolett7b05354 and remainingACS supplements','All10rotating low/broad records in B0012','Full table/native/parent checks for3new SI reviews; citations and FNANO2011'],validation=[L.validate()])
 L.upsert('batches',b,'Save actual4of25first-pass coverage and21unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_second_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_reviewed':sum(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys']),'batch_inputs':len(b['input_keys']),'complete_source_certifications':0,'counts':L.counts(),'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
