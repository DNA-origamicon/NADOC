"""Enumerate every numbered journal-section entry; never infer relevance or merge."""
import hashlib
import json
import re
import subprocess
import unicodedata
import ledger as L
from review_batch_0001 import evidence

def normalized(s):
 return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', s).lower())

def main():
 path=L.ROOT/'assets/research-20261105/hao-yan-asu-cv.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f')
 active=False; entries=[]; current=None
 for page,text in enumerate(pages,1):
  for line in text.splitlines():
   if line.strip()=='1. Journal Publications': active=True; continue
   if active and line.strip()=='2. Book Chapters': active=False; break
   if not active: continue
   m=re.match(r'^\s*(\d{1,3})(?:\.\s*|\s+)([A-Z](?:[.]|[a-z]).*)$',line)
   if m:
    current=dict(number=int(m[1]),pdf_pages=[page],raw_lines=[m[2]])
    entries.append(current)
   elif current and line.strip() and not re.fullmatch(r'\s*\d+\s*',line):
    current['raw_lines'].append(line.strip())
    if page not in current['pdf_pages']:current['pdf_pages'].append(page)
 assert [e['number'] for e in entries]==[n for n in range(243,0,-1) if n not in {228,229,230,231}], 'Numbering anomaly requires source inspection'
 pubs=L.read('publication_reviews')
 for e in entries:
  e['raw_text']=' '.join(e.pop('raw_lines'))
  e['raw_text_note']='Includes source publicity/subsection text until next numbered entry; not a parsed authoritative citation.'
  e['year_tokens']=sorted(set(re.findall(r'\b(?:19|20)\d{2}\b',e['raw_text'])))
  e['year_scope']='requires_primary_date_verification'
  if not e['year_tokens']:e['year_scope']='undated_pending'
  elif all(int(y)<2006 for y in e['year_tokens']):e['year_scope']='earlier_methodological_lead'
  elif all(int(y)>=2020 for y in e['year_tokens']):e['year_scope']='later_or_boundary_verification_pending'
  else:e['year_scope']='pre2020_or_mixed_year_lead'
  raw=normalized(e['raw_text']); candidates=[]
  for p in pubs:
   title=p.get('title') or p.get('legacy_record',{}).get('publication','')
   t=normalized(title)
   if len(t)>=30 and t in raw:candidates.append(p['registry_key'])
  e['title_match_candidates']=sorted(set(candidates))
  e['identity_status']='pending; normalized title substring is a candidate only'
 output=dict(source_file=str(path.relative_to(L.ROOT)),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),method='Complete numbered journal-section extraction; descending243..1 with source gap228–231 asserted; raw text retained; no keyword relevance filter',entries=entries,limitations=['Source numbering skips228–231, visually verified PDFp5; do not fabricate missing entries.','Heading includes proceedings and submitted manuscripts: publication types/dates need individual verification.','Book chapters, patents and invited presentations are separate sections not enumerated by this extraction.','CV is not an exhaustive laboratory or author-history closure claim.'])
 out=L.HERE/'hao_yan_cv_journal_inventory.json';L.atomic(out,json.dumps(output,indent=2)+'\n')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='author-hao-yan-asu-cv')
 ev=evidence(out,run['source_url'],'All239 present numbered journal-section entries with page locators and unresolved title-match candidates')
 if ev not in run['evidence']:run['evidence'].append(ev)
 for e in entries:
  target=f"lead:hao-yan-cv:journal:{e['number']:03d}"
  L.upsert('discovery_edges',dict(edge_id='author-hao-yan-asu-cv:'+str(e['number']),source_key=run['run_id'],target_key=target,relation='author_bibliography_lead',evidence_url=run['source_url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='CV PDF pages '+','.join(map(str,e['pdf_pages']))+' entry '+str(e['number']),reconciliation_state='bibliographic_identity_and_date_pending',candidate_registry_keys=e['title_match_candidates'],run_id=run['run_id'],date=L.DATE),'Retain full author bibliography entry; matching and classification remain pending')
 run.update(retrieved_count=len(entries),retrieved_unit='numbered journal-section entries, including proceedings/submitted/later records',provider_total=239,deduplicated_additions=239,additions_unit='stable pending discovery targets, not new publications',pagination={'complete':True,'scope':'numbered Journal Publications section only','numbering':'243 through1 with missing228–231 visually verified on PDFp5'},checkpoint='Reconcile all239 present entries, prioritize pre2020 or mixed-date entries without dropping low-keyword titles; inspect separate book-chapter section and other author/lab routes.',closure_state='in_progress')
 L.upsert('discovery_runs',run,'Enumerate complete numbered section while leaving identity/date and broader coverage open')
 audit=dict(entries=len(entries),with_title_candidates=sum(bool(e['title_match_candidates']) for e in entries),without_title_candidates=sum(not e['title_match_candidates'] for e in entries),year_scope_counts={v:sum(e['year_scope']==v for e in entries) for v in sorted({e['year_scope'] for e in entries})},validation=L.validate())
 L.atomic(L.HERE/'hao_yan_cv_journal_audit.json',json.dumps(audit,indent=2)+'\n');print(json.dumps(audit,indent=2))

if __name__=='__main__':main()
