"""Targeted review-article scope audit; retain uncapped bibliography."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nrg1892';rid='B0016';path=L.ROOT/'assets/sources/pre2020-expansion/PMC7097529.xml';r=E.parse(path).getroot()
 ev=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7097529/fullTextXML','Publisher XML review-article type and epub2006-06-13; bodyparagraphs26-37 structural/scaffolding discussion includingFigure5/6captions and concludingparagraphs51-54 inspected. Remaining sequence/folding/computation sections not fully read.')
 note='Review of designed DNA molecules; structural discussion attributes scaffolded smiley/worldmap patterns and reproducedFigure5c to Rothemund2006ref42, and 1669nt+five short strand octahedron to ShihQuispeJoyce2004ref43. These are accounts of earlier work, not new experimentally reused origami by this review. Nearby DXtiles, short-strand tetrahedra, nanowires and algorithmic tile arrays are separate motifs; do not classify all as scaffolded origami. Figure5 explicitly states reproduction permissions and provenance. Background/review relevance, excluded from narrow design catalog; no new design group. All82bibliography records retained as leads, independent content/date/scope reconciliation still open.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='background_or_review',design_contributions=[],catalog_eligibility='excluded',access='main_XML_available',rationale=note,reviewer='Codex targeted structuralsection and figureattribution audit',run_id=rid,date=L.DATE,unresolved_questions=['Read remaining review sections if needed for further leads; current classification rests on explicit review type and inspected structural attributions.','Reconcile82bibliographic leads and primary design source evidence independently.'])
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2006-06-13',primary_verified=True,source=ev,meaning='Publisher-deposited XML explicit epub')
 L.upsert('publication_reviews',p,'Distinguish reviewed prior origami designs from new design contributions')
 refs=r.findall('.//ref-list/ref');assert len(refs)==82
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='B0016:nrg1892:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:nrg1892:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all82review references including Rothemund2006/Shih2004')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Processed20of25inputs:19substantive reviews plus1metadataonly. nrg1892backgroundreview classified from structuralsection/figureattribution;82references retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' nrg1892: reviewtype and Figure5reproduction/refs42-43 show earlier designs, no new experimental reuse in inspected section.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining5firstpassinputs:2006solarnews,10.3762/bjnano.10.153,10.3791/58771,10.4049/jimmunol.202.supp.130.13,10.5539/jmsr.v8n4p14.','Next inspect locallyavailable bjnano review while2006news maintext remains unresolved.','Talks collectionfulltext and other sourcegaps remain explicit; priorityauthor/citation discovery ongoing.']);L.upsert('batches',b,'Save20of25processed and review exclusion audit');print(L.validate())
if __name__=='__main__':main()
