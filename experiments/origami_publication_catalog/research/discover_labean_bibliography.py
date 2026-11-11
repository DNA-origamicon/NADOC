"""Inventory bounded official CV/profile sources; preserve publication-type distinctions."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence
from discover_simmel_bibliography import clean
RID='author-priority-thomas-labean'
def main():
 base=L.ROOT/'assets/research-20261105';cv=base/'labean-duke-cv.pdf';s=subprocess.check_output(['pdftotext','-layout',str(cv),'-']).decode()
 s=re.sub(r'(?m)^[ *]+$','',s);s=re.sub(r'\f(JOURNAL PUBLICATIONS|MEETING PROCEEDING PUBLICATIONS|BOOK CHAPTERS) \(Continued\)','',s)
 ev=evidence(cv,'https://fds.duke.edu/db/aas/Chemistry/faculty/thl/files/CV.pdf','Journal Publications, Meeting Proceeding Publications, Book Chapters and Book Reviews sections; older CV through2007, not a current career census. Patents/talks/grants excluded from publication block enumeration.')
 rows=[]
 sections=[('JOURNAL PUBLICATIONS','MEETING PROCEEDING PUBLICATIONS','journal_section_lead',29),('MEETING PROCEEDING PUBLICATIONS','BOOK CHAPTERS','conference_or_proceedings_lead',21),('BOOK CHAPTERS','BOOK REVIEWS','book_chapter_lead',8),('BOOK REVIEWS','PATENTS','book_review_lead',1)]
 for start,end,typ,count in sections:
  t=s.split(start,1)[1].split(end,1)[0];t=re.sub(r'^\s*\(\*Indicates corresponding authors\)','',t);citations=[' '.join(x.split()) for x in re.split(r'\n\s*\n',t) if x.strip()];assert len(citations)==count
  for n,c in enumerate(citations,1):rows.append(dict(source='duke_cv',section=start,ordinal=n,citation=c,publication_type_lead=typ,unpublished_status='in_preparation' if 'in preparation' in c else 'submitted' if 'submitted' in c else None,evidence=ev))
 profile=base/'labean-ncsu-profile.html';h=profile.read_text();start=h.index('<h2>Publications</h2>') if '<h2>Publications</h2>' in h else h.index('>Publications</h2>');block=h[start:h.index('View all publications',start)]
 entries=re.findall(r'<li\b[^>]*>(.*?)</li>',block,re.S);assert len(entries)==10
 pe=evidence(profile,'https://mse.ncsu.edu/people/thlabean/','Publications section10listed items; only2019 and2017 entries are pre2020 candidates. View-all target returned bot challenge; lab target404.')
 for i,c in enumerate(entries,1):
  text=clean(c);years=re.findall(r'\((20\d\d)\)',text);rows.append(dict(source='ncsu_profile',section='Publications',ordinal=i,citation=text,year_candidates=years,selected=not years or min(map(int,years))<=2020,publication_type_lead='profile_publication_lead',evidence=pe))
 selected=[r for r in rows if r.get('selected',True)]
 for r in selected:
  e=r['evidence'];suffix=r['source']+':'+r['publication_type_lead']+':'+str(r['ordinal'])
  L.upsert('discovery_edges',dict(edge_id=RID+':'+suffix,source_key=RID,target_key='authorlead:labean:'+suffix,relation='author_bibliography_lead',citation=r['citation'],publication_type_lead=r['publication_type_lead'],unpublished_status=r.get('unpublished_status'),evidence_url=e['url'],local_file=e['local_file'],sha256=e['sha256'],locator=r['section']+' item'+str(r['ordinal']),reconciliation_state='pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain author CV/profile leads without treating conference/in-preparation text as complete designs')
 audit=dict(cv_occurrences=59,cv_sections={a:n for a,_,_,n in sections},profile_occurrences=10,selected_occurrences=len(selected),counts_overlap_not_unique=True,coverage_gap='CV covers1993–2007 plus undated in-preparation; current profile only10selected works, no2008–2016 coverage established. Independent Duke/NCSU histories remain unenumerated.')
 L.atomic(L.HERE/'labean_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=rows,evidence=[ev,pe],limitations='No primary dates or design classifications inferred. Incidental FNANO citations in CV retained as conference leads; no additional FNANO program search undertaken.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run.update(source_url=pe['url'],retrieved_count=len(rows),deduplicated_additions=None,additions_unit='Overlapping CV/profile publication occurrences',pagination=audit,evidence=[ev,pe],failures=[{'url':'https://mse.ncsu.edu/labean/','result':'404'},{'url':'https://www.lib.ncsu.edu/repository/scholpubs/search.php?page=author&pos=1&aid=30116','result':'HTTP200botchallenge, not bibliography; challenge payload not retained'}],closure_state='in_progress',checkpoint='Enumerated old CV59and current profile10; identity/type/date review pending. Find alternate later-career history; retain2008–2016gap and undated/unpublished leads; no coverage closure.')
 L.upsert('discovery_runs',run,'Save bounded official-source coverage and failed-route diagnostics')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Thomas LaBean':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
