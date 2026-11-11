"""Resolve aggregate conference identity without treating a partial PDF as coverage."""
import ledger as L
from review_batch_0001 import evidence

def main():
 k='PMC6610276';rid='B0016'
 ev=evidence(L.ROOT/'assets/research-20261105/febs2019-abstracts.pdf','https://pureportal.spbu.ru/files/43668655/Bondarev.pdf','Four-page repository excerpt: cover, issueinformation, poster pages265-266. Issueinformation explicitly maps Talks to10.1002/2211-5463.12674 and Posters to10.1002/2211-5463.12675. This PDF does NOT contain Talks pages2-64.')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 note='Identified as aggregate Talks abstracts of44thFEBS Congress, KrakowJuly6-11,2019, not an individual researcharticle or FNANO program. Saved repositoryPDF only contains issueinformation and posterpages265-266; it supports DOI/type identity, not coverage ofTalks. Publisher issueinformation says abstracts are not peer-reviewed and late-breaking abstracts are omitted. FullTalks text remains inaccessible in attempted routes; no negative relevance inference from absent keywords in wrong excerpt. No design verified or conference abstract promoted into journalarticle.'
 p.update(doi='10.1002/2211-5463.12674',publication_type=['conference_abstract_collection'],review_stage='metadata_screened',relevance='uncertain',catalog_eligibility='unresolved',access='partial_issueinformation_only; talks_fulltext_pending',rationale=note,reviewer='Codex source-identity and access audit',run_id=rid,date=L.DATE,unresolved_questions=['Acquire fullTalks pages2-64, identify individual relevant abstracts and reconcile their journal/preprint sources.','No broad relevance or design-completeness classification from issueinformation or selected posterpages.'])
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2019-07-04',primary_verified=False,source='Wiley issueTOC viaweb: FirstPublished04July2019; savedissueinformationJuly2019',publisher_url='https://febs.onlinelibrary.wiley.com/toc/22115463/2019/9/S1',conference_dates='2019-07-06/2019-07-11',legacy_date='2019-07-01')
 L.upsert('publication_reviews',p,'Correct aggregate publication type and DOI while retaining fulltext access gap')
 b=next(b for b in L.read('batches') if b['batch_id']==rid)
 action='Processed19of25:18source/textreviews plus1metadata-only FEBS Talks collection. Corrected DOI/type; four-page repositoryexcerpt is not Talks, fulltext access remains unresolved.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining6firstpassinputs; next10.1016/s1369-7021(06)71752-7 news and10.1038/nrg1892 review.','Return to PMC6610276 fullTalks access; do not mark its abstracts reviewed.','Priorityauthor/citation routes remain open; FNANO deferred.'])
 L.upsert('batches',b,'Save metadata-only rotation without claiming content review');print(L.validate())
if __name__=='__main__':main()
