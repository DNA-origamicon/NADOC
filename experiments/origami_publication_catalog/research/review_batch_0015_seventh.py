"""Twist-control and binding-site variant source inspection."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1021/acsnano.9b01561','15221726-nn9b01561_si_001.pdf','15221726','SI contents; NotesS1–S3; figure-caption inventory; actual TableS1–S37 headings and selected starting rows','6HB twist study separates FB staples(TableS1) and VB variant tables. S2 is straight; S3–S12 H0 insertions2–20 by2; S13–S20 H6 insertions2–16 by2; S21–S26 H0/H6 deletions2/4/6; S27–S31 six insertions at H1–H5; S32–S37 H0 six-insertion variants with1nt/3nt gaps and1/3,2/3,1 densities. Contents incorrectly labels S18–S20 as10insertions, whereas actual headings specify12,14,16. Preserve this source discrepancy. NoteS3 uses293nm length in twist analysis; this is not a verified scaffold routing length. SI distinguishes CanDo/MD analyses, experimental6HB figures and additional60HB/cross-section analysis; do not count every modeled cross-section as experimentally realized. Full main, scaffold identity, complete per-variant FB+VB reconciliation, native routing and lattice eligibility remain pending.'),
('10.1021/acsami.9b01691','15344021-am9b01691_si_001.pdf','15344021','SI TablesS1–S6 ppS2–S3; results and FigS1–S8 captions','Triangle has seven biotin sites in S1 plus four additional sites in S2; B34 is3-prime, other listed triangle sites5-prime. Rectangle S3 specifies16digoxin labels across15staples:133 carries both5-prime and internal digoxin, explaining count difference. S4 lists10rectangle biotin staples at vertex/rim/surface; S5/S6 list six/eight marker strands respectively. These modification sets and mica/solution assay contexts are not independent core designs. Source inspected provides modified strands but does not establish complete base staple sets, precise scaffold or parent lineage. Main article, native/parent sources and variant-specific composition remain pending; broad design relevance supported, narrow eligibility unresolved.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main/native/parent sources and complete per-variant sequences and scaffold maps.','Resolve lattice eligibility and experimental versus modeled design inventory; follow backward/forward citations and author histories.'],reviewer='Codex named SI sections/headings and modified oligo tables',run_id='B0015',date=L.DATE)
  L.upsert('publication_reviews',p,'Record supported variants and table-label discrepancies without completeness inference')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('Inputs12–13 source reviewed: twist-control variant tables and binding-site modifications;13of25 first passes.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['acsomega.9b01166 and nanolett.9b00172;10rotating2015 inputs','FNANO2010 enumeration;234CV identity leads and all prior source/citation followups'])
 L.upsert('batches',b,'Save13of25 first-pass coverage')
 L.atomic(L.HERE/'batch_0015_seventh_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=13,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
