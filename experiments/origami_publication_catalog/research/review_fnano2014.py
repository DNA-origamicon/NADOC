"""Progressive FNANO2014 transcription with source-label and withdrawal audit."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=json.loads((L.HERE/'fnano2014_transcription.json').read_text())
 reviewed=sorted({int(r[0]) for r in rows});path=L.ROOT/'assets/research-20261105/FNANO14schedule.pdf'
 pages=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,check=True).stdout.decode().split('\f');audit=[]
 for page in reviewed:
  a=Counter(r[2] for r in rows if int(r[0])==page);c=Counter()
  for line in pages[page-1].splitlines():
   if 'Refreshments' in line:continue
   m=re.search(r'\b(Poster\b|Contributed|Invited|Keynote)',line[:38])
   if m:c[m[1].lower()]+=1
  assert a==c,(page,a,c)
  audit.append({'page':page,'transcribed':dict(a),'source_labels':dict(c),'counts_match':True})
 existing={p['registry_key'] for p in L.read('publication_reviews')};keys=[];evs=[]
 before=L.counts()
 for page,day,kind,author,title in rows:
  ev=evidence(path,'https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO14schedule.pdf',f'PDF p{page}; April{day} program entry; first-listed author only, not necessarily speaker')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2014:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  withdrawn=author=='Anton Kuzyk' and title=='Reconfigurable 3D plasmonic metamolecules'
  if key not in existing:
   L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],presentation_status='withdrawn_in_program' if withdrawn else 'listed_in_program; occurrence_unverified',date_evidence={'date':'2014-04-'+day,'source':ev,'primary_verified':True,'meaning':'Program date, not verified presentation occurrence or first public availability'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Program title and first-listed author inspected; full author list/speaker roles, abstract and design sources pending. All named entries retained without keyword filtering.'+(' WITHDRAWN label confirmed on rendered PDFp1; not evidence that this poster was presented.' if withdrawn else ''),reviewer='Codex chronological source transcription',run_id='fnano-2014',date=L.DATE,unresolved_questions=['Inspect full author list and speaker typography; first-listed author can differ from presenter.','Locate abstract and reconcile journal/preprint counterpart using primary evidence; verify design contribution.'],legacy_record={}), 'Retain auditable conference lead without eligibility or presentation-occurrence inference')
  L.upsert('discovery_edges',dict(edge_id='fnano2014:'+key,source_key='fnano-2014',target_key=key,relation='conference_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2014',date=L.DATE),'Retain all transcribed conference entries including withdrawn lead')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2014')
 run.update(pagination={'pages':10,'pages_reviewed':reviewed,'all_named_scientific_entries_retained_on_pages':reviewed,'remaining_pages':[p for p in range(1,11) if p not in reviewed]},retrieved_count=len(rows),deduplicated_additions=len(rows),additions_unit='Uncertain program entries, including withdrawn poster; not eligible works',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='All10 pages transcribed:140named entries including withdrawn Kuzyk poster visually confirmed. JanJeppesen p3 remains Monday14, not Tuesday15. Unnamed award address p8, abstracts, full authors and counterparts pending.')
 L.upsert('discovery_runs',run,'Checkpoint bounded conference review without claiming complete2014 coverage')
 b=next((b for b in L.read('batches') if b['batch_id']=='DISC0006'),None)
 if b is None:b=dict(batch_id='DISC0006',date=L.DATE,status='in_progress',input_keys=[],selection='Chronological FNANO2014 program transcription; no keyword cap',completed_actions=[],before_counts=before,unresolved_keys=[],exclusion_audit={'sample':[],'reason':'No final exclusions from titles.'})
 for k in keys:
  if k not in b['input_keys']:b['input_keys'].append(k)
  if k not in b['unresolved_keys']:b['unresolved_keys'].append(k)
 action=f'Transcribed{len(rows)}entries on pages{reviewed}; checked source label counts and visually confirmed withdrawn poster.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['FNANO2013 chronological program transcription','Unnamed ISNSCE award address p8; full-author/speaker roles and abstract book','Journal/preprint counterpart matching; maintain B0010 balanced review queue'])
 L.upsert('batches',b,'Save resumable conference-discovery batch')
 L.atomic(L.HERE/'fnano2014_schedule_audit.json',json.dumps(dict(pages=audit,total_transcribed=len(rows),source_page_total=10,withdrawn_program_entries=1,scope='All10 pages transcribed; unnamed award address p8 unresolved; no abstract-book or counterpart closure',validation=L.validate(),counts=L.counts()),indent=2)+'\n')
 print(L.validate())
if __name__=='__main__':main()
