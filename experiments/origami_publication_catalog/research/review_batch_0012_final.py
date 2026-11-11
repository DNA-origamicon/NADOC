"""Finish first-pass screening; source completeness and discovery remain open."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1186/1477-3155-12-4','review','fulltext_reviewed','background_or_review','PMC3938474.xml','Abstract, section survey, DNA origami attribution and protein tetrahedron discussion',
 'Review compares designed DNA and protein assemblies. DNA origami construction and applications are attributed to earlier references26–30 and41–44. The concatenated-polypeptide tetrahedron discussed under protein origami is not a DNA-origami design. No new DNA design inferred from the inspected review passages.'),
('10.1364/oe.22.029081','journal_article','metadata_screened','design_bearing',None,'PubMed25402146 abstract and bibliographic record',
 'Primary abstract explicitly reports validation of supercritical-angle localization microscopy with DNA origami tetrahedra, after fluorescent-bead calibration. This establishes origami reuse. Exact tetrahedron parent, labeling, dimensions, sequences and native source remain uninspected. Issue date2014-11-17 is supported; exact first-online day requires primary confirmation.'),
('10.1371/journal.pone.0094819','journal_article','fulltext_reviewed','not_origami','PMC3986227.xml','Abstract, Results inspection, complete Methods, Discussion origami context and supplementary-table caption',
 'Experimental work concerns Haloferax volcanii genomic DNA as phosphate storage and nutrient source, chromosome copy numbers and desiccation survival. Methods describe genomic-DNA extraction, culture, qPCR, polyphosphate and ribosome measurements; supplementary TableS1 contains replicon-quantification primers. Discussion cites DNA origami as an example of non-genetic DNA uses (ref34), without using an origami construct in these experiments. Same-agent second-pass Methods/Results scope audit supports exclusion from the design census; the citation remains a discovery lead.'),
('10.1517/17460441.2015.998195','review','metadata_screened','background_or_review',None,'Publisher Review label/abstract/online date and PubMed25549544',
 'Review surveys high-speed AFM studies including DNA origami scaffolds for molecular dynamics. Primary publisher gives first online2014-12-31, distinct from2015issue. Highlighted Sannohe2010 G-quadruplex switching citation is a discovery lead. Main text not acquired; no original-design or complete-source claim.'),
('10.1615/critrevoncog.2014011601','review','metadata_screened','background_or_review',None,'Author institutional record, abstract and review type; PMC access challenge saved separately',
 'Author institutional record identifies a review of cancer imaging and therapy nanotechnology. This supports background/review status only; origami passages and full bibliography remain uninspected. PMC4183929 identified but browser retrieval returned a challenge. Exact first-publication day unresolved; January1metadata is not accepted as verified day.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,typ,stage,rel,xml,loc,note in ROWS:
  path=L.ROOT/'assets/sources/pre2020-expansion'/xml if xml else L.HERE/'batch_0012_final_primary.json'
  ev=evidence(path,'https://doi.org/'+key,loc);p=pubs[key]
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=[typ],review_stage=stage,relevance=rel,design_contributions=['uncertain'] if rel=='design_bearing' else [],catalog_eligibility='excluded' if rel=='not_origami' else 'unresolved',access='partial',rationale=note,unresolved_questions=['Enumerate citations and follow primary design/author/counterpart leads.']+(['Inspect complete main/SI and exact design compositions and source availability.'] if rel=='design_bearing' else []),reviewer='Codex primary context or explicit metadata inspection',run_id='B0012',date=L.DATE)
  if key=='10.1517/17460441.2015.998195':p['date_evidence']={'date':'2014-12-31','meaning':'Publisher first online; issue2015','source':ev,'primary_verified':True}
  L.upsert('publication_reviews',p,'Finish rotated first-pass queue with evidence depth and open follow-ups')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0012');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 assert len(b['input_keys'])==25 and all(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys'])
 b.update(status='completed',unresolved_keys=[k for k in b['input_keys'] if pubs[k]['unresolved_questions']],after_counts=L.counts(),validation=[L.validate()],next_queue=['Enumerate FNANO2011 official schedule and acquire abstract sources','Follow supercritical-angle microscopy tetrahedron main/SI and cited parents','Select balanced B0013; retain all B0012 source and citation follow-ups'])
 action='All25B0012 inputs first-pass screened:15ACS and10rotating records. No whole-source completeness certification; publication discovery remains open.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 L.upsert('batches',b,'Complete first-pass queue only, retaining unresolved source/discovery work')
 out=dict(batch_id='B0012',first_pass_count=25,input_count=25,unresolved_followup_count=len(b['unresolved_keys']),complete_source_certifications=0,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'batch_0012_complete_audit.json',json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
