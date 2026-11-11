"""Exclude short peptide-DNA locks while preserving origami citation leads."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acscentsci.9b00964';rid='B0016';path=L.ROOT/'assets/sources/pre2020-expansion/PMC6978833.xml';root=E.parse(path).getroot()
 ev=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6978833/fullTextXML','Main Introduction, Results including Figures1-5 and Discussion inspected; XML epub2019-12-23. Origami nanorobots are prior-work refs8-9, not current experimental platforms.')
 si=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/20394732-oc9b00964_si_001.pdf','https://ndownloader.figshare.com/files/20394732','SI experimental procedures, FiguresS1-S6 captions and TableS1/S2 read. Short peptide-conjugated oligos, duplex/triplex switches and cell/microdroplet assays; no origami staple set. No independent base-by-base sequence audit.')
 note='Three pH-responsive bivalent peptide-DNA antibody locks (pHAbs1/2/3) use short duplex/triplex-forming oligonucleotides and HA peptide epitopes. pHAbs1 uses20bpduplex/15ntoverhang; pHAbs2 intermolecular20nttriplex; pHAbs3 has a short scaffold oligo, base and triplex-forming strand, with mismatch and20/40/60percentTAT variants. Scaffold here names a short linker strand, not a scaffolded origami object. SI14TableS1 provides these oligos and TableS2 their peptide-conjugate masses; methods describe conjugation, antibody/cell labeling and PDMS microdroplets. Salmon-testes DNA is a nuclease scavenger, not an authored origami. Main Introduction refs8-9 credit prior Douglas2012 and Amir2014origami nanorobots. The present experiments do not build, modify or reuse origami; exclude from design-bearing census and narrow catalog while retaining all citations as leads.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='main_XML_and_SI_available',rationale=note,reviewer='Codex main text and SI methods/sequence-table exclusion audit',run_id=rid,date=L.DATE,unresolved_questions=['Reconcile bibliography leads independently; do not attribute cited nanorobot designs to this publication.'])
 for e in [ev,si]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence'].update(date='2019-12-23',primary_verified=True,xml_epub='2019-12-23',xml_ppub='2020-01-22',xml_date_evidence=ev,meaning='Explicit publisher-deposited XML epub date precedes2020issue.')
 L.upsert('publication_reviews',p,'Exclude experimentally nonorigami peptide-DNA switches on inspected evidence')
 refs=root.findall('.//ref-list/ref');assert len(refs)==46
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='B0016:phlocks:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:phlocks:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='XML reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all46references without relevance cap')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed17of25: pH peptide-DNA locks excluded after main/SI scope audit;46references retained, including Douglas2012/Amir2014 prior origami work.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' pHlocks: current short duplex/triplex peptide conjugates and cell assays checked against SI procedures/TableS1; origami appears as cited prior work only.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining8B0016inputs; next10.1021/acsabm.9b01171.','Reconcile retained citation leads, including Douglas2012/Amir2014origami work.','Continue author histories and balanced backlog; FNANO deferred.']);L.upsert('batches',b,'Save17of25 and audited exclusion');print(L.validate())
if __name__=='__main__':main()
