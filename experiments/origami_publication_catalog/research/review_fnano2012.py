"""Resumable complete-page program transcription; no title-based exclusions."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=json.loads((L.HERE/'fnano2012_transcription.json').read_text());reviewed=sorted({r[0] for r in rows})
 path=L.ROOT/'assets/research-20261105/FNANO12schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO12schedule.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');audit=[]
 def norm(t):
  return ' '.join(t.replace('\u00ad','').replace('‐','').split())
 for page in reviewed:
  page_rows=[r for r in rows if r[0]==page]
  text=norm(pages[page-1])
  for _,_,_,author,title in page_rows:
   assert norm(author) in (text + (norm(pages[page]) if page==6 and author=="Alfredo Bobadilla" else "")),(page,author)
   assert norm(title) in text,(page,title)
  expected={1:12,2:16,3:16,4:16,5:13,6:20,7:20,8:10,9:16}[page]
  assert len(page_rows)==expected,(page,len(page_rows))
  audit.append(dict(page=page,transcribed=len(page_rows),expected_named_entries=expected,source_types=dict(Counter(r[2] for r in page_rows)),audit_method='Complete page text inspected; p2 and p7 additionally rendered and visually reviewed; p7 missing dimension numerals visibly present in source, retained unchanged. Administrative/session headers excluded; title and first-author presence asserted.'))
 before=L.counts();existing={p['registry_key'] for p in L.read('publication_reviews')};keys=[];evs=[]
 for page,day,kind,author,title in rows:
  ev=evidence(path,url,f'PDF p{str(page) if author != "Alfredo Bobadilla" else "6–7"}; April{day} program entry; first-listed author not necessarily presenter')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2012:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in existing:
   L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],presentation_status='listed_in_program; occurrence_unverified',date_evidence={'date':'2012-04-'+day,'source':ev,'primary_verified':True,'meaning':'Program date, not verified presentation or first availability'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Named official program entry retained without keyword filtering. Title/first author inspected; abstract, full author list, speaker and design sources unreviewed. Program alone does not prove complete design.',reviewer='Codex chronological program transcription',run_id='fnano-2012',date=L.DATE,unresolved_questions=['Inspect full authors/speaker typography and abstract book.','Reconcile journal/preprint counterparts using primary evidence; do not infer design completeness.'],legacy_record={}), 'Retain source-supported conference lead with separate publication identity')
  L.upsert('discovery_edges',dict(edge_id='fnano2012:'+key,source_key='fnano-2012',target_key=key,relation='conference_lead',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2012',date=L.DATE),'Retain every named entry on reviewed pages')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2012')
 run.update(pagination={'pages':9,'pages_reviewed':reviewed,'remaining_pages':[p for p in range(1,10) if p not in reviewed]},retrieved_count=len(rows),deduplicated_additions=len(rows),additions_unit='Uncertain conference program leads, not eligible publications',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='All9pages,139named entries. Page3 author list continues onto p4; p6 final title has authors on p7; retained once by title-start page. Full authors/speakers, abstracts and counterparts pending. Printed vHelix mojibake, F -ATPase and p7 missing dimensional numerals visually confirmed, not silently repaired.')
 L.upsert('discovery_runs',run,'Save bounded chronological conference progress')
 b=next((b for b in L.read('batches') if b['batch_id']=='DISC0008'),None)
 if b is None:b=dict(batch_id='DISC0008',date=L.DATE,status='in_progress',input_keys=[],selection='Chronological FNANO2012 program entries without keyword filtering',completed_actions=[],before_counts=before,unresolved_keys=[],exclusion_audit={'sample':[],'reason':'No exclusions from program titles.'})
 b.update(input_keys=keys,unresolved_keys=keys,after_counts=L.counts(),validation=[L.validate()],next_queue=['FNANO2012 abstracts/full authors/counterparts; FNANO2011 schedule','Review abstract book/full author roles and journal counterparts','B0011 source follow-ups and next balanced screening batch'])
 b['completed_actions'].append(f'Transcribed{len(rows)}named entries on pages{reviewed}; per-page type counts audited.')
 L.upsert('batches',b,'Save conference handoff with actual source denominator')
 out=dict(pages=audit,total_transcribed=len(rows),source_page_total=9,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'fnano2012_schedule_audit.json',json.dumps(out,indent=2)+'\n');print(out['validation'])
if __name__=='__main__':main()
