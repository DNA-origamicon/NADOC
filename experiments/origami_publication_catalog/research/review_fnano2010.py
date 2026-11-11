"""Visually audited chronological program transcription; no relevance filtering."""
import hashlib,json,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=json.loads((L.HERE/'fnano2010_transcription.json').read_text());path=L.ROOT/'assets/research-20261105/FNANO10schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO10schedule.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f')
 total=len(pages)-(not pages[-1].strip());assert total==19
 reviewed=sorted({r[0] for r in rows});expected={1:4,2:11,3:11,4:12,5:7,6:8,7:9,8:12,9:11,10:12,11:11,12:10,13:7,14:11,15:7}
 assert Counter(r[0] for r in rows)==Counter(expected)
 before=L.counts();pubs={p['registry_key']:p for p in L.read('publication_reviews')};keys=[];evs=[];seen=Counter()
 for page,day,kind,author,title in rows:
  ev=evidence(path,url,f'PDF p{page}; April{day}; rendered page visually inspected; listed name, not verified full author list')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2010:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in pubs:
   p=dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],presentation_status='listed_in_program; occurrence_unverified',date_evidence={'date':'2010-04-'+day,'source':ev,'primary_verified':True,'meaning':'Program date; not first publication or verified occurrence'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Named contribution transcribed from visually inspected official program page; no keyword filtering. Not evidence of a complete design. Abstract/full authors/counterpart remain unreviewed.',reviewer='Codex rendered-page transcription',run_id='fnano-2010',date=L.DATE,unresolved_questions=['Inspect abstract and full author/speaker roles.','Reconcile journal/preprint counterparts and actual design sources.'],legacy_record={})
   if kind=='award_address':p['rationale']+=' Program provides an award-address label, not a scientific talk title; topic unverified.'
   L.upsert('publication_reviews',p,'Retain visually supported conference lead without relevance inference')
   pubs[key]=p
  elif ev not in pubs[key]['evidence']:
   pubs[key]['evidence'].append(ev)
   L.upsert('publication_reviews',pubs[key],'Preserve repeated program appearance evidence')
  seen[key]+=1
  L.upsert('discovery_edges',dict(edge_id='fnano2010:'+key+('' if seen[key]==1 else ':p'+str(page)),source_key='fnano-2010',target_key=key,relation='conference_lead',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2010',date=L.DATE),'Record official program lead')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2010')
 run.update(pagination={'page_total':19,'pages_reviewed':reviewed,'remaining_pages':[p for p in range(1,20) if p not in reviewed]},retrieved_count=len(rows),deduplicated_additions=len(set(keys)),additions_unit='Uncertain program leads, not eligible works',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='Pages1–15 visually inspected:143 appearances,105 distinct leads;38 repeated poster appearances retained as evidence. Award-address label is not a scientific title. PDF text font encoding corrupted; render pages for reliable transcription. Administrative welcome/chairs/blitz header not treated as separate scientific contributions. Continue page16;4pages remain. Abstracts/full authors/counterparts pending.')
 L.upsert('discovery_runs',run,'Begin chronological FNANO2010 enumeration with visual evidence')
 b=next((b for b in L.read('batches') if b['batch_id']=='DISC0010'),None)
 if b is None:b=dict(batch_id='DISC0010',date=L.DATE,status='in_progress',input_keys=[],selection='Chronological FNANO2010 named contributions without keyword filtering',completed_actions=[],before_counts=before,unresolved_keys=[],exclusion_audit={'sample':[],'reason':'No title-based exclusions; administrative items not scientific contributions.'})
 b.update(input_keys=list(dict.fromkeys(keys)),unresolved_keys=list(dict.fromkeys(keys)),after_counts=L.counts(),validation=[L.validate()],next_queue=['Render and transcribe FNANO2010 pages16–19','Locate abstracts and reconcile journal/preprint counterparts','Resume balanced screening and234CV identity leads'])
 action='Visually transcribed143 appearances (105 distinct leads) on PDF pages1–15; repeated appearances preserve separate page evidence.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 L.upsert('batches',b,'Save bounded conference discovery progress')
 L.atomic(L.HERE/'fnano2010_schedule_audit.json',json.dumps(dict(source_page_total=19,pages_reviewed=reviewed,visual_audit_counts=expected,transcribed=len(rows),distinct_leads=len(set(keys)),repeated_appearances=len(keys)-len(set(keys)),source_types=dict(Counter(r[2] for r in rows)),validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
