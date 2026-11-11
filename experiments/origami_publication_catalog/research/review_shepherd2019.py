"""Primary review of two wireframe variants; index retained workbook cells, no reconstruction."""
import json,re,zipfile,xml.etree.ElementTree as E
from collections import Counter
import ledger as L
from review_batch_0001 import evidence
N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
X='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
def workbook(path):
 with zipfile.ZipFile(path) as z:
  assert z.testzip() is None
  ss=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',N)]
  rel={x.get('Id'):x.get('Target') for x in E.fromstring(z.read('xl/_rels/workbook.xml.rels'))};out=[]
  for sh in E.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',N):
   cells=[]
   for c in E.fromstring(z.read('xl/'+rel[sh.get(X)])).findall('.//s:row/s:c',N):
    v=c.find('s:v',N)
    if v is not None:
     val=ss[int(v.text)] if c.get('t')=='s' else v.text
     bare=re.sub(r'/[^/]+/','',val);seq=bool(re.fullmatch('[ACGTacgt]+',bare))
     cells.append(dict(cell=c.get('r'),value=val,sequence_candidate=seq,base_count=len(bare) if seq else None))
   out.append(dict(sheet=sh.get('name'),cells=cells,sequence_candidate_cells=sum(c['sequence_candidate'] for c in cells)))
 return out

def main():
 key='10.1038/s41598-019-42665-1';rid='author-priority-mark-bathe';batch='AUTHOR0012';base=L.ROOT/'assets/research-20261105'
 before=next(b for b in L.read('batches') if b['batch_id']==batch)['before_counts'];manifest=json.loads((base/'acquisition.json').read_text())
 xml=L.ROOT/'assets/sources/pre2020-expansion/PMC6467869.xml';root=E.parse(xml).getroot()
 me=evidence(xml,'https://pmc.ncbi.nlm.nih.gov/articles/PMC6467869/','Results Sec2/Fig4; DNA origami assembly Sec7; publication date and refs1–56')
 pe=evidence(base/'shepherd2019-publisher.html','https://www.nature.com/articles/'+key.split('/',1)[1],'Publisher article and two Supplementary Information links; published16 April2019')
 se=evidence(base/'shepherd2019-si.pdf',manifest['shepherd2019-si.pdf']['url'],'PDF/printedpp8–10: gels FigS7, TEM FigS8 visually inspected p9, external table descriptions p10')
 we=evidence(base/'shepherd2019-si.xlsx',manifest['shepherd2019-si.xlsx']['url'],'Four sheets; TableS1 B1/B2 scaffold sequences; S3 A1:B44 and S4 A1:B74 named staple entries')
 rows=workbook(base/'shepherd2019-si.xlsx');assert [r['sequence_candidate_cells'] for r in rows]==[7,23,44,74]
 assert [next(c['base_count'] for c in rows[0]['cells'] if c['cell']==x) for x in ['B1','B2']]==[1676,2520]
 L.atomic(L.HERE/'shepherd2019_sequence_index.json',json.dumps(dict(evidence=we,sheets=rows,limitations='Cell index and author-labeled staple table counts; no sequence-to-route verification or molecular reconstruction.'),indent=2)+'\n')
 note='Two DAEDALUS-designed wireframe pentagonal bipyramids experimentally folded with custom bacterial circular scaffolds:52-bp edges using phPB52 and84-bp edges using phPB84. Main Results reports1580-nt design scaffold length versus1676-nt phPB52 genome; phPB84 design and genome both2520nt. Workbook S1 B1/B2 independently contains1676/2520 DNA bases. S3 has44 named staple entries and S4 has74; SI p10 explicitly assigns these tables to the respective objects. Methods Sec7 uses20nM scaffold,20-fold staples,TAE12mM MgCl2 and13-hour95–24C annealing; gels and TEM validate experimental folding. SI FigS8 visually inspected p9. Wireframe architecture is explicitly stated in main Results; both variants excluded from the narrower filled-lattice catalog while retained as design-bearing literature. Native routing not present among the two acquired supplements; table availability is not certified sequence-to-route completeness.'
 unresolved=['Resolve1580nt designed length versus1676nt phPB52 scaffold and the treatment of excess bases against routing evidence.','Acquire original DAEDALUS routing/output or explicit per-base mapping if publicly available; verify exact relationship to2016 DAEDALUS templates.','Reconcile all backward references and forward citations; mainref23 has malformed DOI10.1021/acsnano.1028b08671, probable intended8b08671 remains a candidate correction.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [me,pe,se,we]:
  if e not in p['evidence']:p['evidence'].append(e)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='excluded',access='main_and_both_supplements_available',rationale=note,reviewer='Codex primary methods/results and supplement inspection',run_id=rid,date=L.DATE,date_evidence={'date':'2019-04-16','source':pe,'primary_verified':True,'meaning':'Publisher published date, corroborated in retained XML'},temporal_scope='pre2020_verified',unresolved_questions=unresolved)
 L.upsert('publication_reviews',p,'Review two custom-scaffold wireframe variants without expanding catalog scope')
 did='RDE0048';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or key in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=['phPB52 pentagonal bipyramid52-bp edges','phPB84 pentagonal bipyramid84-bp edges'],identity_status='Two size/scaffold variants documented together; relationship to prior DAEDALUS templates pending',lattice_decision='Explicit wireframe architecture in primary Results, supported by Fig4 and SI FigS8; excluded under unchanged catalog rules',catalog_eligibility='excluded',core_variant_composition=note,relationships=[{'relation':'uses_design_method','target':'10.1126/science.aaf4388','scope':'Mainref19 DAEDALUS; exact prior geometry/reuse relationship not established'}],variant_links=[],source_completeness='not_verified',evidence=[me,pe,se,we],source_files=[se,we],outstanding_checks=unresolved,review_stage='source_reviewed',review_run=batch,run_id=rid,date=L.DATE,legacy_record={}), 'Retain literature-relevant excluded wireframe family and two variant source tables')
 refs=list(root.iter('ref'));assert len(refs)==56
 for n,r in enumerate(refs,1):
  ds=[e.get('{http://www.w3.org/1999/xlink}href') for e in r.iter('ext-link') if e.get('ext-link-type')=='doi'];citation=' '.join(r.itertext());doi=ds[0].lower() if ds else None
  L.upsert('discovery_edges',dict(edge_id='shepherd2019:reference:'+str(n),source_key=key,target_key=doi or 'citation:shepherd2019:'+str(n),relation='cites',evidence_url=me['url'],local_file=me['local_file'],sha256=me['sha256'],locator='XML '+r.get('id'),citation=citation,reconciliation_state='malformed_doi_pending_verification' if n==23 else 'pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all56 main references without relevance filtering or silent DOI repair')
 for e in L.read('discovery_edges'):
  if e['edge_id'].startswith(rid+':') and (e['target_key']==key or 'Bioproduction of pure' in e.get('citation','')):
   e.update(target_key=key,reconciliation_state='primary_identity_and_two_wireframe_variants_reviewed; source_completeness_pending');L.upsert('discovery_edges',e,'Reconcile author-history occurrence to inspected primary article')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Bathe primary source review of custom ssDNA production demonstrations',before_counts=before,after_counts=L.counts(),completed_actions=['Acquired publisher page, PDF SI and XLSX directly without intervention.','Inspected main methods/results and SI; indexed all four workbook sheets; retained two wireframe variants.','Retained56 backward references and malformed ref23 DOI explicitly.'],unresolved_keys=[key],exclusion_audit={'denominator':1,'meaning':'One new narrow-catalog exclusion; remains relevant in literature census','sample':[{'key':key,'reason':'Both demonstrated origami objects explicitly wireframe','evidence':[me,se,we]}]},validation=[L.validate()],next_queue=unresolved+['Continue named-author histories, low-keyword backlog and pending Shih/Qian sources; FNANO deferred.']), 'Save primary review, audit and next queue')
 print(L.validate());print(L.counts())
if __name__=='__main__':main()
