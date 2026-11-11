"""Enumerate the entire retained Choi laboratory history, without keyword caps."""
import hashlib,json,re
from urllib.parse import unquote
import ledger as L
from discover_dietz_bibliography import Paragraphs
from review_batch_0001 import evidence

def main():
 path=L.ROOT/'assets/research-20261105/choi-publications.html';url='https://choinano.org/publications/'
 parser=Paragraphs();parser.feed(path.read_text());rows=[];patents=False
 ev=evidence(path,url,'All90 publication paragraphs and8 patent paragraphs; Google Scholar navigation is not an enumerated bibliography')
 known={r.get('doi','').lower():r['registry_key'] for r in L.read('publication_reviews') if r.get('doi')}
 for p in parser.rows:
  txt=' '.join(' '.join(p['text']).split())
  if txt=='Patents':patents=True;continue
  years=re.findall(r'\((19\d{2}|20\d{2})\)',txt)
  if not years:continue
  ordinal=len(rows)+1;ds=set()
  for link in p['links']:
   match=re.search(r'10\.\d{4,9}/[^?#]+',unquote(link))
   if match:ds.add(re.sub(r'/(abstract|full|pdf)$','',match[0]).lower().rstrip('.'))
  matches={known[d] for d in ds if d in known}
  identity=hashlib.sha256(txt.encode()).hexdigest()[:16]
  target=next(iter(matches)) if len(matches)==1 else 'author_bibliography:choi:'+identity
  row=dict(ordinal=ordinal,text=txt,links=p['links'],stated_bibliographic_year=int(years[-1]),record_section='patent' if patents else 'publication',explicit_doi_candidates=sorted(ds),target_key=target)
  rows.append(row)
  L.upsert('discovery_edges',dict(edge_id='author_choi:'+identity,source_key='author-choi-20261105',target_key=target,relation='author_bibliography',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=f'Bibliographic paragraph{ordinal}; section{row["record_section"]}',target_metadata=row,reconciliation_state='matched_explicit_doi; relevance_and_versions_pending' if len(matches)==1 else 'pending_identity_and_scope',run_id='author-choi-20261105',date=L.DATE),'Retain complete primary laboratory list, including low-keyword publications and separately typed patents')
 counts={s:sum(r['record_section']==s for r in rows) for s in ['publication','patent']}
 pre={s:sum(r['record_section']==s and r['stated_bibliographic_year']<2020 for r in rows) for s in counts}
 assert counts=={'publication':90,'patent':8},counts
 L.atomic(L.HERE/'choi_bibliography_inventory.json',json.dumps(dict(entries=rows,counts=counts,pre2020_stated_years=pre,unfollowed_navigation=[u for u in parser.all_links if 'scholar.google' in u],caveats=['Listed years are not verified first-online dates.','Primary page mixes journal papers, books, chapters and patents; reconcile publication type individually.','No title/keyword exclusion or complete design assertion follows from enumeration.']),indent=2)+'\n')
 L.upsert('discovery_runs',dict(run_id='author-choi-20261105',route='author_bibliography',query_or_seed='Entire Choi lab publication and patent page',source_url=url,date=L.DATE,pagination={'pages':1,'all_bibliographic_paragraphs_enumerated':True,'google_scholar_navigation_followed':False},provider_total=len(rows),retrieved_count=len(rows),pre2020_stated_years=pre,deduplicated_additions=len(rows),additions_unit='Bibliography edges, not new publications or eligible designs',evidence=[ev],failures=[],closure_state='in_progress',checkpoint='90publication and8patent paragraphs enumerated;60publication and1patent entries state pre2020 years. Resolve PMID/publisher links, first-online dates, chapters and identities; follow citations and other lab/author sources. No laboratory-wide closure.'),'Record complete page enumeration and explicit unresolved author-history coverage')
 print(dict(counts=counts,pre2020=pre,matched=sum(r['target_key'] in known.values() for r in rows),validation=L.validate()))
if __name__=='__main__':main()
