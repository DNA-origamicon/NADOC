"""Balanced B0007 triage; abstracts are leads, never complete designs."""
import ledger as L
from review_batch_0001 import evidence
SPECS=[
('10.1109/memsys.2012.6170236','assets/research-20261105/MEMS2012_TechnicalProgram.pdf','https://www.memsconferences.org/mems2012/program/MEMS2012_TechnicalProgram.pdf','PDF p29 entry93-T','Official program states imaging of50nm DNA-origami squares with10.9MHz probe. Proceedings full text, parent design and sequences have not been inspected.','conference_proceedings_article'),
('10.1115/imece2012-87848','assets/research-20261105/marras-2012-institutional.html','https://ohiostate.elsevierpure.com/en/publications/design-of-dna-origami-machines-and-mechanisms/','Institutional record Abstract and publication metadata','Institutional abstract reports hinge and Bennett four-bar prototype, alongside proposed revolute/prismatic/spherical joint approaches. This conference contribution must be reconciled with later mechanism papers; an abstract cannot certify routing or complete source files.','conference_proceedings_article'),
('10.1126/science.1228638','research/batch_0007_remaining_search2.json','https://pubmed.ncbi.nlm.nih.gov/23112329/','PubMed primary author abstract in saved web response','Author abstract describes origami docking one/two gold nanoparticles and a fluorescent dye. Strong design-bearing lead; full methods and geometry/source details remain uninspected.','journal_article'),
('10.1116/1.3676054','assets/research-20261105/hsq-2012-crossref.json','https://api.crossref.org/works/10.1116/1.3676054','Deposited abstract and title','Publisher-deposited abstract reports DNA-origami immobilization on HSQ with roughness optimization; no specific routing or parent source is supplied in the abstract.','journal_article'),
('10.1149/ma2012-02/44/3251','assets/research-20261105/ecs-2012-crossref.json','https://api.crossref.org/works/10.1149/ma2012-02/44/3251','Container ECS Meeting Abstracts; title; abstract placeholder','This is an invited meeting-abstract record. Crossref type journal-article reflects the serial container; deposited abstract is only Abstract not Available. No design classification follows from the title.','conference_abstract'),
('10.1128/microbe.7.217.1','assets/research-20261105/microbe-2012-crossref.json','https://api.crossref.org/works/10.1128/microbe.7.217.1','Title and bibliographic metadata; no abstract deposited','Metadata lacks abstract/full text. News-like title is not sufficient to classify background relevance or exclude a design; inspect the actual item and trace referenced research.','journal_article_type_unresolved'),
('10.1166/jctn.2012.2264','assets/research-20261105/logic-2012-crossref.json','https://api.crossref.org/works/10.1166/jctn.2012.2264','Title and bibliographic metadata; no abstract deposited','DOI metadata confirms identity but no primary content is available in this deposit. The theoretical/experimental nature of the proposed logic circuit and actual origami substrate remain unresolved.','journal_article')]
def main():
 for key,path,url,loc,note,typ in SPECS:
  p=next(r for r in L.read('publication_reviews') if r['registry_key']==key)
  if p['run_id']!='bootstrap-20261105':continue
  ev=evidence(L.ROOT/path,url,loc)
  p.update(review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',publication_type=[typ],evidence=[ev],rationale=note,unresolved_questions=['Acquire primary full text/source material; establish exact design contribution and parent relationships without inferring from keywords.'],reviewer='Codex inspected metadata/abstract evidence; not design verification',access='partial',run_id='B0007',date=L.DATE)
  L.upsert('publication_reviews',p,'Preserve bounded abstract/metadata triage and actual publication type')
 print(L.validate())
if __name__=='__main__':main()
