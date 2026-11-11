"""First source gate over persisted batch; missing sources are an inactive gap,not irrelevance."""
import json,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 b=next(x for x in L.read('batches') if x['batch_id']=='B0017');rows={r['registry_key']:r for r in L.read('publication_reviews')};report=[]
 for k in b['input_keys']:
  p=rows[k];old=p.get('source_triage')
  if old:
   report.append(dict(registry_key=k,decision=old['decision'],basis='Existing source triage retained'));continue
  legacy=p.get('legacy_record',{});evs=[];note='';decision='no_qualifying_table_found';scope='Saved registry supplement links/downloads and current evidence references; no exhaustive publisher/repository search. No linked supplement means unknown availability,not proven absence.'
  if k=='10.1038/nature04586':
   decision='prioritize';note='Existing inspected SI1S38PDF45 has225uniquely named bridged tall-rectangle staple rows; gate passes, exact experimentalvariant sourcecompleteness remains unresolved.'
   evs=[e for e in p['evidence'] if e.get('local_file','').endswith('rothemund2006-s1.pdf')]
  elif k=='10.1093/nar/gkp005':
   path=L.ROOT/'assets'/legacy['xml_file'];root=E.parse(path).getroot();counts=[len(t.findall('.//tbody/tr')) for t in root.findall('.//table-wrap')];assert counts==[4,6,32]
   note='Saved primary XML Tables1-3 list4,6,32strands for tetrahedron,cube,soccerball; no100-entry table. XML supplement links absent. Defer detailed design review.'
   evs=[evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2673411/fullTextXML','Tables1-3 captions and row counts inspected; source gate only,not complete paper review.')]
  elif legacy.get('xml_file'):
   path=L.ROOT/'assets'/legacy['xml_file'];root=E.parse(path).getroot()
   tables=root.findall('.//table-wrap');supp=root.findall('.//supplementary-material')
   note=f'Saved XML contains{len(tables)}table-wrap elements and{len(supp)}supplementary-material elements; no qualifying sequence table or recorded supplemental download. No fulltext/design review performed.'
   if k=='PMC2588530':note+=' Sole table is cover notice with paper-folding model credit,not a DNA sequence table.'
   evs=[evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/'+k+'/fullTextXML','Source inventory: table/supplement elements inspected; no complete content review.')]
  elif k=='10.55838/1980-3540.ge.2007.32':
   note='Prior fulltext review established classroom paper-folding model; no molecular staple table. Preserve existing not_origami classification.';evs=p['evidence'][:1]
  else:
   assert not legacy.get('downloaded_supplements') and not legacy.get('supplement_links')
   note='No qualifying staple table found: saved registry has no downloaded supplements or supplement links; current publication evidence has no acquired sequence source. Source availability remains unknown. Move on without rescue retrieval.'
   evs=[evidence(L.ROOT/'publication_registry.json','',k+': recorded source inventory,empty downloaded_supplements andsupplement_links; not proof of publisher source absence.')]
  triage=dict(run_id='SEQ0002',decision=decision,threshold=100,note=note,source_coverage=scope,evidence=evs,date=L.DATE,reopen_condition='New source evidence or explicit user request only')
  p['source_triage']=triage
  if p['review_stage']=='unreviewed':
   p.update(review_stage='metadata_screened',reviewer='Codex first source gate',run_id='SEQ0002',date=L.DATE,rationale=note)
  for e in evs:
   if e not in p['evidence']:p['evidence'].append(e)
  L.upsert('publication_reviews',p,'Apply first source gate; do not infer relevance from missing sources')
  report.append(dict(registry_key=k,**triage))
 from collections import Counter
 summary=dict(Counter(x['decision'] for x in report))
 out=dict(run_id='SEQ0002',batch_id='B0017',records=report,summary=summary,limitations='Gate dispositions cover25inputs,not25fulltext reviews. No qualifying table found is limited to inspected saved sources. Earlier deep-review and retrieval queues are superseded for these records.',validation=L.validate())
 L.atomic(L.HERE/'sequence_batch_0017_report.json',json.dumps(out,indent=2)+'\n')
 action='SEQ0002 first gate complete for25B0017inputs: '+json.dumps(summary)+'; scientific review andsource completeness separate.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Detailedsource review of qualifying10.1038/nnano.2009.5; Rothemund qualifies but sourcevariant checks remain.','Continue7priority sources fromSEQ0001; no-table B0017records inactive,patents excluded.','Select nextbalanced source-screen chunk; FNANO remainsdeferred.'])
 L.upsert('batches',b,'Save fullB0017source gate without claiming fulltext completion')
 print(json.dumps({'summary':summary,'validation':out['validation']},indent=2))
if __name__=='__main__':main()
