"""Human-reviewed rapid source gate; no automated scientific or completeness promotion."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 index=json.loads((L.HERE/'sequence_pilot_0001_index.json').read_text());rows=L.read('publication_reviews');by={r['registry_key']:r for r in rows}
 assert [r['key'] for r in index['records']]==json.loads((L.HERE/'sequence_pilot_0001_keys.json').read_text()) and len(index['records'])==10
 notes=[
 ('prioritize', 'PDF3-11: explicitly named Origami Helper Strands list;208 candidate strings, named rows inspected. Qualifying large staple list.'),
 ('defer_below_threshold','PDF2 TableS1 visually inspected:6/10-strand cube variants and aptamer controls, well below100 entries. Image table explains zero text matches; not an absence claim.'),
 ('prioritize','PDF14-18 Table1 microtubule analog staple list alone has213 candidate entries; table heading and structure-strand rows inspected. Exclude scaffold text onPDF2/35/36 from gate count.'),
 ('prioritize','PDF8-14 Robot staple sequences:285 candidate strings; numbered core rows inspected. Scaffold onPDF6-7 excluded.'),
 ('prioritize','PDF38-42 first oligonucleotide list has207 candidate strings with Sequence/Length columns; table caption identifies42helix bundle. Scaffold diagrams onPDF1-3/31 excluded.'),
 ('prioritize','PDF2-12 nanotube staple list has named Tube1-171 entries; multiline sequence fragments inflate raw counts. Named strand indexing,not554wholePDF matches,supports gate.'),
 ('defer_no_qualifying_list','PDF44-57 Tables1-37 contain many small dye-labelled oligo configurations; wholePDF221strings must not be pooled as one staple list. Inspected headings andPDF44rows; no qualifying100-entry staple table found in indexed supplement.'),
 ('defer_no_qualifying_list','PDF15/17/23/28: repeated short ARE functional oligos,8candidate strings/5unique. Indexed supplement has no qualifying staple list; retain literature relevance as unresolved.'),
 ('prioritize','PDF12-16 Table1 origami-track staple list has210candidate strings; start/end/sequence/length columns and core rows inspected. LaterTable2 distinct3Dtrack.'),
 ('prioritize','PDF28-30 Table1 cross-shaped origami staples has198candidate strings in two named-entry columns;Table3/4biotin variants separate.')]
 report=[]
 for r,(decision,note) in zip(index['records'],notes):
  p=by[r['key']];evs=[evidence(L.ROOT/f['local_file'],f['url'],note+' Rapid source gate only; no complete article or sequence verification.') for f in r['files']]
  triage=dict(run_id='SEQ0001',decision=decision,threshold=100,note=note,evidence=evs,source_coverage='Recorded available PDF supplements only; other linked/native/spreadsheet sources not exhausted.',date=L.DATE)
  p['source_triage']=triage;p['review_stage']='metadata_screened';p['reviewer']='Codex rapid source/table triage';p['run_id']='SEQ0001';p['date']=L.DATE
  for e in evs:
   if e not in p['evidence']:p['evidence'].append(e)
  p['rationale']='Rapid source gate recorded; literature relevance,design identity and catalog eligibility not adjudicated. '+note
  p['access']='recorded_PDF_supplements_available'
  q='Detailed design processing prioritized only if source_triage qualifies; deferred sources retained,not inferred irrelevant or permanently absent.'
  if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
  L.upsert('publication_reviews',p,'User-authorized100-sequence source triage; preserve scientific uncertainty')
  report.append(dict(registry_key=r['key'],**triage))
 patents=[]
 for p in L.read('publication_reviews'):
  if 'patent' not in str(p.get('publication_type','')).lower():continue
  p['census_scope']='excluded_patent_user_instruction_2026-11-05';p['catalog_eligibility']='excluded';p['source_triage']=dict(decision='exclude_patent',reason='User explicitly excludes patents regardless of sources.',date=L.DATE)
  if p['review_stage']=='unreviewed':p['review_stage']='metadata_screened'
  p['reviewer']='Codex user-scope patent exclusion based on retained publication-type metadata'
  pe=evidence(L.ROOT/'publication_registry.json','',p['registry_key']+': retained Patent publication type; user scope exclusion,not a new content decision.')
  if pe not in p['evidence']:p['evidence'].append(pe)
  note=' Out of active census and design-processing scope by explicit user patent exclusion; prior molecular relevance/evidence retained.'
  if note not in p['rationale']:p['rationale']+=note
  L.upsert('publication_reviews',p,'Apply explicit user patent scope exclusion; preserve stable identity/history');patents.append(p['registry_key'])
 out=dict(run_id='SEQ0001',selection='First10previouslyunreviewed records with recordedPDFsupplements in registry order; availability-biased pilot,not representative corpus yield.',records=report,patents_excluded=patents,results=dict(pilot_records=10,prioritize=7,defer=3),extraction_seconds=index['extraction_seconds'],limitations='Elapsed extraction time excludes human inspection and workflow implementation. No comparable baseline timing; no measured end-to-end speedup claim. No designs certified or counted.',validation=L.validate())
 L.atomic(L.HERE/'sequence_pilot_0001_report.json',json.dumps(out,indent=2)+'\n')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0017')
 action='SEQ0001parallel source-triage pilot:10records screened,7priority/3deferred;all3patents excluded by user scope. This is source triage,not10additional fulltext reviews.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Process7priority sources in sequence_pilot_0001_report.json; expand balanced rapid screening with frozen keys.','Skip all patents,including epmc:1842/1391; retain evidence but no patent followups.','Resume other B0017 records with source gate; deferred records stay explicit. FNANO deferred.'])
 L.upsert('batches',b,'Save rapid source pilot and supersede patent followup queue')
 print(json.dumps({k:v for k,v in out.items() if k not in ['records']},indent=2))
if __name__=='__main__':main()
