"""Retain all official bibliography occurrences, including undated submitted leads."""
import json,re,html
from urllib.parse import urljoin
from discover_simmel_bibliography import clean
import ledger as L
from review_batch_0001 import evidence
URL='https://doye.chem.ox.ac.uk/pub.html';RID='author-priority-jonathan-doye'
def parse(s):
 s=re.sub(r'<!--.*?-->','',s,flags=re.S)
 start=s.index('<h2>Chemical Physics</h2>');s=s[start:]
 heads=list(re.finditer(r'<h[23][^>]*>(.*?)</h[23]>',s,re.S));out=[];section=None;year=None
 for i,h in enumerate(heads):
  title=clean(h[1])
  if re.fullmatch(r'\d{4}',title):year=int(title)
  else:section=title;year=None
  block=s[h.end():heads[i+1].start() if i+1<len(heads) else len(s)]
  entries=re.findall(r'<li\b[^>]*>(.*?)(?=</li>|<li\b|</ul>)',block,re.S|re.I)
  assert len(entries)==len(re.findall(r'<li\b',block,re.I))
  for n,raw in enumerate(entries,1):
   citation=clean(raw);links=list(dict.fromkeys(urljoin(URL,html.unescape(u)) for u in re.findall(r'href="([^"]+)"',raw)))
   submitted=bool(re.search(r'\bsubmitted\b',citation,re.I));dates=re.findall(r'\((19\d\d|20\d\d)\)',citation)
   r=dict(section=section,heading_year=year,ordinal=n,citation=citation,links=links,citation_year_candidates=dates,submitted=submitted)
   r['selected']=submitted or (year is not None and year<=2020) or (year is None and (not dates or min(map(int,dates))<=2020))
   r['selection_reason']='undated_submitted_not_dated_by_heading' if submitted else 'pre2020_or_boundary_or_unknown' if r['selected'] else 'post2020_heading'
   out.append(r)
 assert len(out)==len(re.findall(r'<li\b',s,re.I))
 return out

def main():
 path=L.ROOT/'assets/research-20261105/doye-publications.html';rows=parse(path.read_text());selected=[r for r in rows if r['selected']]
 ev=evidence(path,URL,'All list items in Chemical Physics year sections2024–1992 and Other; submitted items retained regardless of heading. Every raw li reconciled to one parsed occurrence.')
 for r in selected:
  suffix=('other' if r['heading_year'] is None else str(r['heading_year']))+':'+str(r['ordinal']);r['target_key']='authorlead:doye:'+suffix
  L.upsert('discovery_edges',dict(edge_id=RID+':lab:'+suffix,source_key=RID,target_key=r['target_key'],relation='author_bibliography_lead',citation=r['citation'],source_links=r['links'],evidence_url=URL,local_file=ev['local_file'],sha256=ev['sha256'],locator=r['section']+' '+str(r['heading_year'])+' item'+str(r['ordinal']),reconciliation_state='pending_identity_date_type_scope_sources',run_id=RID,date=L.DATE),'Retain official bibliography without keyword relevance filter')
 audit=dict(all_occurrences=len(rows),selected_occurrences=len(selected),undated_submitted=sum(r['submitted'] for r in rows),years=sorted({r['heading_year'] for r in rows if r['heading_year'] is not None}),per_year={str(y):sum(r['heading_year']==y for r in rows) for y in sorted({r['heading_year'] for r in rows if r['heading_year'] is not None})},other_section_occurrences=sum(r['heading_year'] is None for r in rows),raw_li_count_reconciled=True,counts_are_not_unique_works=True)
 L.atomic(L.HERE/'doye_bibliography_inventory.json',json.dumps(dict(audit=audit,entries=rows,selected=selected,evidence=[ev],limitations='Year headings are not primary dates. Older papers and non-DNA work retained for screening, not inclusion. Submitted papers under2024 may have earlier preprints; inspect linked abstracts. No independent history/citation saturation established.'),indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']==RID);run.update(source_url=URL,query_or_seed={'author':'Jonathan Doye','source':URL},retrieved_count=len(rows),deduplicated_additions=None,additions_unit='bibliography occurrences',pagination=audit,evidence=[ev],closure_state='in_progress',checkpoint='Enumerated all official bibliography items; next retrieve linked abstracts for selected entries, reconcile identities/versions/dates, rotate low-keyword records and compare independent histories. Submitted entries not dated from2024heading.')
 L.upsert('discovery_runs',run,'Save auditable uncapped bibliography inventory')
 qp=L.HERE/'author_priority_queue.json';q=json.loads(qp.read_text())
 for a in q['authors']:
  if a['name']=='Jonathan Doye':a.update(status='in_progress',next_action=run['checkpoint'])
 L.atomic(qp,json.dumps(q,indent=2)+'\n');print(audit);print(L.validate())
if __name__=='__main__':main()
