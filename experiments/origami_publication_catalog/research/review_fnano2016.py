"""Manually transcribed complete named schedule; no title-based relevance filter."""
import hashlib,json,re
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[l.split('\t') for l in (L.HERE/'fnano2016_entries.tsv').read_text().splitlines() if l];pages=(L.ROOT/'assets/research-20261105/FNANO16schedule.txt').read_text().split('\f');audit=[]
 for page in range(1,9):
  trans=Counter(r[1] for r in rows if int(r[0])==page);source=Counter()
  for line in pages[page-1].splitlines():
   m=re.search(r'\b(Poster\b|Contributed|Invited|Keynote)',line[:27])
   if m:source[m.group(1).lower()]+=1
  assert trans==source,(page,trans,source)
  audit.append({'page':page,'transcribed':dict(trans),'source_left_column_labels':dict(source),'counts_match':True})
 L.atomic(L.HERE/'fnano2016_schedule_audit.json',json.dumps({'pages':audit,'total_named_entries':len(rows),'image_checks':[{'page':5,'finding':'Rendered page confirms Patrick D. Ellis poster row; sponsor text overlaps name in source itself.'}],'limitations':['Full authors not yet transcribed.','Poster count is presentation rows, not number of distinct designs/topics.','Combined repeat poster sessions are not counted twice.']},indent=2))
 batch=next((b for b in L.read('batches') if b['batch_id']=='DISC0005'),None)
 if batch is None:
  batch=dict(batch_id='DISC0005',date=L.DATE,status='in_progress',input_keys=[],selection='Every named scientific presentation on all eight FNANO2016 schedule pages; no relevance cap',before_counts=L.counts(),after_counts=None,completed_actions=[],unresolved_keys=[],next_queue=['Complete2016 schedule leads, then abstracts and counterpart reconciliation'],exclusion_audit={'sample':[],'reason':'No exclusions'},validation=[]);L.upsert('batches',batch,'Begin bounded conference enumeration')
 existing={p['registry_key'] for p in L.read('publication_reviews')};edges={e['edge_id'] for e in L.read('discovery_edges')};keys=[];evs=[]
 for i,(p,kind,author,title) in enumerate(rows,1):
  page=int(p);day=11+(page-1)//2
  ev=evidence(L.ROOT/'assets/research-20261105/FNANO16schedule.pdf','https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO16schedule.pdf',f'PDF p{page}, named scientific presentation')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2016:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in existing:
   record=dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],date_evidence={'date':f'2016-04-{day}','source':ev,'primary_verified':True,'meaning':'Scheduled presentation, not first public release'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Schedule lead only; retained irrespective of keywords. Abstract and complete design not inspected.',reviewer='Codex complete schedule transcription',run_id='fnano-2016',date=L.DATE,unresolved_questions=['Transcribe full authors, acquire abstract and reconcile journal/preprint counterparts; assess actual design contribution.'],legacy_record={})
   if author=='Philip Lukeman':record['unresolved_questions'].append('One program row includes virus-binding claws and photocleavable surfaces; determine whether one presentation comprises two separate projects.')
   L.upsert('publication_reviews',record,'Retain named conference entry without design-completeness inference')
  eid='fnano2016:'+key
  if eid not in edges:L.upsert('discovery_edges',dict(edge_id=eid,source_key='fnano-2016',target_key=key,relation='conference_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2016',date=L.DATE),'Save unresolved conference publication relationship')
  if i%20==0:print('saved',i,'/',len(rows),flush=True)
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2016');run.update(pagination={'pages':8,'pages_reviewed':list(range(1,9)),'all_named_scientific_entries_retained_on_pages':list(range(1,9))},retrieved_count=len(keys),deduplicated_additions=len(keys),additions_unit='Presentation leads, not verified design-bearing publications',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],unnamed_sessions=[{'page':4,'label':'ISNSCE Award Address','status':'speaker/title unresolved'},{'page':6,'label':'Robert Dirks Prize Presentation','status':'speaker/title unresolved'}],closure_state='in_progress',checkpoint='All145 named scientific presentation rows retained; full authors, abstracts and counterparts remain open. One combined-topic poster row retained as printed.');L.upsert('discovery_runs',run,'Complete schedule enumeration; broader conference discovery remains open')
 batch.update(input_keys=keys,unresolved_keys=keys,completed_actions=['Read all eight schedule pages; transcribed145 first-author/title presentation rows.','Audited per-page/type counts against source labels; rendered p5 to inspect sponsor-overlapped author name.'],after_counts=L.counts(),validation=[L.validate()],next_queue=['Locate2016 full abstract book and full authors','Resolve two unnamed award sessions and combined-topic Lukeman row','Reconcile named leads to primary journal/preprint evidence','Continue remaining2006–2015 schedules and backward/forward citation routes']);L.upsert('batches',batch,'Checkpoint complete named-entry enumeration with follow-up unresolved')
 print(L.validate(),flush=True)
if __name__=='__main__':main()
