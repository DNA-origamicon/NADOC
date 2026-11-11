"""Review original main and retained SI; index sequences without reconstruction."""
import hashlib,json,re,subprocess,zipfile
from pathlib import PurePosixPath
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/ja8030196';batch='AUTHOR0017';rid='author-priority-friedrich-simmel';base=L.ROOT/'assets/research-20261105';before=L.counts();archive=base/'shih-source-75.zip';url=json.loads((base/'acquisition.json').read_text())[archive.name]['url'];members=[]
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None and sum(i.file_size for i in z.infolist())<500*1024**2
  for i in z.infolist():
   if i.is_dir() or i.filename.startswith('__MACOSX/') or PurePosixPath(i.filename).name.startswith('._'):continue
   assert PurePosixPath(i.filename).suffix=='.pdf';data=z.read(i.filename);assert data.startswith(b'%PDF-')
   p=base/'shih-extracted/75'/PurePosixPath(i.filename).name;p.parent.mkdir(parents=True,exist_ok=True)
   if p.exists():assert p.read_bytes()==data
   else:p.write_bytes(data)
   members.append(dict(member=i.filename,local_file=str(p.relative_to(L.ROOT)),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
 L.atomic(L.HERE/'shih75_archive_inventory.json',json.dumps(members,indent=2)+'\n')
 mainpdf=base/'shih-extracted/75/JungmannR_jacs_2010.pdf';si=L.ROOT/'assets/sources/acs-expansion-20261104/4621621-ja8030196_si_001.pdf'
 assert hashlib.sha256(si.read_bytes()).hexdigest()==next(x['sha256'] for x in members if '_SI.pdf' in x['member'])
 me=evidence(mainpdf,url,'Author ZIP misleading2010filename; mainp10062 Published on Web07/10/2008, Figs1–3/results; refs12/13 revised6HB; all16 referencesp10063')
 se=evidence(si,'https://ndownloader.figshare.com/files/4621621','SI S1–S3 methods, FigS1 PDF/printedS4 visually inspected, AppendixA S9–S11 full scaffold, AppendixB S12–S15 staple rows; matches author ZIP SI SHA')
 ce=evidence(base/'jungmann2008-crossref.json','https://api.crossref.org/works/'+key,'All16 deposited reference entries; agrees with final mainreference16')
 s=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode();a,b=s.split('Appendix A (sequence of 7560)',1)[1].split('Appendix B (Staple Sequences for Six-helix bundles)')
 scaffold=''.join(l.strip() for l in a.splitlines() if re.fullmatch('[ACGT]+',l.strip()));staples=[l.strip() for l in b.splitlines() if re.fullmatch('[ACGT]+',l.strip())]
 assert len(scaffold)==7560 and len(staples)==186
 rows=[];ordinal=0
 for page,text in enumerate(s.split('\f'),1):
  if page>=12:
   for line in text.splitlines():
    if re.fullmatch('[ACGT]+',line.strip()):ordinal+=1;rows.append(dict(ordinal=ordinal,pdf_page=page,printed_page='S'+str(page),sequence=line.strip(),length=len(line.strip())))
 assert [r['sequence'] for r in rows]==staples
 L.atomic(L.HERE/'jungmann2008_sequence_index.json',json.dumps(dict(evidence=se,scaffold_bases=len(scaffold),scaffold_sequence=scaffold,staple_entries=len(staples),length_histogram=dict(Counter(map(len,staples))),staples=rows,limitations='Text extraction uses splitlines to include form-feed page-start sequences; counts match stated values. No sequence-to-route or full synthesis-set certification.'),indent=2)+'\n')
 note='Main and SI confirm revised410nm6HB using p7560 scaffold and186 staples, with28 repetitive42base units between end pieces. SI explicitly describes six helices in hexameric arrangement; FigS1 visually shows six-cylinder ring cross-section and repeated/end routing schematic. AppendixA S9–S11 yields7560bases, AppendixB S12–S15 yields186 sequence entries (174x42nt,4x27,4x31,2x24,2x34). S1 incorrectly points staples toAppendixA and insert sequence toAppendixC; actual full scaffold isAppendixA and staplesAppendixB, with noAppendixC heading. Rectangle is explicitly identical to Rothemund2006 and usesM13mp18 plus226 short strands; rectangle sequences are not listed anew. Main references12Douglas2007 and13Mathieu2005 as6HB predecessors; exact variant differences not yet reconciled. Isothermal folding lowers formamide concentration by dialysis; urea also tested. Temperature-based controls do not define new geometries. Author ZIP filenames say2010 but main title/DOI and published-web2008-07-10 verify identity; ZIP SI is byte-identical to retained ACS file.'
 questions=['Verify sequence-to-route assignment and original native design if available; count agreement alone is not full source certification.','Reconcile revised6HB against Douglas2007 and Mathieu2005 parent variants; source genotype p7560 and sequence orientation must remain explicit.','Retrieve and verify exact226-strand Rothemund rectangle source set; preserve explicit reuse attribution.','Follow all backward/forward citations and enumerate Simmel history independently.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [me,se,ce]:
  if e not in p['evidence']:p['evidence'].append(e)
 p.update(access='main_and_SI_available',rationale=note,reviewer='Codex main/SI, FigS1 visual and full sequence-entry inspection',run_id=rid,date=L.DATE,date_evidence={'date':'2008-07-10','source':me,'primary_verified':True,'meaning':'Published on Web at top of mainp10062; filenames2010 not dates'},temporal_scope='pre2020_verified',unresolved_questions=questions)
 L.upsert('publication_reviews',p,'Deepen existing source review; verify complete table counts and main identity')
 did='RDE0051';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or key in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=['Revised410nm6HB p7560','Reused Rothemund2006 rectangle M13mp18'],identity_status='One revised bundle and one explicitly reused rectangle; exact parent/source mapping pending',lattice_decision='SI explicit hexameric6HB arrangement and FigS1 ring cross-section support conventional bundled architecture; rectangle attributed to Rothemund; complete source verification pending',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[{'relation':'reuses_design_from','target':'10.1038/nature04586','scope':'Rectangle explicitly identical SI S1'}],variant_links=[],source_completeness='not_verified',evidence=[me,se],source_files=[me,se],outstanding_checks=questions,review_stage='source_reviewed',review_run=batch,run_id=rid,date=L.DATE,legacy_record={}), 'Record two design units with explicit source differences')
 refs=json.loads((base/'jungmann2008-crossref.json').read_text())['message']['reference'];assert len(refs)==16
 for n,r in enumerate(refs,1):
  L.upsert('discovery_edges',dict(edge_id='jungmann2008:reference:'+str(n),source_key=key,target_key=r.get('DOI','').lower() or 'citation:jungmann2008:'+str(n),relation='cites',citation=r,evidence_url=ce['url'],local_file=ce['local_file'],sha256=ce['sha256'],locator='Reference array index'+str(n-1),reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all16 references')
 L.upsert('discovery_edges',dict(edge_id='jungmann2008:rectangle-reuse',source_key=key,target_key='10.1038/nature04586',relation='reuses_design_from',evidence_url=se['url'],local_file=se['local_file'],sha256=se['sha256'],locator='SI S1 and sole reference1 S3',reconciliation_state='explicit_reuse_attribution; exact_source_set_pending',run_id=rid,date=L.DATE),'Preserve primary rectangle reuse attribution')
 edge=next(e for e in L.read('discovery_edges') if e['edge_id']=='author-priority-william-shih:lab:75');edge.update(reconciliation_state='primary_identity_date_and_source_counts_reviewed; full_source_certification_pending');L.upsert('discovery_edges',edge,'Resolve author ZIP identity despite filename year')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Backward citation from low-keyword paper and author-linked Shih ZIP',before_counts=before,after_counts=L.counts(),completed_actions=['Recovered primary main, verified2008webdate despite2010filenames and SI byte identity.','Visually reviewed6HB cross-section/routing and indexed7560scaffold bases/186staple entries with page locators.','Preserved revised6HB versus explicit rectangle reuse and16 references.'],validation=[L.validate()],unresolved_keys=[key],next_queue=questions+['Continue remaining named authors and low-keyword rotation; FNANO deferred.']), 'Save targeted deeper source review and followup queue')
 print(L.validate())
if __name__=='__main__':main()
