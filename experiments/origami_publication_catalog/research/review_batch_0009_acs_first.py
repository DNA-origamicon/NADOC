"""Named-section review of five ACS source sets; no molecular authoring."""
import ledger as L
from review_batch_0001 import evidence
NOTES=[
 ('10.1021/acsnano.6b01537','SI pp2,7–10,15: FigS1, Notes1–4 and binding-site sequence headings',
  'Six-helix tube uses7223nt consensus region of M13-derived scaffold; p8064 leaves841nt unused scaffold loop. Approximately400nm tube has eight sites of three tethers, spaced126bp/42.2nm. Note4 specifies142core staples plus24binding-site staples with3prime15A tails. Four-site variant retains sites1,3,5,7 with tails removed at other sites, used for56nmAuNPs. Unintended9–11particle complexes can arise from scaffold poly-A motifs; these are not extra designed sites. Native caDNAno available on request.',
  ['Verify full core/staple inventory and scaffold routing against diagrams; no native file acquired.','Distinguish eight/four-site substitutions, unused scaffold loops and particle occupancy outcomes.']),
 ('10.1021/acs.nanolett.6b01335','SI pp1–3,8–9,13–17: folding, lattice text, model settings, dimensions and CAD captions',
  'Three experimental structures: p7308single-layer sheet, p8064three-layer brick, p7560 24HB. SI p8 explicitly calls brick/sheet square lattice and24HB hexagonal lattice. FigsS6–S8 identify caDNAno designs; captions only inspected, topology not fully traced. CanDo/Crysol fit uses2.45nmDNA diameter; model parameters and fitted spacing are not replacement authoring geometry. Extracted equations/annealing ellipses have corrupt glyphs despite no pdftotext stderr.',
  ['Inspect CAD images/native sources and all staple sets for each of three cores.','Resolve parent designs (refs7–9) separately from methods refs.','Visually check equations/table notation before numerical reuse; distinguish designed versus fitted dimensions.']),
 ('10.1021/jacs.6b03966','SI001 pp1–4,7–13 and SI002 pp1–3: methods, failed designs, named CAD captions, connector designs and sequence-table headings',
  'p7560-scaffold hexagon tiles1x4,2x4,4x2 and failed4x4, plus4x4H-3PS intermediate, have separate core and connector strands. Eight connector designs span2bp,1bp,blunt,quasi-gap,gap and2nt-loop variants. Failed star motifs are retained as attempts, not omitted or certified successful. Honeycomb in the title describes the higher-order2Dlattice; it does not by itself establish intrabundle honeycomb packing. SI002 contains p7560 sequence and strand tables with start/end coordinates and roles; only initial tables inspected, no completeness assertion.',
  ['Inspect all diagrams and sequence-table continuations and map each core/connectivity variant.','Separate one/two-step assemblies, tubes/lattices, AuNPcapture strands and unsuccessfully folded designs.','Verify intrabundle lattice independently of higher-order honeycomb geometry.']),
 ('10.1021/acsnano.6b00413','SI pp1–5,13–14; p13 FigS11 visually rendered and inspected',
  'Experiments use origami masks on SiO2 and retain cavities in etched patterns. FigS11 is a caDNAno cuboid diagram; paragraph associates splitting with helices18/26 and positions71/109. Rendered page confirms diagram and caption, but not a complete staple/routing audit. Etched SiO2 blocks are processed products rather than additional origami designs.',
  ['Acquire main methods and identify scaffold, full staple set and parent design.','Inspect native CAD/lattice and map cavity geometry before eligibility.']),
 ('10.1021/acsnano.6b03076','SI pp5,11,13: FigS1 caption, TableS1 role key and FigS3',
  'Four-page caDNAno diagram distinguishes core staples, AuNP-binding extensions and interflower linker-capable staples. TableS1 specifies C2inserts to reduce internal stacking and C6outer extensions preventing interstructure stacking. Chain/square/hexagonal keys select positions where C6 is replaced by A/Btype interflower linkers. FigS3 describes rectangular bare structures without AuNPs and flower formation with central AuNP. Assembly lattice types are not independent scaffold cores.',
  ['Inspect all four image-heavy CAD pages and six-page sequence table with color/underline roles.','Confirm scaffold and exact core topology from main methods; distinguish particle-induced conformation from new routing.','Map each A/Bconnector variant without conflating interflower assembly with core design.'])]

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for doi,locator,note,questions in NOTES:
  p=pubs[doi];evs=[evidence(L.ROOT/'assets'/f['local_file'],f['url'],locator) for f in p['legacy_record']['downloaded_supplements']]
  p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=evs,rationale=note,unresolved_questions=questions,reviewer='Codex named SI section inspection',run_id='B0009',date=L.DATE)
  L.upsert('publication_reviews',p,'Inspect retained supplements; separate cores, functionalization and assemblies without completeness certification')
 groups=[
  ('RDE0028',NOTES[0][0],['6HB common core with four/eight AuNPattachment-site variants'],'unresolved'),
  ('RDE0029',NOTES[1][0],['p7308single-layer sheet'],'square lattice stated; topology not verified'),
  ('RDE0030',NOTES[1][0],['p8064three-layer brick'],'square lattice stated; topology not verified'),
  ('RDE0031',NOTES[1][0],['p7560 24HB'],'hexagonal packing stated; crossover topology not verified'),
  ('RDE0032',NOTES[2][0],['1x4HT','2x4HT','4x2HT','failed4x4HT','4x4H-3PS intermediate','unsuccessful star-motif attempts'],'unresolved; higher-order honeycomb does not determine core lattice'),
  ('RDE0033',NOTES[3][0],['cuboid mask with cavity'],'unresolved'),
  ('RDE0034',NOTES[4][0],['AuNPnanoflower and bare rectangular conformation; A/Blinker variants'],'unresolved')]
 for ident,doi,names,lattice in groups:
  p=pubs[doi]
  L.upsert('design_evidence',dict(design_id=ident,legacy_record={},review_run='B0009',catalog_eligibility='unresolved',publication_keys=[doi],named_objects=names,variant_links=[],relationships=[],lattice_decision=lattice,evidence=p['evidence'],source_files=p['evidence'],core_variant_composition=p['rationale'],source_completeness='not_verified',outstanding_checks=p['unresolved_questions'],review_stage='source_reviewed',run_id='B0009',date=L.DATE,identity_status='provisional family; parentage and distinct-core reconciliation pending'),'Record provisional source-backed design family without reconstruction or catalog promotion')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0009');b.setdefault('completed_actions',[]).append('Inspected five ACS source sets at named sections; saved seven provisional design groups RDE0028–34, including three distinct SAXS cores.')
 b.update(after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'],next_queue=['Review remaining10ACS and5low/broad B0009records.','Inspect full CAD images/sequence tables for source completeness; resolve parentage.','Continue FNANO2014 and remaining discovery routes.']);L.upsert('batches',b,'Checkpoint10/25first passes with unresolved source checks');print(L.validate())
if __name__=='__main__':main()
