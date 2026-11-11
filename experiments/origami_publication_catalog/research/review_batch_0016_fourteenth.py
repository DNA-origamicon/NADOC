"""Aptamer rectangle SI review and literal source-table consistency audit."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsami.9b20707';rid='B0016'
 path=L.ROOT/'assets/sources/acs-expansion-20261104/20277726-am9b20707_si_001.pdf'
 ev=evidence(path,'https://ndownloader.figshare.com/files/20277726','All32pages extracted text read; FigureS1 PDF6 routing and TableS2 PDF25 visually inspected. Full base-by-base PDF audit and main article remain pending.')
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f')
 regular=[];anchors=[]
 for i in range(26,31):
  regular.extend(dict(name=int(n),sequence=s,pdf_page=i+1) for n,s in re.findall(r'^\s*(\d+)\s+([ACGT]+)\s*$',pages[i],re.M))
 for i in [24,25]:
  anchors.extend(dict(name=int(n),sequence=s,pdf_page=i+1,table='S2' if i==24 else 'S3') for n,s in re.findall(r'^\s*(\d+)-anchor\s+([ACGT]+)\s*$',pages[i],re.M))
 assert len(regular)==202 and len(anchors)==56
 reg={r['name']:r['sequence'] for r in regular}
 mismatch=[r for r in anchors if not r['sequence'].endswith(reg[r['name']])]
 assert [r['name'] for r in mismatch]==[63]
 L.atomic(L.HERE/'aptamer_rectangle_source_index.json',json.dumps(dict(evidence=ev,regular_staples=regular,anchors=anchors,anchor_core_suffix_mismatches=mismatch,limitations='Literal extraction; not a synthesis recipe. TableS1 aptamer/ASO chemical modifications and wrapped rows not transcribed. No bases repaired. Regular-table omitted IDs and actual mixture require resolution.'),indent=2)+'\n')
 note='Single-layer rectangular M13mp18 origami, FigureS1 scaffold/staple routing. FigureS4 gives28Bcl2 and28P-gp ASO anchors plus12MUC1 aptamers at two sides. 5prime anchor extensions replace corresponding regular staples; T4hinges separate binding domains. Disulfide-linked ASOs, FAM imaging ASO, Dox loading and biotin-polyT16 aptamer validation are distinct functional variants. TableS4 contains202regular rows(13-204 and217-226), not226rows; TableS1 contains12targeting staple labels among missing1-12/205-216 ranges. Complete side-staple composition remains unresolved. Both anchor tables give28rows each. Anchor63 in TableS2 duplicates64(visually confirmedPDF25) and disagrees with regular63 in TableS4; all55other anchor sequences end in their same-number regular sequence. Preserve printed discrepancy without repairing. FigureS1/TableS4 cite Lund2010 and Ke2016 as source leads; exact source identity not yet reconciled.'
 qs=['Acquire/read main article and its complete bibliography; verify scaffold length, dimensions, source attribution and design variants.','Resolve regular-table omissions1-12/205-216 versus12aptamer replacements and actual baseline/functionalized mixtures.','Resolve TableS2anchor63 versus TableS4regular63 without inventing correction; audit all chemical modifications and source sequences.','Compare Lund2010 and Ke2016 source designs against existing rectangle groups before asserting identical reuse.','Confirm narrow lattice/source eligibility and native design availability; single-layer rectangle alone does not certify complete sources.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design','reused_design'],catalog_eligibility='unresolved',access='SI_available; main_article_not_reviewed',rationale=note,reviewer='Codex completeSItext plus targetedPDFfigure/table review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2019-12-18',source='ACS Article History and PubMed inspected via web; localPubMed returned challenge',primary_verified=False,issue_date='2020-01-08',publisher_history_url='https://pubs.acs.org/aamick/article/12/1/400/478827/Aptamer-Functionalized-DNA-Origami-for-Targeted',publisher_online_date='2019-12-18',qualification='ACS explicitonlinehistoryDec18; bannerDec9 differs, both pre2020. LocalPubMed challenge rejected, not source evidence.')
 L.upsert('publication_reviews',p,'Review functional rectangle and preserve source discrepancy')
 did='RDE0068';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['MUC1 aptamer rectangle with28Bcl2+28P-gp anchors','Unmodified rectangle, ASO/Dox loaded and biotin validation variants'],identity_status='Provisional sourcegroup; parent rectangle identity and variant composition unresolved',lattice_decision='Single-layer rectangle explicit FigureS2; FigureS1 routing inspected. Exact lattice/source eligibility pending.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Record sourcegroup without implying new independent geometry')
 for n,target,c in [('1','10.1038/nature09012','Lund etal. Molecular Robots Guided by Prescriptive Landscapes. Nature2010,465,206-210.'),('2','10.1002/anie.201603183','Ke etal. Directional Regulation of Enzyme Pathways through the Control of Substrate Channeling on a DNA Origami Scaffold. Angew Chem Int Ed2016,55,7483-7486.'),('3','10.1038/nbt.4071','Li etal. A DNA Nanorobot Functions as a Cancer Therapeutic in Response to a Molecular Trigger in vivo. Nat Biotechnol2018,36,258-264.')]:
  L.upsert('discovery_edges',dict(edge_id='B0016:aptamer:SIref'+n,source_key=k,target_key=target,relation='cites',citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI32reference'+n+'; FigureS1/TableS4 cite1-2',reconciliation_state='matched_existing_registry; design_identity_review_pending',run_id=rid,date=L.DATE),'Retain all3SIreferences without claiming exactreuse')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed16of25: aptamerrectangle SI32pages;202regular and56anchorrows indexed; anchor63 source discrepancy visuallyconfirmed.3SIreferences matched existingregistry.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining9B0016inputs; next10.1021/acscentsci.9b00964.',*qs]);L.upsert('batches',b,'Save16of25 and unresolved source consistency');print(L.validate())
if __name__=='__main__':main()
