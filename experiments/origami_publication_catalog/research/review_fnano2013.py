"""Resumable complete-page program transcription; no title-based exclusions."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=json.loads((L.HERE/'fnano2013_transcription.json').read_text());reviewed=sorted({r[0] for r in rows})
 path=L.ROOT/'assets/research-20261105/FNANO13schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO13schedule.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');audit=[]
 for page in reviewed:
  source=Counter()
  for line in pages[page-1].splitlines():
   if 'Reception' in line or 'Refreshments' in line or 'Poster Session' in line:continue
   m=re.search(r'\b(Poster\b|Contributed|Invited|Keynote)',line[:43])
   if m:source[m[1].lower()]+=1
  actual=Counter(r[2] for r in rows if r[0]==page)
  assert source==actual,(page,source,actual)
  audit.append(dict(page=page,source_labels=dict(source),transcribed=dict(actual),counts_match=True))
 before=L.counts();existing={p['registry_key'] for p in L.read('publication_reviews')};keys=[];evs=[]
 for page,day,kind,author,title in rows:
  ev=evidence(path,url,f'PDF p{page}; April{day} program entry; first-listed author not necessarily presenter')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2013:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in existing:
   L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],presentation_status='cancelled_in_program' if author=='Christof Niemeyer' else 'listed_in_program; occurrence_unverified',date_evidence={'date':'2013-04-'+day,'source':ev,'primary_verified':True,'meaning':'Program date, not verified presentation or first availability'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Named official program entry retained without keyword filtering. Title/first author inspected; abstract, full author list, speaker and design sources unreviewed. Program alone does not prove complete design.',reviewer='Codex chronological program transcription',run_id='fnano-2013',date=L.DATE,unresolved_questions=['Inspect full authors/speaker typography and abstract book.','Reconcile journal/preprint counterparts using primary evidence; do not infer design completeness.'],legacy_record={}), 'Retain source-supported conference lead with separate publication identity')
  if author=='Donald Kellis':
   q=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
   q['unresolved_questions'].append('PDFp4 rendered row starts DonaldKellis; extracted text includes overlapping BrittanyCannon/WilliamKnowlton above it. Verify complete author attribution from abstract before normalization.')
   L.upsert('publication_reviews',q,'Preserve visible-versus-extracted author layout ambiguity')
  L.upsert('discovery_edges',dict(edge_id='fnano2013:'+key,source_key='fnano-2013',target_key=key,relation='conference_lead',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2013',date=L.DATE),'Retain every named entry on reviewed pages')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2013')
 run.update(pagination={'pages':7,'pages_reviewed':reviewed,'remaining_pages':[p for p in range(1,8) if p not in reviewed]},retrieved_count=len(rows),deduplicated_additions=len(rows),additions_unit='Uncertain conference program leads, not eligible publications',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='All7pages132named entries; cancelled Niemeyer keynote visually confirmed p4. Unnamed award address p3, reception wording, author layout and full authors/abstracts/counterparts remain unresolved.')
 L.upsert('discovery_runs',run,'Save bounded chronological conference progress')
 b=next((b for b in L.read('batches') if b['batch_id']=='DISC0007'),None)
 if b is None:b=dict(batch_id='DISC0007',date=L.DATE,status='in_progress',input_keys=[],selection='Chronological FNANO2013 program entries without keyword filtering',completed_actions=[],before_counts=before,unresolved_keys=[],exclusion_audit={'sample':[],'reason':'No exclusions from program titles.'})
 b.update(input_keys=keys,unresolved_keys=keys,after_counts=L.counts(),validation=[L.validate()],next_queue=['FNANO2013 abstract book, full authors and counterparts; next FNANO2012schedule','Review abstract book/full author roles and journal counterparts','Maintain balanced B0011 screening'])
 b['completed_actions'].append(f'Transcribed{len(rows)}named entries on pages{reviewed}; per-page type counts audited.')
 L.upsert('batches',b,'Save conference handoff with actual source denominator')
 out=dict(pages=audit,total_transcribed=len(rows),source_page_total=7,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'fnano2013_schedule_audit.json',json.dumps(out,indent=2)+'\n');print(out['validation'])
if __name__=='__main__':main()
