"""Progressive chronological FNANO2015 transcription; every row on reviewed pages."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 rows=[l.split('\t') for l in (L.HERE/'fnano2015_entries.tsv').read_text().splitlines() if l];reviewed=sorted({int(r[0]) for r in rows});pages=subprocess.run(['pdftotext','-layout',str(L.ROOT/'assets/research-20261105/FNANO15schedule.pdf'),'-'],capture_output=True,check=True).stdout.decode().split('\f');audit=[]
 for page in reviewed:
  a=Counter(r[2] for r in rows if int(r[0])==page);c=Counter()
  for line in pages[page-1].splitlines():
   if 'Refreshments' in line:continue
   m=re.search(r'\b(Poster\b|Contributed|Invited|Keynote)',line[:38])
   if m:c[m.group(1).lower()]+=1
  assert a==c,(page,a,c)
  audit.append({'page':page,'transcribed':dict(a),'source_labels':dict(c),'counts_match':True})
 L.atomic(L.HERE/'fnano2015_schedule_audit.json',json.dumps({'pages':audit,'total_transcribed':len(rows),'source_page_total':14,'scope':'All fourteen schedule pages enumerated; unnamed ISNSCE award address p12 unresolved; no abstract-book review claimed'},indent=2))
 existing={p['registry_key'] for p in L.read('publication_reviews')};edges={e['edge_id'] for e in L.read('discovery_edges')};keys=[];evs=[]
 for i,(page,day,kind,author,title) in enumerate(rows,1):
  ev=evidence(L.ROOT/'assets/research-20261105/FNANO15schedule.pdf','https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO15schedule.pdf',f'PDF p{page}; scheduled April{day} presentation')
  if ev not in evs:evs.append(ev)
  key='conference:fnano2015:'+hashlib.sha256((kind+'|'+author+'|'+title).encode()).hexdigest()[:14];keys.append(key)
  if key not in existing:L.upsert('publication_reviews',dict(registry_key=key,registry_id=None,doi='',title=title,authors=[author],full_author_list_transcribed=False,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],publication_type=['conference_'+kind],date_evidence={'date':'2015-04-'+day,'source':ev,'primary_verified':True,'meaning':'Scheduled presentation date, not first public availability'},review_stage='metadata_screened',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale='Schedule title/first author only; no abstract or full design inspected. All named scientific entries on reviewed pages retained, without keyword filtering.',reviewer='Codex chronological schedule transcription',run_id='fnano-2015',date=L.DATE,unresolved_questions=['Transcribe full author list; locate abstract; reconcile primary journal/preprint counterparts and assess design contribution.'],legacy_record={}), 'Preserve uncertain conference lead and stable identity')
  eid='fnano2015:'+key
  if eid not in edges:L.upsert('discovery_edges',dict(edge_id=eid,source_key='fnano-2015',target_key=key,relation='conference_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='journal_preprint_counterpart_pending',run_id='fnano-2015',date=L.DATE),'Retain conference lead without duplicate from alternate program')
  if i%20==0:print('saved',i,'/',len(rows),flush=True)
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2015');run.update(pagination={'pages':14,'pages_reviewed':reviewed,'all_named_scientific_entries_retained_on_pages':reviewed},retrieved_count=len(rows),deduplicated_additions=len(rows),additions_unit='Uncertain presentation records, not eligible works',evidence=run['evidence']+[e for e in evs if e not in run['evidence']],closure_state='in_progress',checkpoint='All fourteen pages enumerated without relevance cap. Full14-page whitespace-normalized text comparison finds room-label/format changes, not presentation-content changes, between retained PDFs. Full authors, abstracts, unnamed ISNSCE award address p12 and counterpart reconciliation remain pending.');L.upsert('discovery_runs',run,'Save bounded chronological coverage and alternate-source comparison')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0005')
 for k in keys:
  if k not in b['input_keys']:b['input_keys'].append(k)
  if k not in b['unresolved_keys']:b['unresolved_keys'].append(k)
 action=f'Enumerated{len(rows)} FNANO2015 presentations on pp1–14; compared both retained14-page PDF texts and avoided duplicate program records.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Continue FNANO2014 schedule without keyword filtering','Full authors/abstracts and journal/preprint counterparts for2015/2016','Light-harvesting parent finite core source mapping; chain-armor thesis scope','Resume backward/forward citations and other laboratory histories']);L.upsert('batches',b,'Checkpoint partial2015 enumeration within continuing discovery batch');print(L.validate(),flush=True)
if __name__=='__main__':main()
