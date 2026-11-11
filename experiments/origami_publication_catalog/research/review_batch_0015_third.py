"""PX exclusion and rectangle seeding source review."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1021/acs.biochem.9b00057','14498645-bi9b00057_si_001.pdf','14498645','SI Fig S2,S5–S11; Note2 sequences and Notes3–4 modeling description; references','not_origami','Four-stranded PX-6:5 DNA consists of PX1/PX4 at28nt and PX2/PX3 at27nt. Half-turn versions use16/15/15/16nt; 60nt complementary duplexes are controls. Fluorescent strand substitutions and enzyme binding are experimental variants, not origami designs. Fig S2 proposes supercoiled-plasmid relaxation into a PX shaft; this schematic is not evidence of a constructed origami. Same-agent exclusion audit rechecked Note2 sequence lengths and Fig S5 assembly. Public code/PDB Dropbox link is mentioned in Note3 but not fetched or executed. Main article and citation review remain pending.'),
('10.1021/acs.langmuir.8b03804','14534945-la8b03804_si_001.pdf','14534945','SI S1 Fig S1 caption; S2 sequence introduction; Fig S2/S3 captions; complete named sequence blocks and reference1','design_bearing','SI explicitly reuses Rothemund2006 rectangle, omitting selected staples during pre-annealing then injecting horizontal/vertical subsets in AFM liquid cell. Lists specify large/small pores and half rectangles with/without seam; caption also describes half plus one-third/two-thirds of remaining half. Missing regions retain free scaffold, so these are partial-folding states rather than proof of scaffold deletions. Extracted table has225 base rows,56 large-pore omissions,14 horizontal and14 vertical add-back rows,20 small-pore omissions,96 half-rectangle omissions and33 additional no-seam rows. Named sequences match base table after small-pore t-prefix normalization; counts are extracted rows, not a certified unique synthesis recipe. Fig S1 says the no-seam half fails room-temperature growth. Exact scaffold identity/length, native maps, omission overlap, color-map assignments and variant completeness remain unresolved.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,rel,note in ROWS:
  p=pubs[key];e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  if e not in p['evidence']:p['evidence'].append(e)
  if rel=='design_bearing':
   ev=evidence(L.HERE/'la8b03804_table_audit.json','https://doi.org/'+key,'Read-only text row extraction and name/sequence comparison; not geometry validation')
   if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance=rel,design_contributions=['reused_design','modified_design'] if rel=='design_bearing' else [],catalog_eligibility='unresolved' if rel=='design_bearing' else 'excluded',access='partial',rationale=note,unresolved_questions=['Inspect main and upstream design sources; verify variant-specific geometry and source completeness where applicable.','Enumerate backward/forward citations and author histories.'],reviewer='Codex named SI sections; same-agent methods/sequence exclusion audit',run_id='B0015',date=L.DATE)
  L.upsert('publication_reviews',p,'Record source-specific evidence with scope and extraction limits')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('Inputs5–6 inspected: PX-DNA exclusion and rectangle seeding/removal/add-back lists;6of25 first passes saved.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['acsami.8b21724; remaining9ACS and10rotating2015 inputs','FNANO2010 enumeration,234CV identity leads, prior source/citation followups'])
 L.upsert('batches',b,'Save6of25 progress and source followups')
 L.atomic(L.HERE/'batch_0015_third_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=6,input_count=25,exclusion_audit='PX Note2 sequences and Fig S5 assembly manually rechecked; main pending',validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
