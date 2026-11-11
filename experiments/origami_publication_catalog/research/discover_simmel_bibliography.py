"""Retain all citations in the lab page's year sections; explicitly bound historical coverage."""
import html,json,re
from html.parser import HTMLParser
from urllib.parse import urljoin,unquote
import ledger as L
from review_batch_0001 import evidence
URL='https://www.bio.nat.tum.de/en/e14/publications/';RID='author-priority-friedrich-simmel'
class Text(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,d):self.parts.append(d)
def clean(s):
 p=Text();p.feed(s);return ' '.join(' '.join(p.parts).split())
def parse(s):
 matches=list(re.finditer(r'<h2[^>]*>\s*(20\d{2})\s*</h2>',s));out=[]
 for i,m in enumerate(matches):
  block=s[m.end():matches[i+1].start() if i+1<len(matches) else s.index('<h3',m.end())];year=int(m[1]);n=0
  for q in re.finditer(r'<p\b[^>]*>(.*?)(?=<p\b|</p>|</div>)',block,re.S):
   citation=clean(q[1])
   if not citation:continue
   n+=1;links=list(dict.fromkeys(urljoin(URL,html.unescape(u)) for u in re.findall(r'href="([^"]+)"',q[1])))
   dois=list(dict.fromkeys(unquote(u.split('doi.org/',1)[1]).split('?')[0].split('#')[0].rstrip('.,').lower() for u in links if 'doi.org/10.' in u))
   out.append(dict(heading_year=year,ordinal=n,citation=citation,links=links,doi_links=dois,citation_year_candidates=re.findall(r'\b(?:19|20)\d{2}\b',citation)))
 return out,[int(m[1]) for m in matches]
def main():
 path=L.ROOT/'assets/research-20261105/simmel-publications.html';rows,years=parse(path.read_text());assert years==list(range(2026,2007,-1))
 ev=evidence(path,URL,'All publication paragraphs under year headings2026–2008. No earlier-year section on this page; not full career coverage.')
 selected=[r for r in rows if r['heading_year']<=2020];pubs={p['registry_key']:p for p in L.read('publication_reviews')};matched=0
 for r in selected:
  keys=[d for d in r['doi_links'] if d in pubs];target=keys[0] if len(keys)==1 else f"authorlead:simmel:{r['heading_year']}:{r['ordinal']}";matched+=len(keys)==1
  r.update(target_key=target,identity_status='explicit_doi_registry_match' if len(keys)==1 else 'pending_identity')
  L.upsert('discovery_edges',dict(edge_id=RID+':lab:'+str(r['heading_year'])+':'+str(r['ordinal']),source_key=RID,target_key=target,relation='author_bibliography_lead',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Year'+str(r['heading_year'])+' paragraph'+str(r['ordinal']),citation=r['citation'],source_links=r['links'],reconciliation_state='explicit_doi_registry_match; primary_date_scope_pending' if len(keys)==1 else 'pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain all year-section leads without title filtering')
 audit=dict(all_occurrences=len(rows),selected_occurrences=len(selected),year_headings=years,per_year={str(y):sum(r['heading_year']==y for r in rows) for y in years},explicit_doi_registry_matches=matched,missing_coverage='Before2008 absent from this page; independent histories not enumerated',counts_are_not_unique_works=True)
 L.atomic(L.HERE/'simmel_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=rows,selected=selected,evidence=[ev],limitations='Lab year headings are discovery dates, not verified first-online dates. All selected paragraph occurrences retained including reviews and low-keyword work; identity, versions and sources pending.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run.update(source_url=URL,query_or_seed={'author':'Friedrich Simmel','source':URL},retrieved_count=len(rows),deduplicated_additions=None,additions_unit='Year-section citation occurrences',pagination=audit,evidence=[ev],closure_state='in_progress',checkpoint='Enumerated lab year sections2026–2008, retaining2008–2020 leads. Pre2008 missing from page; enumerate TUM faculty/organization histories and other independent sources, reconcile identities/dates/types, follow citations. No title cap or saturation claim.')
 L.upsert('discovery_runs',run,'Save bounded author-history enumeration with pre2008 gap')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Friedrich Simmel':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
