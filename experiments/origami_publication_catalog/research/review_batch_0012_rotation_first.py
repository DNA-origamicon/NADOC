"""Primary full-text context review of a rotating low-keyword record."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.2142/biophysics.10.69';p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 ev=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC4629658.xml','https://doi.org/'+key,'Abstract; Single molecule force measurement using DNA handle; Fig2caption; Perspectives origami paragraph')
 if ev not in p['evidence']:p['evidence'].append(ev)
 p.update(title=p['legacy_record']['publication'],review_stage='fulltext_reviewed',relevance='background_or_review',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale='Described optical-tweezers assay uses approximately60nm double-strandedDNA handle linking myosin head to200nmbead; biotin/neutravidin and digoxigenin/antibody endpoints are specified. Perspectives says artificial muscle usingDNAorigami is being constructed and will be applied to control myosin-head number/spacing. This is prospective origami discussion, not evidence of a completed origami design/source in this article. Retain as broad background and a lead to cited origami/author work; no design-completeness inference or final catalog exclusion.',unresolved_questions=['Follow refs35/36 and author history for completed artificial-muscle origami studies.','Enumerate remaining bibliography and inspect original cited tweezers study for lineage.'],reviewer='Codex inspected primary context',run_id='B0012',date=L.DATE)
 L.upsert('publication_reviews',p,'Distinguish implemented duplex handle from prospective origami research')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Rotating myosinV article inspected: implemented duplex handle versus prospective origami muscle; retained background with citation/author follow-ups.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['SNPchip138527281815140916092815 and PDB4V5X deposition','Remaining7rotating records with primary evidence','Source completeness and citation/conference follow-ups'],validation=[L.validate()])
 L.upsert('batches',b,'Save16of25first-pass coverage,9unreviewedinputs');print(L.validate())
if __name__=='__main__':main()
