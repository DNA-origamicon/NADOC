"""Three downloaded ACS supplements: bounded, source-specific design reviews."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[('10.1021/acs.nanolett.8b00660',
  '11542103-nl8b00660_si_001.pdf',
  '11542103',
  'SIcontents/introduction; scaffold headingspp2–3; design/table headings; FigS3caption and '
  'fluorescence-calibration discussion',
  'Nine named shapes listed: L-thin_rod, L-thick_rod, L-block, L-ring, L-octahedron, L-barrel, S-thin_rod, '
  'S-thick_rod, S-ring. SI suppliesp3024/p7308 scaffold sequences and graphical caDNAno maps followed by '
  'long staple tables; full lengths and per-core assignments not checked. Introduction says sequences for '
  'eleven structures whereas contents/TableS1/FigS3say nine: retain discrepancy pending inventory. Three '
  'Cy5-labeled core oligos per structure distinguish core labeling from handle/anti-handle assay variants. '
  'K10-PEG5K coating and cell-assay conditions are material/experimental variants. Geometry and scope need '
  'per-design review; no blanket eligibility or complete-source claim.',
  ['Audit all nine named core tables and resolve eleven-versus-nine wording.',
   'Verify scaffold length/assignment, Cy5locations and handle/anti-handle variants.',
   'Acquire main/native files and parents; inspect each lattice separately.']),
 ('10.1021/acsnano.8b01510',
  '11642015-nn8b01510_si_001.pdf',
  '11642015',
  'SIpp2–6design comparisons/blueprint captions; pp12/14labeling/hinge; p18tall rectangle; table locations',
  'Three sensor designs SH(single-layer horizontal), SV(single-layer vertical), DH(double-layer horizontal); '
  'SH/SV share scaffold pathway and more than half staples but foot locations differ. Fluor arrays '
  'report56/60/30FRET pairs respectively. SV hinge variant removes specified staples to '
  'leave7ntscaffold-only hinge, distinct from conformational opening. Dye TdT labeling and biochemical '
  'sensor modules require separate composition records. Additional tall-rectangle control has edge staples '
  'omitted, one16staple column biotinylated and four16staple columns Cy5-labeled. '
  'TablesS1/S2/S3locatedpp21/27/33 but not fully audited. Source loop lengths96/37are described asbps '
  'although loop strand pairing is unresolved; do not infer paired geometry.',
  ['Audit SH/SV/DHtables, removable-hinge subset and sensor-module replacements.',
   'Reconcile tall-rectangle parent and all omitted/labeled staples.',
   'Acquire main/native scaffold identity and verify lattice/source completeness per design.']),
 ('10.1021/acsnano.8b01669',
  '11826806-nn8b01669_si_001.pdf',
  '11826806',
  'SIcaption text S1–S12, especiallyS1/S5tile design, S8labels andS10nanotube; equations not interpreted',
  'S1explicitly describes caDNAno square-lattice default10.66bp/turn, reduced to10.44by base skips; '
  'unmodified/braced/rolled10.44variants use distinct brace/rolling modifications. S5adds10.55 and10.66tile '
  'designs. S8polyAextended staples attach polyTgold labels; gold configurations are material/labeling '
  'variants, not automatically DNA core differences. S10includes a separate10helix nanotube with caDNAno '
  'diagram/TEM; do not omit this comparison design. The29finite-element basis models and hollow-cylinder '
  'fits are analytical models, not29authored experimental designs. Supplement provides graphical layouts but '
  'no independently verified complete staple inventory. Square-lattice evidence pertains to stated tiles, '
  'not automatically nanotube; eligibility remains unresolved pending source audit.',
  ['Acquire main/native/sequence sources for all tile variants and10helix nanotube.',
   'Audit exact base skips, braces/rolling connectors and gold-label replacements.',
   'Inspect diagrams and equations visually as needed; separate fitted dimensions from design parameters.'])]
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,filename,fileid,locator,note,questions in rows:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/filename,'https://ndownloader.figshare.com/files/'+fileid,locator)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=questions,reviewer='Codex named SI sections and stated image inspection',run_id='B0012',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-supported components and unresolved design checks without catalog promotion')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Reviewed3additional ACS SIs: nine mass/shape cores, beacon sensors plus tall rectangle, and twist tiles plus10helix nanotube.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['acsnano8b01844 and jacs8b03914 supplements','All10rotating low/broad records in B0012','Full table/native/parent checks for3new SI reviews; citations and FNANO2011'],validation=[L.validate()])
 L.upsert('batches',b,'Save actual13of25first-pass coverage and12unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_fifth_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_reviewed':sum(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys']),'batch_inputs':len(b['input_keys']),'complete_source_certifications':0,'counts':L.counts(),'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
