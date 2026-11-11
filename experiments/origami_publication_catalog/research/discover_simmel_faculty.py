"""Follow public faculty pagination exposed by the retained frontend script, without a relevance cap."""
import html,json,re
from urllib.parse import urlencode,unquote
from collections import Counter
import ledger as L
from acquire_sources import fetch
from review_batch_0001 import evidence
from discover_simmel_bibliography import clean
RID='author-priority-friedrich-simmel'
def main():
 base=L.ROOT/'assets/research-20261105';page=1;rows=[];pages=[]
 while True:
  url='https://www.bio.nat.tum.de/?'+urlencode(dict(eID='tumfis_publications',action='publications',contentUid='5931',tumId='gu56goq',queryType='author',page=page,perPage=10,sort='date_desc'))
  item=fetch(url,f'simmel-faculty-api-{page}.json');assert item['status']=='available',item
  path=base/f'simmel-faculty-api-{page}.json';v=json.loads(path.read_text());assert v['success'];pg=v['pagination'];assert pg['currentPage']==page
  blocks=re.findall(r'<article\b(.*?)</article>',v['html'],re.S);assert len(blocks)==v['count']
  ev=evidence(path,url,'All public faculty publication records on page'+str(page)+'; provider count/pagination preserved')
  for i,b in enumerate(blocks,1):
   attr=lambda n:html.unescape(re.search(n+r'="([^"]*)"',b)[1])
   title=attr('data-publication-title');date=attr('data-publication-date');typ=attr('data-publication-type');links=list(dict.fromkeys(html.unescape(u) for u in re.findall(r'href="([^"]+)"',b)))
   ids=[u.rsplit('/',1)[-1] for u in links if 'portal.fis.tum.de/en/publications/' in u];assert len(ids)==1
   dois=[unquote(u.split('doi.org/',1)[1]).lower() for u in links if 'doi.org/10.' in u]
   rows.append(dict(provider_id=ids[0],page=page,ordinal=i,title=title,provider_year=date,provider_type=typ,citation=clean(b),links=links,doi_links=dois))
  pages.append(dict(page=page,pagination=pg,evidence=ev));L.atomic(L.HERE/'simmel_faculty_inventory.json',json.dumps(dict(status='acquisition_in_progress',entries=rows,pages=pages),indent=2)+'\n');print('page',page,'records',len(blocks),flush=True)
  if not pg['hasNextPage']:break
  page+=1
 assert len(rows)==pg['totalCount'];assert len({r['provider_id'] for r in rows})==len(rows)
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};selected=[r for r in rows if not re.fullmatch(r'\d{4}',r['provider_year']) or int(r['provider_year'])<=2020];matched=0
 for r in selected:
  ev=pages[r['page']-1]['evidence'];keys=[d for d in r['doi_links'] if d in pubs];target=keys[0] if len(keys)==1 else 'authorlead:simmel:tum:'+r['provider_id'];matched+=len(keys)==1
  r.update(target_key=target,identity_status='explicit_doi_registry_match' if len(keys)==1 else 'pending_identity')
  L.upsert('discovery_edges',dict(edge_id=RID+':tum:'+r['provider_id'],source_key=RID,target_key=target,relation='author_bibliography_lead',citation=r['citation'],source_links=r['links'],provider_publication_type=r['provider_type'],evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Provider UUID'+r['provider_id']+' page'+str(r['page']),reconciliation_state='explicit_doi_registry_match; primary_date_type_scope_pending' if len(keys)==1 else 'pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain all institutional publication types and date-window leads')
 audit=dict(provider_total=pg['totalCount'],pages=len(pages),unique_provider_ids=len({r['provider_id'] for r in rows}),selected_occurrences=len(selected),before2008_occurrences=sum(r['provider_year'].isdigit() and int(r['provider_year'])<2008 for r in selected),explicit_doi_registry_matches=matched,provider_types=dict(Counter(r['provider_type'] for r in selected)),year_counts=dict(Counter(r['provider_year'] for r in rows)),not_unique_work_count=True)
 L.atomic(L.HERE/'simmel_faculty_inventory.json',json.dumps(dict(status='provider_pagination_complete_reconciliation_open',audit=audit,entries=rows,selected=selected,pages=pages,limitations='Provider IDs are not reconciled works. Dates/types and truncated authors/abstracts require primary verification. Compare lab history and follow citations; no saturation claim.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run['query_or_seed']['additional_source']='https://www.bio.nat.tum.de/en/bio/professors/friedrich-simmel/';run['pagination']['faculty_history']=audit;run['evidence']+= [p['evidence'] for p in pages if p['evidence'] not in run['evidence']];run['retrieved_count']=142+len(rows);run['checkpoint']='Lab142 and faculty'+str(len(rows))+' occurrences enumerated, overlapping not unique works; faculty route adds pre2008 coverage. Reconcile provider identities/types, dates, lab overlap, inspect sources, follow backward/forward citations. Local portal403 did not block public faculty endpoint. No saturation.'
 L.upsert('discovery_runs',run,'Record complementary institutional history and successful public fallback')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Friedrich Simmel':a['next_action']=run['checkpoint']
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
