"""Record inspected SI sections without equating functional states with core designs."""
import json
import ledger as L
from review_batch_0001 import evidence
NOTES=[
('10.1021/jacs.6b10821','7400014-ja6b10821_si_001.pdf','7400014','28-page SI pp2–3 Methods; p18 FigS14/rectangle description; p21 ribbon linker table heading; p22 shaft description/FigS15 caption; p28 references',
 'M13mp18 rectangles and shafts are used. Rectangle omits two staple columns at each lateral edge to avoid blunt stacking and allow polymerization. Ribbons assemble with26 linkers, followed by26 complementary quenchers; these are assemblies of rectangles, not additional core designs. Shaft explicitly uses caDNAno square lattice: central8-helix shaft and two10-helix single-layer flags on the same side, with4nt lateral-edge loops; actual flag angle depends on internal stress. UV treatment is an experimental condition. Sequence-table headings/tails and routing captions inspected, not complete sequences or diagram routing.',
 ['Trace full rectangle/shaft tables and actual FigS14/S15 routing; identify exact parent variants and native files.','Keep ribbon assemblies, UV conditions and shaft core identity separate; do not certify source completeness from table presence.']),
('10.1021/acs.nanolett.7b00159','7727461-nl7b00159_si_001.pdf','7727461','27-page SI p2 materials; p14 section5/FigS21; p18 section8 A–F composition; p20 sequence table start and p27 tail',
 'M13mp18 origami supports split-aptamer/zipper sensor constructs A–F. Section8 explicitly lists changed staple combinations: A zipper; B/C aptamer combinations at66/178 with different74/170 components; D70/174, E74/170 and F78/166 positions. These are functionalization/position variants until a core comparison establishes otherwise. Modified bases are labeled cU-dye1/cU-dye2. FigS21 scheme is adapted from ref17; parent unresolved. Isolated aptamer control is separate from origami. Full shared-core table and actual placement diagram remain unchecked.',
 ['Resolve ref17 in main article and compare shared core versus functional staples for A–F.','Inspect FigS21 and all sequence rows; determine routing/lattice and modifications without treating six conditions as six independent cores.']),
('10.1021/acsphotonics.6b00946','8055491-ph6b00946_si_001.pdf','8055491','12-page SI p1 LSPR methods; p2 extraction limitation; pp7–9 FigS8–S10 map captions; pp10–12 AFM captions and ref2',
 'Three Au nanolens arrangements20-10-60,20b-10-60 and10-20-60 use an origami scaffold. FigS8 explicitly attributes staple nomenclature/sequences to Rothemund original sharp triangle; 5-prime modifications and nanoparticle positions are marked. FigS9 says green extensions are expected on the opposite face because of DNA helix torsion; this is an author expectation, not an independently verified orientation. Arrangement variants are not established as distinct origami cores. Mathematical extraction on p2 is garbled despite successful conversion; no formula interpreted. Actual maps and particle images not yet visually reviewed.',
 ['Inspect map images and modified staples for all three particle arrangements; reconcile exact sharp-triangle source variant.','Use source image for p2 formula if needed; acquire main Methods and verify synthesis/native design sources.'])]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for doi,name,fid,loc,note,qs in NOTES:
  p=pubs[doi];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  p.update(review_stage='design_sources_reviewed',relevance='design_bearing',publication_type=['journal_article'],design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=qs,reviewer='Codex named SI section inspection',run_id='B0010',date=L.DATE)
  L.upsert('publication_reviews',p,'Inspect UV, aptamer and nanolens sources; separate core and functional variants')
 p=pubs[NOTES[2][0]];ev=p['evidence'][0]
 L.upsert('discovery_edges',dict(edge_id='reuses_design_from:'+p['registry_key']+':10.1038/nature04586',source_key=p['registry_key'],target_key='10.1038/nature04586',relation='reuses_design_from',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='FigS8 p7 explicitly names original sharp triangle; ref2 p12 Rothemund Nature2006 440:297–302',reconciliation_state='bibliographic_parent_matched; exact_variant_pending',run_id='B0010',date=L.DATE),'Preserve explicit sharp-triangle reuse attribution')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0010');b.setdefault('completed_actions',[]).append('Reviewed3ACS UV/aptamer/nanolens sources and explicit sharp-triangle parent; no complete-source certification.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review7remaining ACS and6low/broad B0010records','Resolve main-paper parents and full map/sequence checks','Continue conference/citation/laboratory discovery'])
 L.upsert('batches',b,'Checkpoint12/25 first passes')
 audit=dict(batch_id='B0010',first_pass_count=12,input_count=25,complete_sources_certified=0,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'batch_0010_acs_third_audit.json',json.dumps(audit,indent=2)+'\n');print(audit['validation'])
if __name__=='__main__':main()
