"""Extract named bibliography anchors; preserve duplicate anchors and unresolved identities."""
import hashlib,html,json,re
from html.parser import HTMLParser
from urllib.parse import urljoin
import ledger as L
from review_batch_0001 import evidence
URL='https://yin.hms.harvard.edu/publications.html'
class Content(HTMLParser):
 def __init__(self):super().__init__();self.text=[];self.links=[]
 def handle_data(self,d):self.text.append(d)
 def handle_starttag(self,tag,attrs):
  if tag=='a':
   h=dict(attrs).get('href')
   if h:self.links.append(urljoin(URL,h))
def parse(source):
 anchors=list(re.finditer(r'<a\s+name\s*=\s*["\']([^"\']+)["\'][^>]*>',source,re.I));rows=[];seen={}
 for i,a in enumerate(anchors):
  name=a.group(1);seen[name]=seen.get(name,0)+1
  block=source[a.end():anchors[i+1].start() if i+1<len(anchors) else len(source)]
  core=re.split(r'<(?:ul|hr)\b',block,1,flags=re.I)[0];p=Content();p.feed(core);text=' '.join(' '.join(p.text).split());number=re.search(r'\[(\d+)\]',text)
  title=re.search(r'<b>(.*?)</b>',core,re.I|re.S);tp=Content()
  if title:tp.feed(title.group(1))
  explicit=re.findall(r'\bDOI:\s*(10\.\d{4,9}/[^\s\[<>]+)',text,re.I)
  linked=[u.split('doi.org/',1)[1] for u in p.links if 'doi.org/' in u]
  rows.append(dict(anchor=name,occurrence=seen[name],listed_year=int(name[:4]) if name[:4].isdigit() else None,number=int(number.group(1)) if number else None,title=' '.join(' '.join(tp.text).split()),citation=text,links=p.links,explicit_doi_candidates=sorted({x.rstrip('.,;').lower() for x in explicit+linked}),source_offset=a.start()))
 return rows

def main():
 path=L.ROOT/'assets/research-20261105/yin-publications.html';rows=parse(path.read_text());selected=[r for r in rows if r['listed_year'] and r['listed_year']<=2020];pre=[r for r in selected if r['listed_year']<2020]
 assert len(pre)==68 and {r['number'] for r in pre}==set(range(1,69)), 'Inspect numbering changes before updating coverage claim'
 assert all(r['title'] for r in pre)
 known={p['doi']:p['registry_key'] for p in L.read('publication_reviews') if p['doi']};rid='author-priority-peng-yin';matched=0
 ev=evidence(path,URL,'Named anchors; pre2020 printed entries68–1;2020-anchor entries retained for boundary checks. Core citation links exclude nested media lists.')
 for r in selected:
  candidates=r['explicit_doi_candidates'];doi=candidates[0] if len(candidates)==1 else ''
  target=known.get(doi,doi or 'authorlead:yin:'+hashlib.sha256((r['anchor']+'|'+str(r['occurrence'])).encode()).hexdigest()[:16]);matched+=doi in known
  r.update(target_key=target,identity_status='matched_registry_explicit_doi' if doi in known else 'pending',design_review_status='not_inferred_from_bibliography')
  L.upsert('discovery_edges',dict(edge_id=rid+':'+r['anchor']+':'+str(r['occurrence']),source_key=rid,target_key=target,relation='author_bibliography_lead',evidence_url=URL,local_file=ev['local_file'],sha256=ev['sha256'],locator='anchor '+r['anchor']+' occurrence'+str(r['occurrence'])+'; printed entry'+str(r['number']),citation=r['citation'],target_doi=doi,source_links=r['links'],reconciliation_state='matched_registry_explicit_doi; scope_dates_pending' if doi in known else 'pending_identity_date_and_scope',run_id=rid,date=L.DATE),'Retain author citation and source links without title-based classification')
 run=next(x for x in L.read('discovery_runs') if x['run_id']==rid)
 run.update(pagination={'named_anchors':len(rows),'pre2020_numbered_entries':68,'printed_numbers':'68 through1 contiguous','boundary2020_anchor_entries':len(selected)-68,'complete_for_this_named_anchor_inventory':True,'full_author_history_exhausted':False},retrieved_count=len(selected),deduplicated_additions=None,additions_unit='Bibliography rows, not new eligible publications',evidence=[ev],closure_state='in_progress',checkpoint='Enumerated68 printed pre2020 entries plus2020-anchor boundary records; duplicate2020.cnt anchors retained separately. Resolve remaining identities/first-online dates, cross-check headings vs anchor years, inspect papers/SI and follow references. Earlier-publications page and independent author search remain open.')
 L.upsert('discovery_runs',run,'Save uncapped numbered pre2020 bibliography enumeration')
 audit=dict(all_named_anchors=len(rows),pre2020_entries=len(pre),boundary2020_entries=len(selected)-len(pre),explicit_doi_registry_matches=matched,other_rows_pending=len(selected)-matched,duplicate_anchors=sorted({r['anchor'] for r in rows if r['occurrence']>1}),validation=L.validate())
 L.atomic(L.HERE/'yin_bibliography_inventory.json',json.dumps(dict(evidence=ev,entries=selected,all_anchor_inventory=rows,audit=audit),indent=2)+'\n');print(audit)
if __name__=='__main__':main()
