"""Named-section source reviews; computational origami distinguished from synthesis."""
import json
import ledger as L
from review_batch_0001 import evidence
NOTES=[
('10.1021/acsami.6b11001','7539715-am6b11001_si_001.pdf','7539715','13-page SI pp2–5sectionsS1/S2 andFigS3/S4captions; pp8–9sandwich variant text; p13references',
 'Computational origami-graphene nanopore, not reported experimental synthesis. S2 describes caDNAno-to-NAMD conversion: temporary scaffold breakpoints permit sequence reassignment and are reconnected before simulation. Single-layer pore deletes8 staple A bases to expose scaffold T bases; double-layer deletes18A bases, with8T and10T around the two layers. These are authored computational variants, not experimental staple completeness. Graphene sandwich is a material arrangement rather than automatically another origami core. FiguresS3/S4 routing, scaffold length and lattice need independent inspection; cannot infer conventional scope from caDNAno use alone.',
 ['Inspect actual FigS3/S4 maps and main Methods; verify scaffold identity, layer topology, packing and source model files.','Keep simulated single/double-layer and graphene-sandwich systems separate from synthesized origami evidence.','Do not translate reported temporary breakpoint operations into NADOC authoring; this task is literature review only.']),
('10.1021/acsnano.6b06861','7340837-nn6b06861_si_001.pdf','7340837','26-page SI pp2–3AuNR functionalization/electrophoresis; pp6–10FigS1–S7captions; p20sequence section start; pp22–26role-label inspection',
 'Tripod SI documents reversible30/60/90degree symmetric conformations, released/unlocked R30/R60/R90 states and asymmetric30-60-60,60-60-90,30-90-90,60-90-90 conformations. AuNR load1/2/3 is separate functionalization. Sequences start p20 with core-1 and continue to core-119 onp22; role labels distinguish biotin handles, three AuNR-handle groups, angle-setting/releasing strands, vertex and End rows. Labels and captions were inspected, not full strand coverage or topology. Core scaffold/lattice/parent design require main-paper review; no independent core count inferred from angles.',
 ['Acquire main Methods and identify tripod scaffold, bundle topology and parent design.','Map complete common-core/vertex/end sequences plus angle-specific locks/releases and AuNR/biotin handles for each condition.','Inspect sequence formatting and microscopy images visually; text/caption extraction is not complete design verification.'])]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for doi,name,fid,loc,note,qs in NOTES:
  p=pubs[doi];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  p.update(review_stage='design_sources_reviewed',relevance='design_bearing',publication_type=['journal_article'],design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=qs,reviewer='Codex primary SI named-section inspection',run_id='B0010',date=L.DATE)
  L.upsert('publication_reviews',p,'Review actual computational/experimental sources with explicit variant and completeness limits')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0010');b.setdefault('completed_actions',[]).append('Reviewed computational graphene-nanopore and experimental AuNR-tripod SI named sections; no complete sources certified. Enumerated210references from4local XML sources.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review13remaining selected ACS source sets and6low/broad B0010records','NanoporeFigS3/S4 and tripod main/core/angle-specific sequence mapping','Resolve205reference targets and recurse discovery','Continue FNANO2013, abstract books and author/forward routes'])
 L.upsert('batches',b,'Checkpoint6/25 first passes plus uncapped local bibliography enumeration')
 L.atomic(L.HERE/'batch_0010_acs_first_audit.json',json.dumps(dict(batch_id='B0010',first_pass_count=6,input_count=25,complete_sources_certified=0,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
