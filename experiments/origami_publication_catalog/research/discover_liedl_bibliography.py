"""Enumerate lab year sections and separate review section; retain missing-link leads."""
import html,json,re
from urllib.parse import urljoin,urlsplit,unquote
import ledger as L
from review_batch_0001 import evidence
from discover_simmel_bibliography import clean
URL='https://www.physik.lmu.de/softmatter/en/publications/liedl-group/';RID='author-priority-tim-liedl'
def main():
 path=L.ROOT/'assets/research-20261105/liedl-publications.html';s=path.read_text();ms=list(re.finditer(r'<h3>(20\d{2}|Reviews)</h3>',s));assert [m[1] for m in ms]==[str(y) for y in range(2024,2003,-1)]+['Reviews'];rows=[];counts={}
 for i,m in enumerate(ms):
  b=s[m.end():ms[i+1].start() if i+1<len(ms) else s.index('</div>',m.end())];ps=re.findall(r'<p\b[^>]*>(.*?)</p>',b,re.S);assert len(ps)==len(re.findall(r'<p\b',b));counts[m[1]]=len(ps)
  for n,p in enumerate(ps,1):
   parts=[clean(t) for t in re.split(r'<br\s*/?>',p)];citation=clean(p.replace('<br>',' '));assert citation;links=[];omitted=0
   for u in re.findall(r'href="([^"]+)"',p):
    u=urljoin(URL,html.unescape(u));v=urlsplit(u)
    if '/stoken/' in v.path or any(x in v.query.lower() for x in ['token=','signature=','key-pair-id=']):omitted+=1;continue
    links.append(u)
   links=list(dict.fromkeys(links));dois=[]
   for u in links:
    mm=re.search(r'(10\.\d{4,9}/[^?#]+)',unquote(u))
    if mm:dois.append(mm[1].removesuffix('/full').removesuffix('/abstract').lower())
   years=[int(x) for x in re.findall(r'\((20\d{2}|19\d{2})\)',citation)]
   rows.append(dict(section=m[1],ordinal=n,citation=citation,components=parts,title=parts[1] if len(parts)>=3 else None,links=links,doi_links=list(dict.fromkeys(dois)),citation_years=years,access_links_omitted=omitted,selection_year=int(m[1]) if m[1].isdigit() else min(years) if years else None))
 ev=evidence(path,URL,'Every paragraph in2024–2004 sections and separate Reviews section; source labels downloadpdf/getarticle may lack actual links')
 selected=[r for r in rows if r['selection_year'] is None or r['selection_year']<=2020];pubs={p['registry_key']:p for p in L.read('publication_reviews')};matched=0
 for r in selected:
  keys=[d for d in r['doi_links'] if d in pubs];target=keys[0] if len(keys)==1 else f"authorlead:liedl:{r['section']}:{r['ordinal']}";matched+=len(keys)==1;r.update(target_key=target,identity_status='explicit_doi_registry_match' if len(keys)==1 else 'pending_identity')
  L.upsert('discovery_edges',dict(edge_id=RID+':lab:'+r['section']+':'+str(r['ordinal']),source_key=RID,target_key=target,relation='author_bibliography_lead',citation=r['citation'],source_links=r['links'],evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Section'+r['section']+' paragraph'+str(r['ordinal']),reconciliation_state='explicit_doi_registry_match; primary_dates_scope_pending' if len(keys)==1 else 'pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Preserve all author-history and review leads without title relevance filtering')
 audit=dict(all_occurrences=len(rows),selected_occurrences=len(selected),section_counts=counts,explicit_doi_registry_matches=matched,selected_without_links=sum(not r['links'] for r in selected),not_unique_work_count=True)
 L.atomic(L.HERE/'liedl_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=rows,selected=selected,evidence=[ev],limitations='Current lab page ends2004 and starts2024; independent LMU repository history and title/version reconciliation pending. Year labels are not primary online dates; reviews retained separately as leads.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run.update(source_url=URL,query_or_seed={'author':'Tim Liedl','source':URL},retrieved_count=len(rows),deduplicated_additions=None,additions_unit='Bibliography paragraph occurrences',pagination=audit,evidence=[ev],closure_state='in_progress',checkpoint='Lab sections2024–2004 and Reviews enumerated fully; reconcile identities, dates, source links and low-keyword records. Compare LMU repository author history; source labels are sometimes plain text without links. No saturation claim.')
 L.upsert('discovery_runs',run,'Save bounded author-history enumeration and missing links')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Tim Liedl':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
