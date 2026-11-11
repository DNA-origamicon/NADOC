"""Enumerate provider pagination without title relevance caps; preserve publication types as unresolved."""
import html,json,re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,unquote
import ledger as L
from acquire_sources import fetch
from review_batch_0001 import evidence
URL='https://www.physics.ox.ac.uk/our-people/turberfield/publications';RID='author-priority-andrew-turberfield'
class Text(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,d):self.parts.append(d)
def clean(s):
 p=Text();p.feed(s);return ' '.join(' '.join(p.parts).split())
def parse(s,page):
 blocks=s.split('<div class="publication">')[1:];out=[]
 for ordinal,b in enumerate(blocks,1):
  b=b.split('<nav class="pager"')[0]
  def field(css):
   m=re.search(r'<div class="'+css+r'">(.*?)</div>',b,re.S);return clean(m[1]) if m else ''
  title=field('publication-title');citation=field('publication-citation');authors=field('publication-authors');abstract=field('publication-abstract');links=[]
  for u in re.findall(r'href="([^"]+)"',b):
   u=urljoin(URL,html.unescape(u))
   if urlsplit(u).netloc!='www.physics.ox.ac.uk' and u.startswith('http'):links.append(u)
  links=list(dict.fromkeys(links));dois=[]
  for u in links:
   if 'doi.org/' in u:
    d=unquote(u.split('doi.org/',1)[1]).split('?')[0].split('#')[0].lower()
    if d.startswith('10.'):dois.append(d)
  years=[int(x) for x in re.findall(r'\((19\d{2}|20\d{2})\)',citation)]
  assert title
  out.append(dict(page=page,ordinal=ordinal,title=title,citation=citation,authors=authors,abstract=abstract,links=links,doi_links=list(dict.fromkeys(dois)),stated_years=years))
 return out

def main():
 base=L.ROOT/'assets/research-20261105';rows=[];evs=[];page=0;seen=set();pages=[]
 while True:
  assert page not in seen;seen.add(page);url=URL+('?page='+str(page) if page else '')
  item=fetch(url,f'turberfield-publications-{page}.html');assert item['status']=='available',item
  path=base/f'turberfield-publications-{page}.html';s=path.read_text();rs=parse(s,page);assert rs
  ev=evidence(path,url,'All publication blocks on provider page '+str(page)+'; title, citation, authors, abstract and links; no title filtering')
  evs.append(ev);rows.extend(rs);pages.append(dict(page=page,records=len(rs),evidence=ev))
  print('page',page,'records',len(rs),flush=True)
  L.atomic(L.HERE/'turberfield_bibliography_inventory.json',json.dumps(dict(status='acquisition_in_progress',all_entries=rows,pages=pages),indent=2)+'\n')
  n=re.search(r'<a href="\?page=(\d+)"[^>]*rel="next"',s)
  if not n:break
  page=int(n[1])
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};selected=[r for r in rows if not r['stated_years'] or min(r['stated_years'])<=2020];matched=0
 for r in selected:
  ev=evs[r['page']];keys=[d for d in r['doi_links'] if d in pubs];target=keys[0] if len(keys)==1 else f"authorlead:turberfield:{r['page']}:{r['ordinal']}";matched+=len(keys)==1
  r.update(target_key=target,identity_status='explicit_doi_registry_match' if len(keys)==1 else 'pending_identity')
  L.upsert('discovery_edges',dict(edge_id=RID+':oxford:'+str(r['page'])+':'+str(r['ordinal']),source_key=RID,target_key=target,relation='author_bibliography_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='page'+str(r['page'])+' publication block'+str(r['ordinal']),citation=r['title']+' | '+r['citation'],source_links=r['links'],reconciliation_state='explicit_doi_registry_match; date_type_scope_sources_pending' if len(keys)==1 else 'pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain author-history occurrence without title relevance filtering')
 audit=dict(provider_pages=len(pages),provider_page_records=[p['records'] for p in pages],all_occurrences=len(rows),selected_occurrences=len(selected),explicit_doi_registry_matches=matched,unknown_dates=sum(not r['stated_years'] for r in selected),terminal_page=page,terminal_next_link_absent=True,distinct_exact_titles=len({r['title'] for r in rows}),counts_are_not_unique_works=True)
 L.atomic(L.HERE/'turberfield_bibliography_inventory.json',json.dumps(dict(status='provider_pagination_enumerated_identity_review_open',audit=audit,all_entries=rows,selected=selected,pages=pages,limitations='Provider pagination completed, not exhaustive author coverage. Repeated titles, conference/journal/preprint identities and publication dates require primary reconciliation; no relevance classifications from titles/abstracts.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID)
 run.update(source_url=URL,query_or_seed={'author':'Andrew Turberfield','source':URL},retrieved_count=len(rows),deduplicated_additions=None,additions_unit='Provider bibliography occurrences, not unique works',pagination=audit,evidence=evs,closure_state='in_progress',checkpoint='Followed provider next-page links to terminal page without relevance cap; reconcile identities/versions/types and dates, inspect sources, follow citations, compare independent histories. FNANO deferred; saturation not established.')
 L.upsert('discovery_runs',run,'Save complete bounded provider enumeration; broader discovery open')
 qpath=L.HERE/'author_priority_queue.json';q=json.loads(qpath.read_text())
 for a in q['authors']:
  if a['name']=='Andrew Turberfield':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qpath,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
