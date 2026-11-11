"""Inspect the next balanced record; metadata-only XML is not a full-text review."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='PMC7080001';path=L.ROOT/'assets/sources/pre2020-expansion/PMC7080001.xml'
 r=E.parse(path).getroot();assert r.find('body') is None
 doi=r.find('.//article-id[@pub-id-type="doi"]').text
 assert doi=='10.1007/s00249-007-0178-7'
 ev=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7080001/fullTextXML','Entire front metadata inspected; XML has no body. European Biophysics Journal36Suppl1,51-248, Abstracts; explicit epub14June2007; PDF self-uri249_2007_Article_178.pdf.')
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(doi=doi,publication_type='conference_abstract_collection',review_stage='metadata_screened',access='metadata_XML_only; PDF_needed',rationale='Publisher-deposited metadata identifies an EBSA2007 abstract supplement, not a complete design paper. Saved XML lacks body; prior fulltext_evidence_triaged label is not proof of content review. Relevance and design leads remain uncertain pending actual abstracts. Existing conference backlog rotation, not new FNANO discovery.',reviewer='Codex primary XML metadata inspection',run_id='B0017',date=L.DATE,unresolved_questions=['Acquire actual abstract PDF; inspect relevant content and reconcile journal/preprint counterparts without treating abstracts as complete design sources.','Check DOI identity against other registry versions before canonical merge.'])
 p['date_evidence']=dict(date='2007-06-14',primary_verified=True,source=ev,meaning='Explicit publisher XML epub;2020PMC release is not publication date.')
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Correct date,DOI and type; retain absent-body access gap')
 b=next(x for x in L.read('batches') if x['batch_id']=='B0017')
 action='Processed2of25:1source-reviewed Rothemund plus1metadata-only abstract collection PMC7080001;23untouched. Abstract PDF/content still pending.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Next balanced record10.55838/1980-3540.ge.2007.32;23untouched inputs.','Acquire PMC7080001 actual abstract PDF; source XML has no body.','Rothemund remaining SI recipes and24citation leads; author histories continue,FNANO deferred.'])
 L.upsert('batches',b,'Save2of25processed with explicit metadata-only denominator')
 print(L.validate())

if __name__=='__main__':main()
