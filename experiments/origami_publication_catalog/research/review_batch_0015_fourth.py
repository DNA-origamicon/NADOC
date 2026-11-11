"""RNase carriers and pH capsule SI evidence; no source-completeness claim."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1021/acsami.8b21724','14639699-am8b21724_si_001.pdf','14639699','Methods S2–S4; Fig S1,S5,S8; sequence lists S19–S21; S21 visually inspected','RNase A delivery reuses modified Rothemund rectangles with M13mp18. Fig S1 specifies56 capture strands extended at5-prime and32 MUC1 edge-targeting strands. Sequence list contains54 named AAA capture rows and32 muc1 rows after page-break normalization; this discrepancy remains unresolved. Rows11muc1 and12muc1 are identical, visually confirmed on S21; do not silently repair. Fig S8 reports48±5 loaded proteins per origami, an observed loading value rather than designed site count. Methods write polyT conjugate with terminal-SH while Fig S5 calls it5-prime thiol; orientation also remains unresolved. Parent/native routing, scaffold length and full variant staple replacement require further checks.'),
('10.1021/acsnano.9b01857','14937797-nn9b01857_si_001.pdf','14937797','Supplementary methods; Fig S1–S10 captions; Tables S1–S5 including lock-region composition instructions','Nanocapsule variants share Tables S1/S2 plus exactly one lock-region set: S3 pH latch pHL, S4 complementary closed control clC, or S5 open control opC. Eight matching hairpin/ssDNA latch sets are specified. Fig S9 describes four10nt unhybridized scaffold links between halves. clC exchanges adjacent core strands to obtain correct hybridization direction, not merely different extension sequences. AuNP and HRP are cargo variants; pH/magnesium/plasma conditions are not new DNA cores. Table S3 assigns50[54]–52[49] to both50/1 and51/1 and50[75]–51[83] to both50/2 and51/2 although sequences differ; S5 assigns51/1 and51/2 distinct coordinates. Preserve as coordinate discrepancy pending visual routing comparison. Caption top-half range1–49 also omits core helix0 appearing in S1. Exact scaffold, native files, full sequence-map reconciliation and narrow lattice eligibility remain unverified.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main/native/upstream sources and reconcile noted table, coordinate and modification discrepancies.','Audit all variant synthesis sets and lattice eligibility; enumerate backward/forward citations and author routes.'],reviewer='Codex named SI methods/captions/tables; RNase S21 image inspection',run_id='B0015',date=L.DATE)
  L.upsert('publication_reviews',p,'Save design evidence and unresolved source discrepancies')
 path=L.ROOT/'assets/sources/acs-expansion-20261104'/ROWS[0][1]
 tx=subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True).replace('\f','\n')
 capture=re.findall(r'^AAA-(\d+)[，,]\s*([ACGT ]+)$',tx,re.M)
 apt=re.findall(r'^(\d+)muc1,\s*([ACGT]+)$',tx,re.M)
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('Inputs7–8 source reviewed: RNase rectangle and pH capsule;8of25 first passes saved; discrepancies retained.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['acsnano.9b01025 and remaining7ACS plus10rotating2015 inputs','FNANO2010 enumeration,234CV identities and prior source/citation followups'])
 L.upsert('batches',b,'Save8of25 first-pass coverage')
 L.atomic(L.HERE/'batch_0015_fourth_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=8,input_count=25,capture_rows=capture,aptamer_rows=apt,extraction_limits='pdftotext named row count after page-break normalization; not complete recipe certification',validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
