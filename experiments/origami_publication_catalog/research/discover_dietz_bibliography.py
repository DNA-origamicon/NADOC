"""Retain every numbered laboratory bibliography entry, including low-keyword works."""
import hashlib,json,re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,urlunsplit,unquote
import ledger as L
from review_batch_0001 import evidence

class Paragraphs(HTMLParser):
 def __init__(self):super().__init__();self.rows=[];self.current=None;self.all_links=[]
 def handle_starttag(self,t,attrs):
  if t in ('p','h2','h3'):self.current={'tag':t,'text':[],'links':[]}
  if t=='a':
   u=dict(attrs).get('href','');u=urljoin('https://www.dietzlab.org',u);s=urlsplit(u)
   clean=urlunsplit((s.scheme,s.netloc,s.path.split(';')[0],'',''));self.all_links.append(clean)
   if self.current is not None:self.current['links'].append(clean)
 def handle_data(self,d):
  if self.current is not None:self.current['text'].append(d)
 def handle_endtag(self,t):
  if self.current is not None and self.current['tag']==t:self.rows.append(self.current);self.current=None

def entries(html):
 p=Paragraphs();p.feed(html);rows=[];cur=None;year=None;patents=[];in_patents=False
 for r in p.rows:
  t=' '.join(' '.join(r['text']).split())
  if not t:continue
  if r['tag'] in ('h2','h3'):
   if cur:rows.append(cur);cur=None
   if t in ('Patents','Books, theses'):in_patents=True
   year=int(t) if re.fullmatch(r'\d{4}',t) else None
   continue
  if in_patents:patents.append({'text':t,'links':r['links']});continue
  m=re.match(r'^\((\d+)\)',t)
  if m:
   if cur:rows.append(cur)
   cur={'printed_number':m[1],'stated_year_heading':year,'text_parts':[t],'links':r['links']}
  elif cur:cur['text_parts'].append(t);cur['links']+=r['links']
 if cur:rows.append(cur)
 return rows,patents

def main():
 root=L.ROOT/'assets/research-20261105';known={r['doi'].lower():r['registry_key'] for r in L.read('publication_reviews') if r['doi']};allrows=[];evs=[];patent_rows=[];saved_edges={e['edge_id']:e for e in L.read('discovery_edges')}
 for name,url in [('dietz-publications.html','https://www.dietzlab.org/publications/'),('dietz-publications-pre2010.html','https://www.dietzlab.org/publications/2010/')]:
  path=root/name;rows,patents=entries(path.read_text());parser=Paragraphs();parser.feed(path.read_text());patent_rows.append({'source':name,'unnumbered_patent_book_thesis_paragraphs':patents,'all_source_links':sorted(set(parser.all_links))});ev=evidence(path,url,'All numbered publication entries; printed labels may repeat and are not unique identities');evs.append(ev)
  for ordinal,r in enumerate(rows,1):
   txt=' '.join(r['text_parts']);years=re.findall(r'\((19\d{2}|20\d{2})\)',txt);r['stated_bibliographic_year']=int(years[-1]) if years else r['stated_year_heading'];dois=set(re.findall(r'10\.\d{4,9}/[^\s,;]+',txt))
   for u in r['links']:
    m=re.search(r'10\.\d{4,9}/[^?#]+',unquote(u))
    if m:dois.add(re.sub(r'/(abstract|full|pdf)$','',m[0]))
   dois=sorted(d.lower().rstrip('.') for d in dois)
   matches={known[d] for d in dois if d in known}
   identity=hashlib.sha256((name+'|'+txt).encode()).hexdigest()[:16]
   target=next(iter(matches)) if len(matches)==1 else 'author_bibliography:dietz:'+identity
   row=dict(r,source=name,ordinal=ordinal,explicit_doi_candidates=dois,target_key=target);allrows.append(row)
   # Source enumeration must not overwrite a later primary-source identity review.
   prior=saved_edges.get('author_dietz:'+identity)
   if prior and prior.get('identity_evidence'):continue
   L.upsert('discovery_edges',dict(edge_id='author_dietz:'+identity,source_key='author-dietz-20261105',target_key=target,relation='author_bibliography',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=f'Numbered entry ordinal{ordinal}, printed label({r["printed_number"]}), year heading{r["stated_year_heading"]}',target_metadata=row,reconciliation_state='matched_explicit_doi; source_typos_and_other_versions_pending' if len(matches)==1 else 'pending_identity_and_scope',run_id='author-dietz-20261105',date=L.DATE),'Retain laboratory bibliography without keyword or relevance cap')
 L.atomic(L.HERE/'dietz_bibliography_inventory.json',json.dumps({'entries':allrows,'unnumbered_sections_and_source_links':patent_rows,'caveats':['Public page DOI typography retained as candidates, not corrected silently.','Patents retained as separate paragraphs for subsequent record reconciliation; not journal papers.','Year headings are bibliography placement, not verified first-publication dates.']},indent=2,ensure_ascii=False))
 run=dict(run_id='author-dietz-20261105',route='author_bibliography',query_or_seed='Dietz laboratory numbered bibliography and linked pre2010 page',source_url=evs[0]['url'],date=L.DATE,pagination={'pages':2,'numbered_entries_enumerated':True,'patent_section_record_reconciliation':'pending'},provider_total=len(allrows),retrieved_count=len(allrows),pre2020_stated_years=sum(r['stated_bibliographic_year'] is not None and r['stated_bibliographic_year']<2020 for r in allrows),deduplicated_additions=len(allrows),additions_unit='Bibliography edges, not newly eligible works',evidence=evs,failures=[],closure_state='in_progress',checkpoint='Both numbered bibliography pages enumerated. Reconcile unmatched/malformed DOI candidates, patent records and all source relevance; verify publication dates. No lab-wide discovery closure claimed.')
 L.upsert('discovery_runs',run,'Record bounded laboratory-history coverage')
 print({'entries':len(allrows),'pre2020_year_heading':run['pre2020_stated_years'],'per_page':{e['local_file']:sum(r['source']==e['local_file'].split('/')[-1] for r in allrows) for e in evs},'validation':L.validate()},flush=True)
if __name__=='__main__':main()
