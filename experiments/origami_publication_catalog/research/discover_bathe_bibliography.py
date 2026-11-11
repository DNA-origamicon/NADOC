"""Complementary public lab/CV author history, without title-based screening."""
import html,json,re,subprocess
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,urlunsplit,unquote,parse_qsl,urlencode
import ledger as L
from review_batch_0001 import evidence
URL='http://bathebionano.org/bathe-bionanolab-publications/'
class TextLinks(HTMLParser):
 def __init__(self):super().__init__();self.text=[];self.links=[]
 def handle_data(self,d):self.text.append(d)
 def handle_starttag(self,t,a):
  if t=='a':
   u=urljoin(URL,dict(a).get('href',''));v=urlsplit(u)
   if v.scheme in ['http','https']:
    query=urlencode([(k,val) for k,val in parse_qsl(v.query) if k.lower() in ['id','articleid','doi','uri']])
    self.links.append(urlunsplit((v.scheme,v.netloc,v.path,query,'')))
def parse_lab(s):
 matches=list(re.finditer(r'<h2\b[^>]*>\s*(\d+)\s*</h2>',s));out=[]
 for i,m in enumerate(matches):
  block=s[m.end():matches[i+1].start() if i+1<len(matches) else len(s)];block=block.split('data-elementor-type="footer"')[0]
  citation=re.search(r'data-widget_type="text-editor.default">.*?<div class="elementor-widget-container">(.*?)</div>',block,re.S);assert citation
  p=TextLinks();p.feed(citation[1]);text=' '.join(' '.join(p.text).split());q=TextLinks();q.feed(block)
  links=list(dict.fromkeys(q.links));dois=[]
  for u in links:
   mt=re.search(r'(10\.\d{4,9}/[^?#\s]+)',unquote(u))
   if mt:
    doi=mt[1].removesuffix('/abstract').removesuffix('/full').removesuffix('/meta').lower()
    if urlsplit(u).netloc=='academic.oup.com':doi='/'.join(doi.split('/')[:3])
    dois.append(doi)
  year_tokens=[int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',text)]
  out.append(dict(number=int(m[1]),citation=text,stated_years=year_tokens[:1],year_token_candidates=year_tokens,links=links,doi_links=list(dict.fromkeys(dois))))
 assert [r['number'] for r in out]==list(range(out[0]['number'],0,-1))
 return out

def parse_cv(s):
 part=s.split('Publications',1)[1].split('Patents',1)[0]
 part=re.sub(r'Mark Bathe[^\n]*\nProfessor[^\n]*\n77 Massachusetts[^\n]*\nBuilding[^\n]*\nCambridge[^\n]*','',part)
 matches=list(re.finditer(r'^[ \t]*(\d{1,3})\.?[ \t]+(?=[A-Z])',part,re.M));out=[]
 for i,m in enumerate(matches):
  citation=' '.join(part[m.end():matches[i+1].start() if i+1<len(matches) else len(part)].split())
  out.append(dict(number=int(m[1]),citation=citation,stated_years=[int(y) for y in re.findall(r'\((19\d{2}|20\d{2})\)',citation)]))
 assert [r['number'] for r in out]==list(range(out[0]['number'],0,-1))
 return out

def main():
 base=L.ROOT/'assets/research-20261105';lab=parse_lab((base/'bathe-publications-http.html').read_text());cv=parse_cv(subprocess.check_output(['pdftotext','-layout',str(base/'bathe-cv-2025.pdf'),'-']).decode())
 rid='author-priority-mark-bathe';ev=evidence(base/'bathe-publications-http.html',URL,'All numbered116–1 entries; HTTP public source after HTTPS certificate mismatch. First text-editor citation and associated links per numbered block.')
 ce=evidence(base/'bathe-cv-2025.pdf','https://meche.mit.edu/sites/default/files/cv/BatheMark-CV-2025.pdf','Publications section109–1; excludes patents/talks; strips repeated page headers. Missing dot at85 retained.')
 selected={source:[r for r in rows if not r['stated_years'] or any(y<=2020 for y in r['stated_years'])] for source,rows in [('lab',lab),('cv2025',cv)]}
 pubs={p['registry_key']:p for p in L.read('publication_reviews')};matched=0
 for source,rows,e in [('lab',selected['lab'],ev),('cv2025',selected['cv2025'],ce)]:
  for r in rows:
   keys=[d for d in r.get('doi_links',[]) if d in pubs];target=keys[0] if len(keys)==1 else f"authorlead:bathe:{source}:{r['number']}";matched+=len(keys)==1
   r.update(lead_key=f"authorlead:bathe:{source}:{r['number']}",target_key=target,identity_status='explicit_doi_registry_match' if len(keys)==1 else 'pending_identity')
   L.upsert('discovery_edges',dict(edge_id=rid+':'+source+':'+str(r['number']),source_key=rid,target_key=target,relation='author_bibliography_lead',evidence_url=e['url'],local_file=e['local_file'],sha256=e['sha256'],locator=source+' numbered entry'+str(r['number']),citation=r['citation'],source_links=r.get('links',[]),reconciliation_state='explicit_doi_registry_match; date_scope_sources_pending' if len(keys)==1 else 'pending_identity_date_scope_sources',run_id=rid,date=L.DATE),'Retain full in-window/boundary bibliography occurrences without title filtering')
 selected_ids={rid+':'+s+':'+str(r['number']) for s,rows in selected.items() for r in rows}
 historical=[]
 for edge in L.read('discovery_edges'):
  if edge['edge_id'].startswith(rid+':') and edge['edge_id'] not in selected_ids:
   edge.update(reconciliation_state='retained_history_outside_current_date_selection; primary_date_pending',selection_correction='Earlier selector mistook page/article-number year tokens for publication years. Citation states2023 for lab94 and2021 for lab70; retain evidence/history, outside current pre2020/boundary selection.')
   L.upsert('discovery_edges',edge,'Correct date selection without deleting discovery evidence')
   historical.append(edge['edge_id'])
 audit=dict(lab_all=len(lab),cv_all=len(cv),selected_counts={k:len(v) for k,v in selected.items()},retained_historical_edges=historical,retained_edge_count=len(selected_ids)+len(historical),explicit_doi_registry_matches=matched,unknown_date_entries={k:[r['number'] for r in v if not r['stated_years']] for k,v in selected.items()},not_unique_publications=True)
 L.atomic(L.HERE/'bathe_bibliography_inventory.json',json.dumps(dict(audit=audit,all_lab=lab,all_cv=cv,selected=selected,evidence=[ev,ce],limitations='Overlapping bibliographies are not unique/new publication counts. Primary identity, dates, versions, scope and source review remain pending; current-page coverage not exhaustive.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==rid);run.update(source_url=URL,query_or_seed={'author':'Mark Bathe','sources':[URL,ce['url']]},retrieved_count=sum(len(v) for v in selected.values()),deduplicated_additions=None,additions_unit='Overlapping bibliography citation occurrences',pagination=audit,evidence=[ev,ce],closure_state='in_progress',checkpoint='Official public lab page and MIT CV enumerated completely within their publication sections, retaining all pre2020/boundary/unknown-date entries. HTTPS hostname mismatch avoided through public HTTP URL; no authentication requested. Reconcile overlap and metadata errors (e.g. CV56 volume/page duplicated from55), verify primary dates and versions, acquire sources and follow citations. Independent histories and saturation passes remain open.')
 L.upsert('discovery_runs',run,'Save complementary author-history enumeration and coverage limits')
 qpath=L.HERE/'author_priority_queue.json';q=json.loads(qpath.read_text())
 for a in q['authors']:
  if a['name']=='Mark Bathe':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qpath,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
