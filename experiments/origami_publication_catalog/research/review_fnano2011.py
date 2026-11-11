"""Resumable complete-page program transcription; no title-based exclusions."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=json.loads((L.HERE/'fnano2011_transcription.json').read_text());reviewed=sorted({r[0] for r in rows})
 path=L.ROOT/'assets/research-20261105/FNANO11schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO11schedule.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');audit=[]
 def norm(t):
  return ' '.join(t.replace('\u00ad','').replace('‐',' ').split())
 for page in reviewed:
  page_rows=[r for r in rows if r[0]==page]
  text=norm(pages[page-1])
  for _,_,_,author,title in page_rows:
   assert norm(author) in text,(page,author)
   cursor=0
   for word in norm(title).split():
    found=text.find(word,cursor)
    assert found>=0,(page,title,word)
    cursor=found+len(word)
  expected={1:13,2:18,3:16,4:12,5:15,6:14,7:12,8:11,9:16,10:14,11:17,12:11}[page]
  assert len(page_rows)==expected,(page,len(page_rows))
  audit.append(dict(page=page,transcribed=len(page_rows),expected_named_entries=expected,source_types=dict(Counter(r[2] for r in page_rows)),audit_method='Complete page text inspected; p1 additionally rendered. Extracted text has font substitutions (ti as R, tt as g), retained rather than silently repaired. Administrative introductory remarks/session headers excluded; named TBA entries retained. Title and listed-author presence asserted.'))
 before=L.counts();existing={p['registry_key']:p for p in L.read('publication_reviews')};keys=[];evs=[];seen=Counter()
 for page,day,kind,author,title in rows:
  ev=evidence(path,url,f'PDF p{str(page)}; April{day} program entry; first-listed author not necessarily presenter')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2011:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in existing:
   L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],presentation_status='listed_in_program; occurrence_unverified',date_evidence={'date':'2011-04-'+day,'source':ev,'primary_verified':True,'meaning':'Program date, not verified presentation or first availability'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Named official program entry retained without keyword filtering. Title/first author inspected; abstract, full author list, speaker and design sources unreviewed. Program alone does not prove complete design.',reviewer='Codex chronological program transcription',run_id='fnano-2011',date=L.DATE,unresolved_questions=['Inspect full authors/speaker typography and abstract book.','Reconcile journal/preprint counterparts using primary evidence; do not infer design completeness.'],legacy_record={}), 'Retain source-supported conference lead with separate publication identity')
   existing[key]=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
  elif ev not in existing[key]['evidence']:
   existing[key]['evidence'].append(ev)
   L.upsert('publication_reviews',existing[key],'Preserve repeated program appearance evidence under stable lead')
  seen[key]+=1
  L.upsert('discovery_edges',dict(edge_id='fnano2011:'+key+('' if seen[key]==1 else ':p'+str(page)),source_key='fnano-2011',target_key=key,relation='conference_lead',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2011',date=L.DATE),'Retain every named entry on reviewed pages')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2011')
 run.update(pagination={'pages':12,'pages_reviewed':reviewed,'remaining_pages':[p for p in range(1,13) if p not in reviewed]},retrieved_count=len(rows),deduplicated_additions=len(set(keys)),additions_unit='Uncertain conference program leads, not eligible publications',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='All12pages,169appearances representing167distinct kind/author/title leads. Bui and Cigler posters each repeated on p6/p10, both locators preserved. No journal/preprint merges. Text extraction has font substitutions in titles and names; p1 rendered and checked, remaining visual normalization pending. Named TBA talks retained. Authors/abstracts/counterparts pending.')
 L.upsert('discovery_runs',run,'Save bounded chronological conference progress')
 b=next((b for b in L.read('batches') if b['batch_id']=='DISC0009'),None)
 if b is None:b=dict(batch_id='DISC0009',date=L.DATE,status='in_progress',input_keys=[],selection='Chronological FNANO2011 program entries without keyword filtering',completed_actions=[],before_counts=before,unresolved_keys=[],exclusion_audit={'sample':[],'reason':'No exclusions from program titles.'})
 b.update(input_keys=list(dict.fromkeys(keys)),unresolved_keys=list(dict.fromkeys(keys)),after_counts=L.counts(),validation=[L.validate()],next_queue=['FNANO2011 abstracts/full authors/counterparts and visual normalization; FNANO2010 enumeration','Review abstract book/full author roles and journal counterparts','B0011 source follow-ups and next balanced screening batch'])
 action=f'Transcribed{len(rows)}named entries on pages{reviewed}; per-page type counts audited.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 L.upsert('batches',b,'Save conference handoff with actual source denominator')
 out=dict(pages=audit,total_transcribed=len(rows),distinct_program_leads=len(set(keys)),repeated_appearance_count=len(keys)-len(set(keys)),source_page_total=12,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'fnano2011_schedule_audit.json',json.dumps(out,indent=2)+'\n');print(out['validation'])
if __name__=='__main__':main()
