"""Evidence-reviewed hydrogel exclusion; preserve main and SI citation leads."""
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsomega.9b01586';rid='B0016'
 path=L.ROOT/'assets/sources/pre2020-expansion/PMC6714519.xml';root=E.parse(path).getroot()
 me=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6714519/fullTextXML','Introduction, complete Results/Discussion and Conclusions text read; refs8/9 cite earlier optical antenna work. XML publication date2019-08-16 has no date-type attribute.')
 se=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/17290484-ao9b01586_si_001.pdf','https://ndownloader.figshare.com/files/17290484','All28pages extracted text read, including TableS3, synthesis/bioconjugation/hybridization methods and computation/spectral captions. Figure pixels not independently audited.')
 note='Experimental assay uses a peptide-fluorophore hydrogel, PEG-linked capture oligonucleotides, and peptide-linked detection oligonucleotides against digested genomic EGFR DNA. SI TableS3 identifies ON1/ON1prime/ON3 capture variants and ON2/ON4/ON5 detection variants; SI11 describes six24mer strands attached to8-armPEG. These are probe conjugates, not origami staples or a scaffold fold. Main Results and SI methods concern hydrogel formation, hybridization, peptide docking and spectroscopy. Origami optical antennas are cited background (refs8/9), not constructed, modified or reused in this experiment. Exclusion supported by main and complete SI text review; retain bibliography for discovery.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='main_XML_and_SI_available',rationale=note,reviewer='Codex main and complete SI text review',run_id=rid,date=L.DATE,unresolved_questions=['Reconcile cited publication identities and follow origami antenna ref9 separately.','XML2019-08-16 publication date is untyped; exact first-online date not independently established.'])
 for ev in [me,se]:
  if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(primary_verified=False,xml_publication_date='2019-08-16',xml_date_evidence=me,meaning='Untyped XML date supports2019; exact first-online date unverified.')
 L.upsert('publication_reviews',p,'Audit hydrogel exclusion from actual experimental components')
 refs=root.findall('.//ref-list/ref');assert len(refs)==51
 for ref in refs:
  n=ref.get('id');dois=[x.text.lower() for x in ref.findall('.//pub-id[@pub-id-type="doi"]')];citation=' '.join(ref.itertext())
  # A numbered reference may combine multiple works: do not collapse ref3 onto its sole DOI.
  target=dois[0] if len(dois)==1 and n!='ref3' else 'citation:hydrogel:'+n
  L.upsert('discovery_edges',dict(edge_id='B0016:hydrogel:'+n,source_key=k,target_key=target,relation='cites',citation=citation,evidence_url=me['url'],local_file=me['local_file'],sha256=me['sha256'],locator='MainXML '+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain51numbered reference entries; bundled ref3 remains unresolved')
 refs_si=[('1','https://www.lumiprobe.com/protocols/nhs-ester-labeling','SI7'),('2','Shoute LCT, Loppnow GR. Phys Chem Chem Phys.2018;20(7):4772-4780.','SI10'),('3','Taskova M, Madsen CS, Jensen KJ, Hansen LH, Vester B, Astakhova K. Bioconjug Chem.2017;28(3):768-774.','SI12'),('4','Okholm A, Kjems J, Astakhova. RSC Adv.2014,4,45653-45656.','SI12'),('5','Dahse et al. Anticancer Res.2008;28(4B):2265-70.','SI13'),('6','Lamiable A, Thevenet P, Rey J, Vavrusa M, Derreumaux P, Tuffery P. Nucleic Acids Res.2016,44,449-54.','SI16')]
 for n,c,loc in refs_si:
  L.upsert('discovery_edges',dict(edge_id='B0016:hydrogel:SIref'+n,source_key=k,target_key='citation:hydrogel:SI:'+n,relation='cites',citation=c,evidence_url=se['url'],local_file=se['local_file'],sha256=se['sha256'],locator=loc+'footnote'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain sixSIfootnotes including web protocol; not all are publication works')
 b=next(b for b in L.read('batches') if b['batch_id']==rid)
 action='Reviewed8of25: hydrogel main and SI text establish probe-conjugate assay without origami experiment;51main reference entries and6SIfootnotes preserved, including Tinnefeld2017nanoantenna lead.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' Hydrogel: main experiments and allSItext inspected; capture/detection conjugates separated from cited origami antennas.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining17of25B0016inputs: next10.1021/acsnano.9b05650 and downloadedSI.','Follow10.1021/acs.analchem.7b04082 as independent Tinnefeld publication; retain bundledref3 for splitting.','Continue priority-author histories and backward/forward citation reconciliation; FNANO deferred.'])
 L.upsert('batches',b,'Save8of25review progress with evidence-backed exclusion');print(L.validate())
if __name__=='__main__':main()
