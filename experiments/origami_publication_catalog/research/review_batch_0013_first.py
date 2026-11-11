"""Two downloaded supplements inspected; exact source sets remain open."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[('10.1021/acsami.8b03585','12264080-am8b03585_si_001.pdf','12264080','Entire5-page SI text/captions, FigS1 positions and TableS1',
 'Triangular Rothemund-parent origami carries12fluorophore positions in a3x4array. FigS1 lists t-4s3g,t-3s4e,t-2s3g,t-1s4e; t-4s5f,t-3s6e,t-2s5f,t-1s6e; t-4s7f,t-3s8g,t-2s7f,t-1s8g. Staples have5prime(AAT)7or(CAA)7extensions and separate dye-bearing complementary oligos; TableS1 lists FAM,Cy3,C343 oligos. Array sizes/dye occupancy are modifications on a triangular platform, not automatically separate cores. Smaller-array exact subsets and base staple/scaffold sources require main/parent review. SI does not supply complete triangular base sequences.'),
('10.1021/jacs.8b05429','12273029-ja8b05429_si_001.pdf','12273029','30-page SI contents and pp3–8,14,22–23,28–30; full table rows not audited',
 'Enzyme channeling origami platform supports G6pDH/LDH pairs with10,25,35,40nm horizontal spacings, two docking staples per enzyme. TableS3 assigns G6pDH152/153; LDH127/126,91/90,67/66,55/54 respectively. HJ probe139and azobenzene-modified163-B4X are distinct functional components; TablesS1/S2 list azobenzene and Holliday-junction strands including NAD+ linkage via amino-T0/T10/T20arms. Ori-FAM control uses native hybridizing DNA rather than azobenzene strands. TableS4 supplies unmodified sequences with noncontinuous numbering (13–204 then217–226 in inspected ranges), not proof of a complete build list. Exact scaffold, core map, omissions/replacements and native source remain unresolved; spacing and cofactor-arm variants not counted as independent cores.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc);p=pubs[key]
  if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main article, native/parent sources, exact scaffold and all variant compositions.','Audit complete base and replacement oligo sets against diagrams; resolve narrow catalog eligibility.','Enumerate bibliography and follow backward/forward citations and author routes.'],reviewer='Codex named SI sections and tables',run_id='B0013',date=L.DATE)
  L.upsert('publication_reviews',p,'Record primary supplement design evidence without source-completeness inference')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0013');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='First2of25inputs inspected: FRET triangular arrays and light-driven enzyme channeling supplement; no complete-source certifications.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],validation=[L.validate()],next_queue=['nl8b01374multivalent tension probes and remaining12ACS SI','Ten rotating2015records','All source and discovery followups; FNANO2010'])
 L.upsert('batches',b,'Save2of25first-pass coverage and concrete remaining queue')
 L.atomic(L.HERE/'batch_0013_first_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=2,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
