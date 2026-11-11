"""Three primary-source reviews with explicit component/assembly distinctions."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[('10.1021/acs.bioconjchem.8b00418',[('12441533-bc8b00418_si_001.pdf','12441533','Entire10-page SI text/captions; p10sixmodified staple sequences and parent reference')],
 'M13mp18 rectangular origami follows Rothemund assembly; unmodified design/staples explicitly deferred to Wang,Nuckolls,Wind2012Angew51,11325–11327. Six modified staples listed: LEpolyAR205/206/190 withpolyA20 and BE RandomR25/27/28 with20mer random sequence. AuNPthiolated polyT/cRS ratios and lengths vary separately from the origami base. Particle occupancy and unintended dimers sharing anAuNP are outcomes, not additional designed cores. Exact parent base set and all AuNPoligo sequences need primary main/parent reconciliation.'),
('10.1021/acsnano.8b02720',[('12454583-nn8b02720_si_001.pdf','12454583','22-page SI contents/caption survey; pp8–10origami design discussion; pp12–19assembly/cutting context'),('12454580-nn8b02720_si_002.pdf','12454580','13-page sequence supplement headers; cross pp1–4,longrectangle p5onward,shortrectangle p10onward; cross functional rows p4')],
 'Cross-shaped, short rectangular and long rectangular origami platforms support SWNTbinding/cutting. Cross monomers also form1Dpolymers via linkerDNA; assembly not silently counted as another independent core. SI states10.67bp/turn initial design ruptured,10.4improvedflatness; biotin/streptavidin recruits biotin-DNA-wrapped SWNTs, two G-quadruplex staples at top corners catalyze cutting withhemin. Separate sequence PDF lists ordinary/linker/biotin/Gquadruplex components (cross HA1082/1083Gquadruplex). Exact per-shape scaffold, nativeCAD, substitutions, linker subsets and twist corrections not fully audited. G-DNA/nG-DNA/B-DNA wrapping species are distinct from origami staples. SI caption numbering repeatsS14 for polymer cutting; cite PDFpages to avoid ambiguity. No simulation/reconstruction performed.'),
('10.1021/acs.langmuir.8b01933',[('12484508-la8b01933_si_001.pdf','12484508','Entire9-page SI text/captions; FigS6p5; staple listpp5–8; capture setspp8–9')],
 'Origami module measured approximately42.41x51.89nm; FigS6describes domain capture sites and a free groove capturing particles hosted on another module, all extended from3prime ends. SI lists117numbered base staples, separate cap1/cap8sets for AuNP/AuNR,16free-troughcapture strands, five capture sequencesA–E and complementary thiolated particle oligos. AuNPsets add capture tails only topositions2–4 ofeach five-strandgroup, while AuNRsets add them toallfive. Dimers through pentamers and heterogeneous particle arrangements are modular assembly variants; full module scaffold/routing and per-arrangement sequence assignments require main/native audit. Duplicate FigS3labels retained as source ambiguity. No complete build-set or lattice eligibility certification.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,sources,note in ROWS:
  p=pubs[key]
  for name,fid,loc in sources:
   e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
   if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main and original/native sources; exact scaffold/base/variant compositions and narrow eligibility.','Audit full sequence lists against per-variant maps and assembly recipes.','Enumerate bibliography and follow citations/author histories.'],reviewer='Codex specified SI context inspection',run_id='B0013',date=L.DATE)
  L.upsert('publication_reviews',p,'Record primary component distinctions and unresolved composition')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0013');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='Next3SI records inspected:AuNPaddressability,SWNTcutting andmodularplasmonics; cumulative8of25screened.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],validation=[L.validate()],next_queue=['Remaining7ACS startingjacs8b06146','Ten rotating2015records','FNANO2010 and all source/discovery followups'])
 L.upsert('batches',b,'Save8of25firstpasses,17unreviewed inputs')
 L.atomic(L.HERE/'batch_0013_third_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=8,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
