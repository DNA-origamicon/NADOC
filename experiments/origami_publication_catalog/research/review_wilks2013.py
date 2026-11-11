"""Audit a low-keyword author lead using experimental architecture, preserving citation routes."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/nn402642a';rid='author-priority-andrew-turberfield';batch='AUTHOR0016';base=L.ROOT/'assets/research-20261105';before=L.counts()
 me=evidence(base/'wilks2013-main.pdf','https://pure.rug.nl/ws/files/6801056/2013ACSNanoWilks.pdf','Publisher PDF via author institution, repository cover precedes article; printedpp8564–8565 tetrahedron assembly, p8568 DNA Sequences; printedp8561 online date; refs1–62')
 se=evidence(base/'wilks2013-si.pdf','https://pure.rug.nl/ws/files/6801055/2013ACSNanoWilksSupp.pdf','SI FigS11 four-component omission controls, FigS12 polymer-conjugate hybridization andFigS14 ligation/denaturation; characterization and microscopy context')
 ce=evidence(base/'wilks2013-crossref.json','https://api.crossref.org/works/'+key,'Publisher-deposited62 references and published-online2013-10-01; differs from printed PDF online2013-09-16')
 note='Experimental DNA tetrahedron is assembled from four component oligonucleotides s1–s4, not a long scaffold folded by staple strands. Polymer is attached to an internally alkyne-modified uracil replacing s2 baseA12; unmodified and ligated tetrahedra serve as controls. Equimolar s1,s2-poly(NIPAM),s3,s4 undergo isothermal formamide-based assembly. SI FigS11 omission controls require all four strands; FigsS12/S14 characterize conjugate hybridization and ligation. Main DNA Sequences section explicitly assigns s1–s4 as tetrahedron components. Origami is cited as background and for an isothermal assembly method (ref50), not used as the experimental structure. Exclude from origami relevance based on inspected construction and experiments; retain cited origami leads.'
 existing=next((p for p in L.read('publication_reviews') if p['registry_key']==key),None)
 p=existing or dict(registry_key=key,registry_id=None,doi=key,canonical_work_id='work:'+key,canonical_work_status='provisional_unreconciled',version_links=[],legacy_record={},evidence=[])
 for e in [me,se,ce]:
  if e not in p['evidence']:p['evidence'].append(e)
 p.update(title='Giant Surfactants Created by the Fast and Efficient Functionalization of a DNA Tetrahedron with a Temperature-Responsive Polymer',publication_type=['journal_article'],review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='main_and_SI_available',rationale=note,reviewer='Codex primary methods/results and SI experimental-architecture inspection',run_id=rid,date=L.DATE,date_evidence={'date':'2013-10-01','source':ce,'primary_verified':False,'meaning':'Publisher-deposited online date; exact first-online date unresolved against retained publisher PDF printed online2013-09-16','conflicting_primary_source':me,'conflicting_date':'2013-09-16'},temporal_scope='pre2020_verified',unresolved_questions=['Resolve exact first-online date conflict between printed PDF and deposited metadata; both unambiguously pre2020.','Reconcile all62 references and follow relevant origami method/design citations.'])
 L.upsert('publication_reviews',p,'Audit non-origami four-strand tetrahedron and preserve date conflict')
 refs=json.loads((base/'wilks2013-crossref.json').read_text())['message']['reference'];assert len(refs)==62
 for n,r in enumerate(refs,1):
  L.upsert('discovery_edges',dict(edge_id='wilks2013:reference:'+str(n),source_key=key,target_key=r.get('DOI','').lower() or 'citation:wilks2013:'+str(n),relation='cites',citation=r,evidence_url=ce['url'],local_file=ce['local_file'],sha256=ce['sha256'],locator='Reference array index'+str(n-1)+'; total agrees with final reference62 in retained main',reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all deposited references despite article exclusion')
 resolved=[]
 for e in L.read('discovery_edges'):
  if e['edge_id'].startswith(rid+':') and 'surfactants' in e.get('citation','').lower():
   assert any(key in u for u in e['source_links'])
   e.update(target_key=key,reconciliation_state='primary_identity_and_non_origami_architecture_verified; exact_online_date_conflict_open');L.upsert('discovery_edges',e,'Reconcile three repeated author occurrences to one primary record');resolved.append(e['edge_id'])
 assert len(resolved)==3
 ip=L.HERE/'turberfield_bibliography_inventory.json';inv=json.loads(ip.read_text())
 for field in ['all_entries','selected']:
  for row in inv[field]:
   if key in row.get('doi_links',[]):row.update(target_key=key,identity_status='primary_identity_verified',review_status='not_origami_four_strand_tetrahedron; date_conflict_open')
 inv.setdefault('review_reconciliations',{})[key]=dict(occurrences=3,source_evidence=[me,se],decision='not_origami',original_enumeration_audit_unchanged=True)
 L.atomic(ip,json.dumps(inv,indent=2)+'\n')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Low-keyword Oxford author bibliography record; three repeated occurrences reconciled',before_counts=before,after_counts=L.counts(),completed_actions=['Acquired main and SI from public institutional repository without intervention.','Excluded after inspecting four-strand construction, polymer conjugation and omission/ligation controls.','Reconciled three bibliography occurrences; retained62 references and explicit online-date conflict.'],exclusion_audit={'denominator':1,'meaning':'One new non-origami exclusion audited using main experimental methods and SI controls','sample':[{'key':key,'reason':note,'evidence':[me,se]}]},validation=[L.validate()],unresolved_keys=[key],next_queue=['Follow cited origami method ref50 and parent tetrahedron ref30 as separate leads; reconcile dates.','Continue named-author histories, citation routes and low-keyword backlog; FNANO deferred.']), 'Save audited exclusion and discovery followup')
 print(L.validate());print(L.counts())
if __name__=='__main__':main()
