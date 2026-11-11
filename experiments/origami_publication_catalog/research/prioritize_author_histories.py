"""Apply user discovery priorities and retain Castro bibliography leads."""
import hashlib,json,re
import ledger as L
from review_batch_0001 import evidence

def main():
 names=['Carlos Castro','Hendrik Dietz','Shawn Douglas','William Shih','Hao Yan','Peng Yin','Andrew Turberfield','Mark Bathe','Tim Liedl','Lulu Qian','Friedrich Simmel','Philip Tinnefeld','Jonathan Doye','Thomas LaBean','Paul Rothemund']
 existing={'Hendrik Dietz':'author-dietz-20261105','Shawn Douglas':'author-douglas-20261105','Hao Yan':'author-hao-yan-asu-cv','Paul Rothemund':'author-rothemund-selected-20261105'}
 queue=[]
 for name in names:
  rid=existing.get(name,'author-priority-'+name.lower().replace(' ','-'))
  if name=='Carlos Castro':rid='author-castro-osu'
  queue.append(dict(name=name,run_id=rid,status='in_progress' if name in existing or name=='Carlos Castro' else 'pending',next_action='Enumerate publication history; reconcile identities and first-online dates; inspect designs/sources and follow citations.'))
  if name not in existing and name!='Carlos Castro':
   run=dict(run_id=rid,route='author_bibliography',query_or_seed={'name':name,'basis':'Explicit user priority list'},source_url='',date=L.DATE,pagination={},provider_total=None,retrieved_count=0,deduplicated_additions=0,failures=[],checkpoint='Locate identity-verified official bibliography and archived pre2020 coverage; not yet executed.',closure_state='pending',evidence=[])
   if not any(x['run_id']==rid for x in L.read('discovery_runs')):L.upsert('discovery_runs',run,'Persist explicit author priority')
 L.atomic(L.HERE/'author_priority_queue.json',json.dumps(dict(date=L.DATE,priority_basis='User correction: author/publication routes first; FNANO only after demonstrated diminishing returns elsewhere.',fnano='deferred; preserved; no saturation established',authors=queue),indent=2)+'\n')
 for run in L.read('discovery_runs'):
  if run['run_id'].startswith('fnano-'):
   run.update(scheduling_priority='deferred_by_user',resume_condition='Other search methods demonstrate documented diminishing returns; not currently established.')
   L.upsert('discovery_runs',run,'Defer conference route per user priority without claiming exhaustion')
 path=L.HERE/'castro_publications_web_capture.json';raw=json.loads(path.read_text());year=None;entries=[]
 for line in raw.splitlines():
  m=re.match(r'L(\d+): (.*)',line)
  if not m:continue
  number,body=int(m[1]),m[2]
  if re.fullmatch(r'20\d\d',body.strip()):year=int(body.strip())
  if year and year<=2020 and 148<=number<=226 and body.startswith('  * '):
   entries.append(dict(source_line=number,listed_year=year,citation=body[4:].strip(),boundary_check=year==2020,identity_status='pending'))
 assert entries and all(x['listed_year']>=2007 for x in entries)
 ev=evidence(path,'https://mae.osu.edu/nbl/publications','Web-reader capture lines148–226:2020 boundary plus2019–2007 bibliography; nested news links excluded')
 rid='author-castro-osu';run=dict(run_id=rid,route='author_bibliography',query_or_seed={'name':'Carlos E. Castro','affiliation':'Ohio State University'},source_url=ev['url'],date=L.DATE,pagination={'page':'single official lab page','section_years':[2007,2020],'full_author_history_exhausted':False},provider_total=None,retrieved_count=len(entries),deduplicated_additions=None,additions_unit='Unreconciled bibliography entries, not new eligible works',failures=[{'resource':ev['url'],'method':'paced downloader','status':'HTTP403','fallback':'web-reader capture retained'}],checkpoint='Enumerated pre2020 sections plus2020 boundary entries. Reconcile DOI/title/version identities and publication dates; under-review entries are not proof of publication. Compare CV and linked full bibliography; then inspect sources and citations.',closure_state='in_progress',evidence=[ev])
 L.upsert('discovery_runs',run,'Start requested author history using accessible official bibliography')
 for entry in entries:
  key='authorlead:castro:'+hashlib.sha256(entry['citation'].encode()).hexdigest()[:16]
  entry['lead_key']=key
  L.upsert('discovery_edges',dict(edge_id=rid+':'+key,source_key=rid,target_key=key,relation='author_bibliography_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Web capture line'+str(entry['source_line']),citation=entry['citation'],listed_year=entry['listed_year'],reconciliation_state='pending_identity_date_and_scope',run_id=rid,date=L.DATE),'Retain bibliography entry without keyword exclusion or duplicate publication insertion')
 L.atomic(L.HERE/'castro_bibliography_inventory.json',json.dumps(dict(entries=entries,total=len(entries),pre2020_section_entries=sum(x['listed_year']<2020 for x in entries),boundary2020_entries=sum(x['listed_year']==2020 for x in entries),evidence=ev),indent=2)+'\n')
 print({'entries':len(entries),'pre2020':sum(x['listed_year']<2020 for x in entries),'validation':L.validate()})
if __name__=='__main__':main()
