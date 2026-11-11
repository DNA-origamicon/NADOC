"""Enumerate all named bibliography paragraphs; no relevance cap or title filter."""
import re,hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin
import ledger as L
from review_batch_0001 import evidence
class Bibliography(HTMLParser):
 def __init__(self):super().__init__();self.rows=[];self.current=None
 def handle_starttag(self,t,attrs):
  a=dict(attrs)
  if t=='p' and a.get('id'):self.current={'id':a['id'],'text':[],'links':[]}
  elif t=='a' and self.current is not None and a.get('href'):self.current['links'].append(urljoin('https://bionano.ucsf.edu/publications',a['href']))
 def handle_data(self,d):
  if self.current is not None:self.current['text'].append(d)
 def handle_endtag(self,t):
  if t=='p' and self.current is not None:self.rows.append(self.current);self.current=None

def main():
 path=L.ROOT/'assets/research-20261105/douglas-lab-publications.html';parser=Bibliography();parser.feed(path.read_text());ev=evidence(path,'https://bionano.ucsf.edu/publications','All p elements with publication anchor IDs; older-publications link followed separately')
 known={r['doi']:r['registry_key'] for r in L.read('publication_reviews') if r['doi']};before=len(L.read('discovery_edges'));years=[]
 last_index={row['id']:i for i,row in enumerate(parser.rows)}
 for i,row in enumerate(parser.rows):
  original_id=row['id']
  if i!=last_index[original_id]:row['id']+=':'+hashlib.sha256(''.join(row['text']).encode()).hexdigest()[:12]
  txt=' '.join(' '.join(row['text']).split());match=re.search(r'\((20\d\d|19\d\d)\)',txt);year=int(match[1]) if match else None;years.append(year)
  dois=[]
  for link in row['links']:
   m=re.search(r'(10\.\d{4,9}/[^?#]+)',link)
   if m:dois.append(m[1].lower().removesuffix('v1').removesuffix('v2'))
  target=next((known[d] for d in dois if d in known),'author_bibliography:douglas:'+row['id'])
  L.upsert('discovery_edges',dict(edge_id='author_douglas:'+row['id'],source_key='author-douglas-20261105',target_key=target,relation='author_bibliography',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='HTML p#'+original_id+'; publication paragraph ordinal '+str(i+1),target_metadata={'bibliographic_text':txt,'links':row['links'],'stated_year':year,'explicit_doi_candidates':dois},reconciliation_state='matched_explicit_doi; other_versions_pending' if target in known.values() else 'pending_identity_and_scope',run_id='author-douglas-20261105',date=L.DATE),'Retain every bibliography entry including later background leads')
 run=dict(run_id='author-douglas-20261105',route='author_bibliography',query_or_seed='Shawn M Douglas, UCSF; linked main lab bibliography',source_url=ev['url'],date=L.DATE,pagination={'complete_for_this_page':True,'older_link':'http://www.shawndouglas.com/publications','older_page_reviewed':False},provider_total=len(parser.rows),retrieved_count=len(parser.rows),pre2020_stated_years=sum(y is not None and y<2020 for y in years),deduplicated_additions=sum(e.get('run_id')=='author-douglas-20261105' for e in L.read('discovery_edges')),additions_unit='bibliography edges, not newly eligible works',evidence=[ev],failures=[],closure_state='in_progress',checkpoint='All current-page entries retained; follow older bibliography and resolve PMID/preprint/journal identities and source relevance. Later entries remain discovery leads only.')
 L.upsert('discovery_runs',run,'Enumerate actual laboratory publication history beyond keyword searches')
 print({'entries':len(parser.rows),'pre2020_stated_years':run['pre2020_stated_years'],'validation':L.validate()})
if __name__=='__main__':main()
