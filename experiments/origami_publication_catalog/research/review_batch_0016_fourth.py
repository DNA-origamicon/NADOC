"""Audit antibody methods paper against full main and SI, preserve original-work lead."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acs.bioconjchem.9b00490';rid='B0016';path=L.ROOT/'assets/sources/pre2020-expansion/PMC6753658.xml';r=E.parse(path).getroot()
 ev=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6753658/fullTextXML','All main sections Introduction, Results/Discussion, Conclusions, Materials/Methods read; ref32 explicitly identifies previous DNA-nanostructure application; XML epub2019-08-22.')
 si=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/17489498-bc9b00490_si_001.pdf','https://ndownloader.figshare.com/files/17489498','Entire SI extracted text read: FiguresS1–S18, supplementary methods, TablesS1/S2. Docking/imager oligos and protein coding sequences, not origami staples.')
 note='Full main and SI establish antibody/proteinG-ODN conjugation, purification and cell labeling on A431/Jurkat/HUVEC, with DNA-PAINT/dSTORM on cellular targets. TableS1 contains short docking/imager oligos (10–22nt) and TableS2 proteinG coding sequences; neither is an origami staple list. Origami appears as introductory motivation refs11–15. The claim of decorating DNA nanostructures with antibodies explicitly describes previous work ref32, Rosier2017(10.1039/c7cc04178k), not an experiment in this paper. No origami construction/modification/reuse found after entire main methods/results and SI inspection. Exclude this publication from design-bearing catalog; retain adjacent method and cited original-work leads.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='main_XML_and_SI_available',rationale=note,reviewer='Codex complete main/SI text review',run_id=rid,date=L.DATE,unresolved_questions=['Reconcile2019-08-22XMLepub versus2019-09-03PubMed article date against publisher history; pre2020 unaffected.','Review cited2017Rosier original design application and remaining bibliography; do not transfer earlier design use to this publication.'])
 for e in [ev,si]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence'].update(primary_verified=False,xml_epub='2019-08-22',xml_date_evidence=ev,meaning='Exact first-online date requires reconciliation; XML and PubMed differ, both2019.')
 L.upsert('publication_reviews',p,'Full-text exclusion audit separates cell labeling from previously published origami application')
 refs=r.findall('.//ref-list/ref');assert len(refs)==37
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='B0016:antibody-conjugation:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:antibody-conjugation:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='XML reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain complete37reference list including earlier nanostructure application')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);b['completed_actions'].append('Reviewed6of25: antibody-conjugation main/SI contains cell-labeling oligos, no origami experiment. Exclusion audited;37references retained including prior Rosier2017origami-application lead.')
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' Antibody paper: all main sections and SI text inspected; previous-work statement explicitly traced to ref32.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining19B0016 inputs including clathrin-mimic SI and peptide-fluorophore hydrogel.','Follow Rosier2017ref32 as its own publication; reconcile main date discrepancy.','Continue priority histories/citation routes; human dissertation request pending independently.'])
 L.upsert('batches',b,'Save6of25progress and full exclusion audit');print(L.validate())
if __name__=='__main__':main()
