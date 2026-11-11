"""Enumerate lab bibliography and source links without keyword screening."""
import json,re
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urlsplit,urlunsplit,unquote
import ledger as L
from review_batch_0001 import evidence
URL='https://www.shih.hms.harvard.edu/publications'
class Bibliography(HTMLParser):
 def __init__(self):super().__init__();self.active=False;self.tag=None;self.text=[];self.links=[];self.rows=[];self.year=None
 def handle_starttag(self,t,a):
  if t in ['p','h1','h2']:self.tag=t;self.text=[];self.links=[]
  if t=='a' and self.tag:
   u=dict(a).get('href','');v=urlsplit(u)
   if v.scheme in ['http','https']:
    # Only retain stable public paths; query parameters here are filenames/login hints.
    self.links.append(urlunsplit((v.scheme,v.netloc,v.path,'','')))
 def handle_data(self,d):
  if self.tag:self.text.append(d)
 def handle_endtag(self,t):
  if t!=self.tag:return
  s=' '.join(' '.join(self.text).replace('\u200b','').split())
  if t=='h1' and s=='PUBLICATIONS':self.active=True
  elif t=='h2' and self.active:self.active=False
  elif self.active and s:
   if re.fullmatch(r'(19|20)\d\d',s):self.year=int(s)
   elif self.year:
    years=[int(x) for x in re.findall(r'(?<![\w/])(19\d{2}|20\d{2})(?!\d)',s)]
    dois=[]
    for u in self.links:
     if urlsplit(u).netloc=='doi.org':dois.append(unquote(urlsplit(u).path.lstrip('/')).lower())
    self.rows.append(dict(ordinal=len(self.rows)+1,heading_year=self.year,citation=s,citation_years=years,doi_links=list(dict.fromkeys(dois)),links=list(dict.fromkeys(self.links)),source_links=list(dict.fromkeys(u for u in self.links if '/_files/' in u))))
  self.tag=None

def main():
 p=Bibliography();p.feed((L.ROOT/'assets/research-20261105/shih-publications.html').read_text());rows=p.rows
 selected=[r for r in rows if r['heading_year']<=2020 or any(y<=2020 for y in r['citation_years'])]
 assert len(rows)>len(selected)>40 and rows[-1]['citation'].startswith('Baier G')
 pubs={r['registry_key']:r for r in L.read('publication_reviews')};rid='author-priority-william-shih'
 ev=evidence(L.ROOT/'assets/research-20261105/shih-publications.html',URL,'All publication paragraphs between PUBLICATIONS heading and next h2; preserve citation years independently of section heading')
 for r in selected:
  matches=[d for d in r['doi_links'] if d in pubs];assert len(matches)<=1
  r['lead_key']='authorlead:shih:lab:'+str(r['ordinal']);r['target_key']=matches[0] if matches else r['lead_key'];r['identity_status']='explicit_doi_registry_match' if matches else 'pending_identity';r['review_status']='not_changed_by_bibliography_enumeration'
  L.upsert('discovery_edges',dict(edge_id=rid+':lab:'+str(r['ordinal']),source_key=rid,target_key=r['target_key'],relation='author_bibliography_lead',evidence_url=URL,local_file=ev['local_file'],sha256=ev['sha256'],locator='Publication paragraph ordinal'+str(r['ordinal']),citation=r['citation'],source_links=r['source_links'],reconciliation_state='explicit_doi_matched; date_scope_sources_pending' if matches else 'pending_identity_date_scope_sources',run_id=rid,date=L.DATE),'Retain author bibliography citation and source URLs without keyword screening')
 audit=dict(all_paragraphs=len(rows),selected_pre2020_or_boundary=len(selected),heading_year_counts=dict(Counter(r['heading_year'] for r in rows)),selected_registry_matches=sum(r['identity_status']=='explicit_doi_registry_match' for r in selected),selected_source_links=sum(len(r['source_links']) for r in selected),not_unique_new_publications=True)
 L.atomic(L.HERE/'shih_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=selected,all_entries=rows,evidence=[ev]),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==rid);run.update(source_url=URL,query_or_seed={'author':'William Shih','source':URL},retrieved_count=len(selected),deduplicated_additions=None,additions_unit='Bibliography occurrences, not new publications',pagination=audit,evidence=[ev],closure_state='in_progress',checkpoint='Official lab bibliography enumerated through1994; all pre2020/boundary entries and source links retained. Resolve date/version/title identity, including2004 heading followed by older citations; compare HMS paginated bibliography and DASH repository. Source archives and primary design review pending; no coverage closure.')
 L.upsert('discovery_runs',run,'Enumerate author history with explicit incompleteness')
 qpath=L.HERE/'author_priority_queue.json';q=json.loads(qpath.read_text())
 for a in q['authors']:
  if a['name']=='William Shih':a.update(status='in_progress',next_action=run['checkpoint'])
  if a['name']=='Lulu Qian':a['next_action']=next(r for r in L.read('discovery_runs') if r['run_id']=='author-priority-lulu-qian')['checkpoint']
 L.atomic(qpath,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
