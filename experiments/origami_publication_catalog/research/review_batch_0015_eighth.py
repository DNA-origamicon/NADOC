"""Finish the fifteen ACS first passes, retaining source-completeness checks."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1021/acsomega.9b01166','15591776-ao9b01166_si_001.pdf','15591776','SI FigS1–S3 captions; modified/unmodified sequence blocks S4–S7; parent referenceS8','Cross-shaped origami platform bears ten modified ssDNA probes at RC-M27/37/49/57/68/29/38/50/58/70. SI supplies unmodified RC-M and AS sequences and cites Liu/Zhong/Wang/Seeman2011 Crystalline two-dimensional DNA origami arrays for strand numbering. Probe modifications, target/mismatch miRNAs and electrode-concentration optimization are distinct assay components/conditions, not separate cores. Sequence presence is not complete-source proof: exact probe polarity/complementarity, attachment chemistry, scaffold identity/length, full replacement map and parent routing require main/upstream review. FigS1 supports cross-shaped object; narrow lattice/source eligibility remains unresolved.'),
('10.1021/acs.nanolett.9b00172','15638255-nl9b00172_si_001.pdf','15638255','SI FigS1–S8 captions; TablesS1–S3 headings and S4–S8 rows; references','SI distinguishes nanorectangle NR,nanodisc ND and nanopillar core with dye-position variants NP1–NP4. FigS7 assigns NP4 dye height53nm; do not infer each NP label denotes a different core. TablesS1–S3 provide unmodified core staples; S4/S5/S6 list eight/eight/six extension-bearing staples respectively for pyrene-oligo binding. S7 gives a25nt pyrene-modified strand. S8 gives ATTO542 label sequences for NR/ND/NP1–NP4; captions additionally use ATTO647N, whose exact modified sequence mapping remains unresolved. NP2 zero/one/eight pyrene experiments and glass/graphene comparisons are attachment controls. Complete base/replacement reconciliation, exact scaffold, parent sources, native routing and lattice eligibility remain pending.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main/native/parent sources; reconcile full core and variant sequence sets, scaffold and maps.','Determine narrow catalog eligibility and follow citations/author histories.'],reviewer='Codex named SI captions and sequence sections',run_id='B0015',date=L.DATE)
  L.upsert('publication_reviews',p,'Save ACS source evidence with variant/source distinctions')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('All15 ACS inputs first-pass source reviewed;10rotating2015 inputs remain; no complete sets certified.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Ten rotating2015 inputs beginning10.3791/52486 and10.3934/matersci.2015.4.448','FNANO2010 enumeration;234CV identities and prior source/citation followups'])
 L.upsert('batches',b,'Save15of25 first-pass progress and rotate to backlog')
 L.atomic(L.HERE/'batch_0015_eighth_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=15,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
