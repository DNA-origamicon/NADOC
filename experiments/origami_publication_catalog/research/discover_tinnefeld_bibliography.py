"""Follow actual bibliography pagination and retain every provider BibTeX record."""
import html,json,re
from html.parser import HTMLParser
from urllib.parse import urljoin,urldefrag
import ledger as L
from acquire_sources import fetch
from review_batch_0001 import evidence
URL='https://tinnefeld.cup.uni-muenchen.de/publications/';RID='author-priority-philip-tinnefeld'
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.current=None;self.inpre=False;self.parts=[];self.rows=[];self.next=None;self.ids=[]
 def handle_starttag(self,t,a):
  a=dict(a)
  if t=='div' and a.get('id','').startswith('tp_bibtex_'):
   self.current=a['id'].removeprefix('tp_bibtex_');self.ids.append(self.current)
  if t=='pre' and self.current:self.inpre=True;self.parts=[]
  if t=='br' and self.inpre:self.parts.append('\n')
  if t=='a' and a.get('title')=='next page':self.next=urldefrag(urljoin(URL,a['href']))[0]
 def handle_data(self,d):
  if self.inpre:self.parts.append(d)
 def handle_endtag(self,t):
  if t=='pre' and self.inpre:
   raw=''.join(self.parts);fields={}
   for m in re.finditer(r'(?m)^\s*(\w+)\s*=\s*\{',raw):
    depth=1;i=m.end();start=i
    while i<len(raw) and depth:
     if raw[i]=='{':depth+=1
     if raw[i]=='}':depth-=1
     i+=1
    assert depth==0;fields[m[1].lower()]=raw[start:i-1].strip()
   self.rows.append(dict(provider_id=self.current,bibtex=raw,fields=fields));self.inpre=False;self.current=None

def main():
 page=1;url=URL;seen=set();rows=[];evs=[];pages=[]
 while url:
  assert url not in seen;seen.add(url);item=fetch(url,'tinnefeld-publications.html' if page==1 else f'tinnefeld-publications-{page}.html');assert item['status']=='available',item
  path=L.ROOT/item['local_file'];p=Parser();p.feed(path.read_text());assert p.rows and len(p.rows)==len(p.ids)
  ev=evidence(path,url,f'Publication page{page}; all{len(p.rows)}BibTeX provider IDs; explicit next-page link followed until absent.');evs.append(ev)
  for r in p.rows:r.update(page=page,evidence=ev)
  rows.extend(p.rows);pages.append(dict(page=page,records=len(p.rows),next_url=p.next));url=p.next;page+=1
 identities={}
 for r in rows:
  if r['provider_id'] in identities:assert identities[r['provider_id']]==r['fields'], 'Conflicting repeated provider ID'
  identities[r['provider_id']]=r['fields']
 pubs={p['registry_key'] for p in L.read('publication_reviews')};selected=[]
 for r in rows:
  f=r['fields'];y=f.get('year','');r['selected']=not y.isdigit() or int(y)<=2020
  if not r['selected']:continue
  doi=f.get('doi','').lower().strip();r['target_key']=doi if doi in pubs else 'authorlead:tinnefeld:'+r['provider_id'];r['identity_status']='explicit_doi_registry_match' if doi in pubs else 'pending_identity';selected.append(r);e=r['evidence']
  L.upsert('discovery_edges',dict(edge_id=RID+':lab:'+r['provider_id']+':page'+str(r['page']),source_key=RID,target_key=r['target_key'],relation='author_bibliography_lead',citation=f,doi_candidate=doi,evidence_url=e['url'],local_file=e['local_file'],sha256=e['sha256'],locator='Provider BibTeX ID'+r['provider_id']+' page'+str(r['page']),reconciliation_state='explicit_doi_registry_match; primary_date_scope_pending' if doi in pubs else 'pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain all pre2020/boundary/unknown-year bibliography leads')
 audit=dict(all_occurrences=len(rows),unique_provider_ids=len(identities),repeated_provider_occurrences=len(rows)-len(identities),empty_metadata_provider_ids=[r['provider_id'] for r in rows if not r['fields'].get('title')],selected_unique_provider_ids=len({r['provider_id'] for r in selected}),selected_occurrences=len(selected),explicit_doi_registry_matches=sum(r['identity_status']=='explicit_doi_registry_match' for r in selected),pages=pages,years=sorted({r['fields'].get('year','unknown') for r in rows}),provider_total=None,terminal_next_link_absent=True,counts_are_not_unique_works=True)
 L.atomic(L.HERE/'tinnefeld_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=rows,selected=selected,evidence=evs,limitations='One repeated provider record is retained by page occurrence; empty provider metadata remains a lead without publication identity. Provider IDs distinguish bibliography records, not canonical works. Dates are bibliography fields, not primary first-online verification. No keyword exclusions; independent history/citation coverage remains open.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run.update(source_url=URL,query_or_seed={'author':'Philip Tinnefeld','source':URL},retrieved_count=len(rows),deduplicated_additions=None,additions_unit='Provider bibliography records',pagination=audit,evidence=evs,closure_state='in_progress',checkpoint='All linked bibliography pages enumerated to terminal next-link absence; reconcile dates/identities/source evidence and compare independent LMU repository history. No saturation claim.')
 L.upsert('discovery_runs',run,'Save complete traversal of this bounded provider route')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Philip Tinnefeld':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
