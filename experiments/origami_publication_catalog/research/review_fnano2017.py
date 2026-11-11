"""Transcribe all scientific presentation entries on FNANO2017 schedule, all ten pages."""
import hashlib
import ledger as L
from review_batch_0001 import evidence
ENTRIES=[
('keynote','Friedrich Simmel','DNA-based mechanisms for hybrid molecular robotics'),
('poster','Divita Mathur','Quantum Dot Encapsulation Using a Peptide-Modified Tetrahedral DNA Cage'),
('poster','Chanseok Lee','Modular shape and stiffness variation of DNA origami bundle structures with minimum change of staple sets'),
('poster','Jae Young Lee','Investigating the mechanical properties of DNA nicks using molecular dynamics simulation'),
('poster','Nayan Agarwal','Stabilization of DNA nanoarchitectures'),
('poster','J.V. Le','Probing Nucleosome Stability with a DNA Origami Caliper'),
('poster','Joshua Johnson','Control of DNA Origami Mechanisms via Gold Nanoparticles'),
('poster','Yeongjae Choi','Shape reconfigurable wireframe DNA origami'),
('poster','Abeer Eshra','A reversible DNA seesaw motif with hairpins'),
('poster','Risheng Wang','Self-assembly of heterogeneously shaped nanoparticles into plasmonic metamolecues on DNA origami'),
('poster','Yue Zhao','DNA Triplex Binding Examined in Self-Assembled DNA Crystals'),
('poster','Shohei Kotani','Multi-Arm Junctions for Dynamic DNA Nanotechnology'),
('poster','Yuma Endo','A DNA motif for a membrane-like structure')]
def main():
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2017');ev=evidence(L.ROOT/'assets/research-20261105/FNANO17schedule.pdf','https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO17schedule.pdf','PDF p.1, Monday10 April2017; all13 scientific presentations')
 entries=[(1,*e) for e in ENTRIES]+[(int(p),k,a,t) for p,k,a,t in (line.split('\t') for line in (L.HERE/'fnano2017_remaining.tsv').read_text().splitlines() if line)]
 page_evidence=[]
 for page,kind,author,title in entries:
  ev=evidence(L.ROOT/'assets/research-20261105/FNANO17schedule.pdf','https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO17schedule.pdf',f'PDF p.{page}; named scientific presentation')
  if ev not in page_evidence:page_evidence.append(ev)
  day=10 if page<=3 else 11 if page<=6 else 12 if page<=9 else 13
  key='conference:fnano2017:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14]
  if any(r['registry_key']==key for r in L.read('publication_reviews')):continue
  L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],date_evidence={'date':f'2017-04-{day}','source':ev,'primary_verified':True,'meaning':'scheduled presentation date, not first public release'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Schedule entry only; all named scientific entries on inspected pages retained regardless of keyword. No abstract or full design inspected.',reviewer='Codex schedule transcription',run_id='fnano-2017',date=L.DATE,unresolved_questions=['Transcribe full authors, locate abstract and reconcile journal/preprint counterpart; determine actual design contribution.'],legacy_record={}), 'Preserve conference lead without assuming origami relevance or design completeness')
  L.upsert('discovery_edges',dict(edge_id='fnano2017:'+key,source_key='fnano-2017',target_key=key,relation='conference_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2017',date=L.DATE),'Retain conference lead and unresolved version relationship')
 run.update(closure_state='in_progress',pagination={'pages':10,'pages_reviewed':list(range(1,11)),'all_named_scientific_entries_retained_on_pages':list(range(1,11))},retrieved_count=len(entries),deduplicated_additions=len(entries),additions_unit='uncertain presentation versions, not newly eligible works',evidence=page_evidence,unnamed_sessions=[{'page':6,'label':'Robert Dirks Prize Presentation','status':'speaker/title unresolved'},{'page':9,'label':'ISNSCE Award Address','status':'speaker/title unresolved'}],checkpoint='All ten pages inspected; named scientific presentations retained with first author only. Two unnamed award sessions remain unresolved. Acquire abstracts; complete authors and journal reconciliation. Registration, refreshments, repeated combined poster sessions, meals and business meeting are not additional publication records.')
 L.upsert('discovery_runs',run,'Complete named-entry enumeration across2017 schedule; abstract/identity coverage remains open')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0004')
 keys=[r['registry_key'] for r in L.read('publication_reviews') if r['run_id']=='fnano-2017']
 b.update(input_keys=keys,completed_actions=['Inspected all ten2017 schedule pages and retained all named scientific presentations, regardless of keywords.','Recorded two unnamed award sessions as unresolved gaps.'],after_counts=L.counts(),validation=[L.validate()],unresolved_keys=keys,next_queue=['Locate2017 abstracts and full authors','Resolve unnamed award addresses on pp6/9','Reconcile journal/preprint counterparts; inspect primary experiments'])
 L.upsert('batches',b,'Save full schedule enumeration; discovery follow-up still in progress')
 print(L.validate())
if __name__=='__main__':main()
