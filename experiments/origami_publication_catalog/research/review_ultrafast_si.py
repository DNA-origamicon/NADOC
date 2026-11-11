"""Record inspected ACS source tables and unresolved cutoff conflict."""
import json,re,subprocess,hashlib
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acs.nanolett.9b04354';rid='author-priority-philip-tinnefeld';batch='AUTHOR0027';before=L.counts();base=L.ROOT/'assets/research-20261105';si=base/'ultrafast-si.pdf'
 meta=json.loads((base/'ultrafast-figshare-11541942.json').read_text());assert meta['resource_doi']==key
 assert hashlib.md5(si.read_bytes()).hexdigest()==meta['files'][0]['computed_md5']
 se=evidence(si,'https://ndownloader.figshare.com/files/20731413','SI section4 PDF13–15; TablesS2 PDF17–21 andS3 PDF21–22 (PDF22 visually inspected); refs24–26. Main text not acquired.')
 fe=evidence(base/'ultrafast-figshare-11541942.json','https://api.figshare.com/v2/articles/11541942','Explicit parent DOI, sole file20731413, size/MD5 verified; repository published2020-01-07, not evidence of2019SI availability.')
 observation=dict(url='https://pubs.acs.org/doi/10.1021/acs.nanolett.9b04354',observed=L.DATE,method='Web search rendered publisher result; local direct acquisition403',banner_date='2019-12-23',article_history_published_online='2020-01-08',issue_date='2020-02-12',limitation='Observer transcription of displayed metadata; not retained publisher HTML or proof that full design was public in2019.')
 L.atomic(L.HERE/'ultrafast_publisher_date_observation.json',json.dumps(observation,indent=2)+'\n')
 oe=evidence(L.HERE/'ultrafast_publisher_date_observation.json',observation['url'],'Observer-transcribed conflicting publisher dates; original HTML unavailable locally, see method/limitation.')
 s=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode();rows=[]
 for page,t in enumerate(s.split('\f'),1):
  if 17<=page<=21:
   for n,seq in re.findall(r'^\s*(P[12][A-H]\d+)\s+([ACGT]+)\s*$',t,re.M):rows.append(dict(name=n,sequence=seq,pdf_page=page,length=len(seq)))
 assert len(rows)==188 and len({r['name'] for r in rows})==188
 names=['P1'+c+str(n) for c in 'ABCDEFGH' for n in range(1,13)]+['P2'+c+str(n) for c in 'ABCDEFG' for n in range(1,13)]+['P2H'+str(n) for n in range(1,9)]
 assert {r['name'] for r in rows}==set(names)
 L.atomic(L.HERE/'ultrafast_sequence_index.json',json.dumps(dict(evidence=se,unmodified_count=188,unmodified=rows,modified_named_rows=22,modified_groups={'biotin':12,'npbind':8,'dye':2},modified_sequence_status='Not transcribed: PDF22 wrapped polyA bases overlap row boundaries; visual inspection confirms row identities but exact base assignment needs source verification.',limitations='210 named table rows do not certify a complete synthesis set. Full p8064 sequence, native routing, strand-to-route assignment and parent variant mapping remain unverified.'),indent=2)+'\n')
 note='SI confirms experimental p8064 DNA origami nanoantenna carrying Cy7 and binding two100nm AuNPs; caDNAno2 design and folding methods inSI13–15. TableS2 has188 uniquely named unmodified staples (P1A1–H12;P2A1–G12,H1–H8). TableS3 has22 named modified rows:12biotin,8npbind,base_dye ATTO542 and hotspot_dye Cy7. PDF22 visually inspected; wrapped polyA text intrudes into following rows, so modified sequences are not certified or silently concatenated. AuNPs coated with3prime-thiolT25; this coating oligo is separate from structure staple tables. References7Ochmann2017 and9Vietz2016 support nanoparticle procedures/zipper geometry; exact reuse versus modification of origami core remains unresolved. Geometry/native routing and lattice not established by these tables. Publisher date conflict and2020SIrepository date mean pre2020 full-source availability is not yet verified.'
 qs=['Resolve publisher2019banner/Crossref versus2020article-history date conflict; determine whether original article/design was public before2020.','Acquire main text via author/repository copies; do not infer it was read from supplement access.','Recover native routing, full scaffold and modified-strand exact sequences; audit overlapping table text against original editable source.','Reconcile exact parent design with Ochmann2017/Vietz2016/Puchkova2015; treatment procedure citations alone do not prove identical origami core.','Continue independent author histories and source rotation; no FNANO saturation claim.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='SI_available; main_pending',rationale=note,reviewer='Codex SI methods/tables and PDF22 visual review',run_id=rid,date=L.DATE,temporal_scope='boundary_date_conflict',unresolved_questions=qs)
 for e in [se,fe,oe]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence'].update(primary_verified=False,conflicting_publisher_history_date='2020-01-08',conflict_evidence=oe,meaning='2019-12-23 deposited/banner date versus2020-01-08 publisher history; first public article/design date unresolved')
 L.upsert('publication_reviews',p,'Confirm design use from SI while preserving cutoff conflict and source limits')
 did='RDE0054';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or key in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=['p8064 Cy7/ATTO542 origami nanoantenna with100nm-AuNP dimer'],identity_status='Experimental origami and named source rows verified; parent geometry and pre2020availability pending',lattice_decision='Unresolved: source tables and interhelical-distance assumption do not establish complete geometry/lattice.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[se],evidence=[se,fe,oe],outstanding_checks=qs,review_stage='source_reviewed',review_run=batch,run_id=rid,date=L.DATE,legacy_record={}), 'Retain inspected source group without native-file or date certification')
 refs=re.findall(r'(?ms)^\s*\[(\d+)\]\s+(.*?)(?=^\s*\[\d+\]\s+|\Z)',s.split('  References',1)[1]);assert [int(n) for n,_ in refs]==list(range(1,13))
 for n,t in refs:
  L.upsert('discovery_edges',dict(edge_id='ultrafast:SI-reference:'+n,source_key=key,target_key='citation:ultrafast:SI:'+n,relation='cites',citation=' '.join(re.sub(r'\n\s*\d+\s*\f',' ',t).split()),evidence_url=se['url'],local_file=se['local_file'],sha256=se['sha256'],locator='SI reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all12SI references')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Low-keyword boundary-year article source review',before_counts=before,after_counts=L.counts(),completed_actions=['Recovered sole ACS SI and verified providerMD5/size.','Confirmed actual origami use; indexed188unmodified rows and22modified row names with wrapped-sequence ambiguity explicit.','Recorded conflicting publisher dates and2020SIrepository date without cutoff certification.','Preserved12SI references and main acquisition gap.'],validation=[L.validate()],unresolved_keys=[key],next_queue=qs),'Save source review and cutoff uncertainty')
 print(L.validate())
if __name__=='__main__':main()
