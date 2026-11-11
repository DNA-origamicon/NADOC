"""FRET repair platform; preserve primary printed2019date versus current2020history."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/jacs.9b09093';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/20550705-ja9b09093_si_001.pdf'
 se=evidence(path,'https://ndownloader.figshare.com/files/20550705','SIcaptions1-6,FigureS14/TableS1 pages16-19,TableS5caption/organization23-29 and references30 inspected. Not fullkinetic results or independent base-level audit.')
 te=evidence(L.ROOT/'assets/research-20261105/bartnik-thesis.pdf','https://edoc.ub.uni-muenchen.de/26670/1/Bartnik_Kira.pdf','Thesis2020title; originalJACSpaperreprint PDF88/printed815 explicitlyPublishedDecember4,2019; PDF90/printed817 designparagraph and Resultsopening read. Remainingmainpages not fullyread.')
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');rows=[]
 for i in range(22,29):
  for kind,num in re.findall(r'\b(Oligo|Endcap)\s+(\d+)\b',pages[i]):rows.append(dict(kind=kind,number=int(num),pdf_page=i+1))
 assert len(rows)==225;assert {r['number'] for r in rows if r['kind']=='Oligo'}==set(range(1,186));assert {r['number'] for r in rows if r['kind']=='Endcap'}==set(range(1,41))
 L.atomic(L.HERE/'fret_frame_source_index.json',json.dumps(dict(evidence=se,rows=rows,limitations='Name/page index only. Wrapped DNAsequence rows not reconstructed; endcaps10/32biotin and assaystrandsTableS1 require independent sequence verification.'),indent=2)+'\n')
 note='Two-layer p7560 DNA origami frame with an opening and two inward protrusions supporting approximately80nt DNAduplex repair substrates. TableS5 lists185Oligo labels and40Endcap labels; terminalT4spacers reduceaggregation,Endcaps10/32carrybiotin for immobilization. TableS1 supplies separate fluorophore/phosphate assaystrands:0/4/6/8ntstickyends,plus/minus2or10nt length variants,hairpin andrestrictionenzyme versions,andfreedsDNAcontrols. Cy3b/Atto647N labels distinguish ligation states; assay-substrate changes do not automatically mean newframe routings. Main reprint says inspired by designsrefs25-27,not proven identicalreuse. NativecaDNAno,fullscaffold/staple mapping and exactframepacking pending. SI describes2MDmovies notacquired in thispass.'
 qs=['Review remainder of acquiredmainreprintPDF88-98 and refs25-27 for dimensions/packing,parentrelationships and completebibliography.','Reconcile printedPublishedDecember4,2019 with currentACShistory/PubMedJanuary2,2020; primaryreprint supports pre2020availability but exacthistory remains conflicting.','Acquire nativecaDNAno and twoMDmovies if publicly available; avoid assuming downloadedPDF is fullsupplement inventory.','Audit wrapped225TableS5sequence rows,biotin/endcap modifications andTableS1assays independently.','Apply narrow whole-frame lattice/source scope explicitly; no catalogpromotion from two-layer label alone.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',access='SI_and_mainreprint_in_public2020thesis_available; fullmainreview_pending',rationale=note,reviewer='Codex targetedSI and originalpaperreprint review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 for ev in [se,te]:
  if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(primary_verified=False,printed_publication_date='2019-12-04',printed_date_evidence=te,current_publisher_online='2020-01-02',current_publisher_url='https://pubs.acs.org/doi/abs/10.1021/jacs.9b09093',meaning='Primarypaperreprint explicitly2019; conflictingcurrentonlinehistory2020retained,do not exclude solely2020issueyear. InstituteannouncementDecember12,2019corroborates viaweb but local403.')
 L.upsert('publication_reviews',p,'Retain frame sources and competing cutoffdate evidence')
 did='RDE0067';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['Two-layer p7560frame with inward DNArepair substrates','0/4/6/8ntoverhang and alteredlength/hairpin/restriction substratevariants'],identity_status='Frame sourcegroup plus distinct assayvariants; exactparent and framevariant mapping unresolved',lattice_decision='Two-layer frame explicitSI23/main817; exactpacking and whole-object eligibility pending.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[se,te],evidence=[se,te],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Preserve frame sourcegroup and substrate distinctions')
 refs=[('1','GrantBJ etal.Bio3d:anRPackage for Comparative Analysis of Protein Structures.Bioinformatics2006,22,2695-2696.'),('2','DouglasSM,DietzH,LiedlT,HogbergB,GrafF,ShihWM.Self-Assembly ofDNAIntoNanoscaleThree-DimensionalShapes.Nature2009,459,414-418.')]
 for n,c in refs:
  L.upsert('discovery_edges',dict(edge_id='B0016:fret:SIref'+n,source_key=k,target_key='citation:fret:SI:'+n,relation='cites',citation=c,evidence_url=se['url'],local_file=se['local_file'],sha256=se['sha256'],locator='SI30reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain2SIreferences')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed15of25: LiedlFRETframe SI and targetedmainreprint;185oligos40endcaps indexed; primaryprintedDecember4,2019 conflictscurrentJanuary2020history,retained. Bartnik2020thesis acquired publicly.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review remainderBartnikmainreprintPDF88-98,parentrefs25-27.','Remaining10B0016inputs; next10.1021/acsami.9b20707.',*qs]);L.upsert('batches',b,'Save15of25progress with cutoffdate evidence');print(L.validate())
if __name__=='__main__':main()
