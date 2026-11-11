"""Link explicit tall-rectangle reuse to existing design ID, retaining date conflict."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acsnano.6b05938';parent='10.1038/nature04586';rid='author-priority-thomas-labean';batch='AUTHOR0032';before=L.counts();base=L.ROOT/'assets/research-20261105'
 ev=evidence(base/'precise-coating-main.pdf','https://phyweb.physics.nus.edu.sg/~bcf/publications/nano2E6b05938_2016.pdf','Main PDF1–9 text read; PDF6 Fig6/7 visually inspected. Template PDF5/7/8 (journal148/150/151); parent ref31 PDF9; PDF1 printed publication date2016-12-01.')
 ce=evidence(base/'precise-coating-crossref.json','https://api.crossref.org/works/'+key,'35 deposited references; ref31 DOI10.1038/nature04586; online date2016-12-12 differs from PDF publication label.')
 qs=['Reconcile parent tall-rectangle source variants and exact staple inventory with S007; explicit reuse identity does not certify complete experimental synthesis set.','Resolve PDF2016-12-01 publication label versus publisher/Crossref2016-12-12 online date; both pre2020, issue2017-01-24.','Retain movies as acquired but not directly reviewed; main PDF5/8 identifies them as T4-DNA fluorescence, not new origami designs.','Resume author-history and backlog rotation; compare diblock-paper rectangle only after its main/source identity is available.']
 note='Main PDF5 identifies the experimental origami as Rothemund tall rectangle; Materials PDF7 points to ref31 for precise staple sequences and scaffold/staple layout, and Methods PDF8 explicitly uses M13mp18 7249nt,5nM scaffold and50nM staples. Ref31 PDF9 is Rothemund2006, DOI verified in deposited bibliography. Protein coatings C8-BSso7d/C4-BK12 and concentration series are experimental conditions, not reported new routing. Main Fig6/7 PDF6 visually inspected: origami mobility/AFM measurements; no unsupported inference of molecular routing from AFM. Main PDF5/8 identifies supporting movies as T4-DNA fluorescence; rawM13, plasmids and linearDNA controls are not distinct origami designs. Exact parent variant/source completeness remains unverified.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 p.update(design_contributions=['reused_design'],rationale=note,access='main_and_all_four_SI_files_available; main_and_SI_PDF_reviewed; movies_not_directly_reviewed',reviewer='Codex main/SI text and Fig6/7 visual review',run_id=rid,date=L.DATE,unresolved_questions=qs,temporal_scope='pre2020_verified; exact_first_online_date_conflict')
 p['date_evidence'].update(date='2016-12-12',primary_verified=False,source=ce,pdf_publication_label='2016-12-01',pdf_date_evidence=ev,meaning='Exact first-online date unresolved across primary PDF label and deposited/current publisher history; both2016.')
 for e in [ev,ce]:
  if e not in p['evidence']:p['evidence'].append(e)
 L.upsert('publication_reviews',p,'Verify explicit parent reuse and preserve divergent primary/deposited date labels')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='S007')
 if key not in d['publication_keys']:d['publication_keys'].append(key)
 rel=dict(relation='reused_design',publication_key=key,parent_publication_key=parent,evidence=ev,scope='Explicit tall rectangle reuse; exact sequence-level variant comparison pending.')
 if rel not in d['relationships']:d['relationships'].append(rel)
 if ev not in d['evidence']:d['evidence'].append(ev)
 d['outstanding_checks']=list(dict.fromkeys(d['outstanding_checks']+qs))
 L.upsert('design_evidence',d,'Attach verified reuse claim to existing tall rectangle ID; do not create duplicate geometry or certify legacy source set')
 refs=json.loads((base/'precise-coating-crossref.json').read_text())['message']['reference'];assert len(refs)==35
 for i,r in enumerate(refs,1):
  L.upsert('discovery_edges',dict(edge_id='precise-coating:journal-reference:'+str(i),source_key=key,target_key=r.get('DOI','').lower() or 'citation:precise-coating:'+str(i),relation='cites',citation=r,evidence_url=ce['url'],local_file=ce['local_file'],sha256=ce['sha256'],locator='Deposited reference'+str(i),reconciliation_state='parent_identity_verified; exact_variant_pending' if i==31 else 'pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain complete deposited bibliography and resolved parent identity')
 L.upsert('discovery_edges',dict(edge_id='precise-coating:reuse-tall-rectangle',source_key=key,target_key=parent,relation='reused_design',design_id='S007',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Main PDF5/7/8 and ref31 PDF9',reconciliation_state='explicit_reuse_identity_verified; sequence_variant_comparison_pending',run_id=rid,date=L.DATE),'Retain explicit source-based reuse relationship')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Complete recovered main review and parent reconciliation',before_counts=before,after_counts=L.counts(),completed_actions=['Read main, inspected AFM/EMSA figures, verified named tall rectangle and7249ntM13 scaffold.','Attached reuse evidence to stable S007 without counting protein coating conditions as new geometry.','Retained35references and exact date-label conflict.','No new catalog eligibility/source-completeness certification.'],validation=[L.validate()],unresolved_keys=[key],next_queue=qs),'Save explicit reuse evidence and remaining source/date checks')
 print(L.validate())
if __name__=='__main__':main()
