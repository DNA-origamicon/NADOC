"""Complement lab history with the public LMU author repository index."""
import json,re
import ledger as L
from review_batch_0001 import evidence
from discover_simmel_bibliography import clean
URL='https://epub.ub.uni-muenchen.de/view/autoren/Liedl%3D3ATim%3D3A%3D3A.html';RID='author-priority-tim-liedl'
def main():
 p=L.ROOT/'assets/research-20261105/liedl-lmu-repository-history.html';s=p.read_text();blocks=re.findall(r'<div style="margin: 0">(.*?)</div>',s,re.S);total=int(re.search(r'Anzahl der Publikationen: <strong>(\d+)',s)[1]);assert len(blocks)==total;rows=[]
 ev=evidence(p,URL,'Complete author index; reported64 publication records, all blocks retained, labeled journal articles')
 for b in blocks:
  m=re.search(r'<a href="(https://epub.ub.uni-muenchen.de/(\d+)/)"><span class="title">(.*?)</span></a>',b,re.S);assert m
  dates=re.findall(r'\(([^()]*(?:19|20)\d{2})\):',b);assert len(dates)==1;year=int(re.search(r'(?:19|20)\d{2}',dates[0])[0]);rows.append(dict(repository_id=m[2],url=m[1],title=clean(m[3]),citation=clean(b),stated_date=dates[0],stated_year=year,provider_type='journal_article'))
 selected=[r for r in rows if r['stated_year']<=2020]
 for r in selected:
  L.upsert('discovery_edges',dict(edge_id=RID+':lmu:'+r['repository_id'],source_key=RID,target_key='authorlead:liedl:lmu:'+r['repository_id'],relation='author_bibliography_lead',citation=r['citation'],source_links=[r['url']],evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Repository record'+r['repository_id'],reconciliation_state='pending_identity_primary_dates_versions_sources',run_id=RID,date=L.DATE),'Retain all repository author-index leads without relevance filtering')
 audit=dict(provider_total=total,parsed_records=len(rows),unique_repository_ids=len({r['repository_id'] for r in rows}),selected_occurrences=len(selected),oldest_year=min(r['stated_year'] for r in rows),newest_year=max(r['stated_year'] for r in rows),not_unique_work_count=True)
 L.atomic(L.HERE/'liedl_repository_inventory.json',json.dumps(dict(audit=audit,entries=rows,selected=selected,evidence=[ev],limitations='Repository coverage begins2013; lab page extends2004. Reconcile overlap, dates and identities; repository dates not assumed first online.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run['query_or_seed']['repository']=URL;run['pagination']['repository']=audit;run['retrieved_count']=119+len(rows);run['evidence'].append(ev);run['checkpoint']='Lab119 and LMU repository64 overlapping citation occurrences enumerated; lab2004–2024,repository2013–2025. Reconcile all identities and primary dates; lab88 selected leads lack source links, repository provides landing links. Silica-growth lead has lab2018 vs repository2019 requiring first-online verification. No saturation.';L.upsert('discovery_runs',run,'Preserve complementary bibliography scope and overlap limits')
 qpath=L.HERE/'author_priority_queue.json';q=json.loads(qpath.read_text())
 for a in q['authors']:
  if a['name']=='Tim Liedl':a['next_action']=run['checkpoint']
 L.atomic(qpath,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
