"""Retain current lab bibliography and older CV; no title-based disposition."""
import html,json,re,subprocess
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
import ledger as L
from review_batch_0001 import evidence
URL='https://www.qianlab.caltech.edu/publications.html'
class P(HTMLParser):
 def __init__(self):super().__init__();self.text=[];self.links=[]
 def handle_data(self,d):self.text.append(d)
 def handle_starttag(self,t,a):
  if t=='a':
   u=dict(a).get('href','');u=urljoin(URL,u);v=urlsplit(u)
   if u and not v.query and 'author-tokens' not in u and '/stoken/' not in u:self.links.append(u)
def parse_page(s):
 rows=[];section=None
 for m in re.finditer(r'<h4\b[^>]*>(.*?)</h4>|<p\b[^>]*>(.*?)</p>',s,re.I|re.S):
  if m[1]:section=html.unescape(re.sub('<[^>]*>','',m[1]));continue
  p=P();p.feed(m[2]);txt=' '.join(' '.join(p.text).split());num=re.match(r'\[(\d+)\]',txt)
  if not num:continue
  years=[int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',txt)]
  rows.append(dict(section=section,number=int(num[1]),citation=txt,stated_years=years,source_links=p.links))
 return rows

def main():
 base=L.ROOT/'assets/research-20261105';rows=parse_page((base/'qian-publications.html').read_text());assert len(rows)==23
 assert {r['number'] for r in rows if r['section']=='Experimental work'}==set(range(1,18))
 assert {r['number'] for r in rows if r['section']=='Theoretical work'}==set(range(1,7))
 selected=[r for r in rows if any(y<=2020 for y in r['stated_years'])];assert len(selected)==15
 text=subprocess.check_output(['pdftotext','-layout',str(base/'qian-cv-sep2019.pdf'),'-']).decode();part=text.split('Refereed Publications',1)[1].split('Google Scholar citation',1)[0];matches=list(re.finditer(r'^\s*(\d+)\.\s+',part,re.M));cv=[]
 for i,m in enumerate(matches):
  citation=part[m.end():matches[i+1].start() if i+1<len(matches) else len(part)];citation=re.sub(r'(?m)^\s*\d+\s*$','',citation)
  cv.append(dict(number=int(m[1]),citation=' '.join(citation.split()),note='CV citation may include commentary references; preserve and reconcile separately'))
 assert [r['number'] for r in cv]==list(range(1,19))
 rid='author-priority-lulu-qian';ev=evidence(base/'qian-publications.html',URL,'All23 numbered paragraphs: experimental17–1,theoretical6–1;15 paragraphs include pre2020 or2020 boundary dates')
 cv_ev=evidence(base/'qian-cv-sep2019.pdf','https://www.qianlab.caltech.edu/Qian_CV_Sep2019.pdf','Refereed Publications pp2–3 entries1–18; talks not enumerated as publications')
 run=next(x for x in L.read('discovery_runs') if x['run_id']==rid);run.update(source_url=URL,query_or_seed={'name':'Lulu Qian','affiliation':'Caltech','sources':[URL,cv_ev['url']]},pagination={'lab_numbered_entries':23,'lab_selected_boundary_or_pre2020_paragraphs':15,'CV_refereed_entries':18,'full_history_exhausted':False},retrieved_count=33,deduplicated_additions=None,additions_unit='Source citation occurrences; overlap and versions unreconciled',evidence=[ev,cv_ev],closure_state='in_progress',checkpoint='Current lab page and Sep2019 CV enumerated. CV14–18 supply older citations absent from current page, including asymmetric origami2010 and China-map2006. Reconcile33 source occurrences, split embedded conference/journal/commentary records and dates; review paper/SI sources. Historical personal bibliography and independent author search remain open.')
 L.upsert('discovery_runs',run,'Enumerate complementary author bibliographies without claiming full coverage')
 for source,items,e in [('lab',selected,ev),('cv2019',cv,cv_ev)]:
  for r in items:
   suffix=(r.get('section','').split()[0].lower()+':' if source=='lab' else '')+str(r['number']);lead='authorlead:qian:'+source+':'+suffix;r['lead_key']=lead
   L.upsert('discovery_edges',dict(edge_id=rid+':'+source+':'+suffix,source_key=rid,target_key=lead,relation='author_bibliography_lead',evidence_url=e['url'],local_file=e['local_file'],sha256=e['sha256'],locator=source+' '+suffix,citation=r['citation'],source_links=r.get('source_links',[]),reconciliation_state='pending_identity_date_version_and_scope',run_id=rid,date=L.DATE),'Retain each source occurrence; do not duplicate publication records')
 L.atomic(L.HERE/'qian_bibliography_inventory.json',json.dumps(dict(lab_all=rows,lab_pre2020_and_boundary=selected,cv_refereed=cv,evidence=[ev,cv_ev],source_occurrences=33,not_unique_publications=True),indent=2)+'\n')
 qpath=L.HERE/'author_priority_queue.json';q=json.loads(qpath.read_text())
 for a in q['authors']:
  if a['name']=='Lulu Qian':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qpath,json.dumps(q,indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
