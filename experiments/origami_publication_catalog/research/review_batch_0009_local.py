"""Primary XML section review of five rotated B0009 records."""
import ledger as L
from review_batch_0001 import evidence

NOTES=[
 ('10.1091/mbc.e13-03-0155','PMC3842987','background_or_review',['perspective'],'Abstract; Introduction; nucleic-acid scaffold paragraph',
  'Introduction explicitly identifies a Perspective reviewing synthetic cellular organization. The origami paragraph attributes dynein/kinesin experiments to Derr2012, rather than presenting an executed origami design in this article.',
  ['Reconcile Derr2012 citation and inspect its primary origami cargo design.','Enumerate full bibliography for further discovery.']),
 ('10.1101/gad.226837.113','PMC3841729','background_or_review',['review_article'],'Abstract/editorial summary; Box1 DNA assembly discussion; Discussion',
  'Primary abstract explicitly describes a review. DNA assembly discussion summarizes Rothemund2006, Dietz2009 and Douglas2012 alongside DNA bricks. These are attributed examples, not new origami cores; XML generic research-article label does not override the article content.',
  ['Enumerate bibliography and reconcile discussed source papers.','Keep DNA bricks distinct from scaffolded origami in any downstream source review.']),
 ('10.1083/jcb.2002pi','PMC3549966','background_or_review',['interview','news'],'Entire interview body, especially MASTERING THE MOTOR',
  'Interview reports the lab combining origami artificial cargoes with motor ensembles but supplies no particular routing, component set, design figures or source files. Retained as an author/lab discovery lead, not proof of a complete design or a newly introduced core.',
  ['Follow Reck-Peterson lab publication history and reconcile specific motor-ensemble cargo publications; interview does not establish exact identity.']),
 ('10.1093/nar/gkt592','PMC3794576','design_bearing',['journal_article'],'Introduction; Methods materials/annealing; Results frame design and Fig1; refs46–47',
  'Results explicitly reuse the earlier origami frame: M13mp18 scaffold, approximately40x40nm internal space, missing-corner orientation marker, two pairs of32nt connection sites. Internal G-mismatch duplexes and KCl-dependent quadruplex formation are assay elements; top67nt and bottom67/77nt duplex variants are not separate frame cores. Ref46 identifies the original frame method and ref47 another application.',
  ['Acquire supplementary DOC and inspect full frame/staple and G-repeat variant tables.','Map exact frame source to Endo2010 DOI10.1021/ja907649w, and distinguish any interface changes from core reuse.','Verify lattice/routing and synthesis completeness before catalog eligibility.']),
 ('10.1093/nar/gkt1269','PMC3936709','design_bearing',['journal_article'],'Introduction; Methods modeling framework; Results seven-helix antenna and megadalton FRET cascade/Fig7; Conclusion; Availability; refs3,15',
  'Computational study evaluates an existing rectangular origami FRET switch from Stein2011(ref15) using CanDo-derived geometry and ATTO488/565/647N plusAF750 dyes. Separate seven-helix antenna(ref3) self-assembles from19oligos; it is not automatically a long-scaffold origami core. Origami model reuse is substantive design evidence; no new experimental synthesis or new core is inferred. Availability says atomic models available through CanDo, while modeling/dye/optical software is on request.',
  ['Acquire supplementary ZIP and inventory actual files; extraction is not source completeness.','Review parent10.1021/ja1105464 and match exact dye configurations and rectangular core.','Keep19oligo seven-helix antenna10.1021/ja1115138 separate from origami FRET switch.','Verify online versus2014issue dates independently.'])]

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for doi,pmc,rel,types,locator,note,questions in NOTES:
  p=pubs[doi];path=L.ROOT/'assets'/p['legacy_record']['xml_file'];ev=evidence(path,'https://pmc.ncbi.nlm.nih.gov/articles/'+pmc+'/',locator)
  p.update(review_stage='fulltext_reviewed',relevance=rel,publication_type=types,design_contributions=['reused_design'] if rel=='design_bearing' else [],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=questions,reviewer='Codex primary XML named-section inspection',run_id='B0009',date=L.DATE)
  L.upsert('publication_reviews',p,'Review primary content across low-keyword/broad rotation; preserve source gaps and distinct publication types')
 for source,target,locator in [('10.1093/nar/gkt592','10.1021/ja907649w','Results same frame and ref46'),('10.1093/nar/gkt1269','10.1021/ja1105464','Results origami FRET cascade/Fig7 and ref15')]:
  ev=pubs[source]['evidence'][0]
  L.upsert('discovery_edges',dict(edge_id='reuses_design_from:'+source+':'+target,source_key=source,target_key=target,relation='reuses_design_from',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=locator,reconciliation_state='bibliographic_parent_matched; exact_variant_pending',run_id='B0009',date=L.DATE),'Trace explicitly attributed parent without counting application as new core')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0009');b.setdefault('completed_actions',[]).append('Reviewed five local primary XML records: Perspective, review, interview, G-quadruplex frame reuse and computational origami FRET reuse.')
 b.update(after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'],next_queue=['Review remaining5low/broad records and15ACS supplements.','Acquire gkt592DOC and gkt1269ZIP; inspect parents/variants.','Continue FNANO2014 and backward/forward/author discovery.'])
 L.upsert('batches',b,'Checkpoint5/25first passes with explicit depth and source follow-ups');print(L.validate())
if __name__=='__main__':main()
