"""Inspect peptide-linked origami variants without reconstructing molecular structures."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acsnano.9b04251';batch='AUTHOR0015';rid='author-priority-andrew-turberfield';base=L.ROOT/'assets/research-20261105';xml=L.ROOT/'assets/sources/PMC6764022.xml';pdf=L.ROOT/'assets/sources/acs-expansion-20261104/17012882-nn9b04251_si_001.pdf'
 before=next(b['before_counts'] for b in L.read('batches') if b['batch_id']==batch);r=E.parse(xml).getroot()
 me=evidence(xml,'https://pmc.ncbi.nlm.nih.gov/articles/PMC6764022/','Results section Two Distinct DNA Nanostructures; Fig2; handle/tag discussion; publication date; refs1–50')
 se=evidence(pdf,'https://ndownloader.figshare.com/files/17012882','SI scaffold/folding methods pp4–5; FigsS9/S10 PDF/printedpp21–23 visually inspected; TableS6-1 pp41–42 andS6-2 pp43–44; supporting refs p45')
 ce=evidence(base/'peptide2019-crossref.json','https://api.crossref.org/works/'+key,'Publisher-deposited published-online2019-08-05 and published-print2019-09-24; agrees with primary XML date')
 s=subprocess.check_output(['pdftotext','-layout',str(pdf),'-']).decode();index=[]
 for label,expected,midmax in [('A',69,59),('B',67,57)]:
  matches=re.findall(r'^\s*('+label+r' (?:MID-\d+\*?|LEFT-\d+(?: handle| ctrl)?|RIG-\d+))\s+([ACGT]+)\s*$',s,re.M)
  rows=[dict(name=n,sequence=q,base_count=len(q),role='replacement_control' if ' ctrl' in n else 'base_staple',fluorophore=('5prime Cy3' if label=='A' else '5prime Cy5') if '*' in n else None) for n,q in matches]
  assert len(rows)==expected+3 and len({x['name'] for x in rows})==len(rows)
  assert [int(re.search(r'MID-(\d+)',x['name'])[1]) for x in rows if 'MID' in x['name']]==list(range(1,midmax+1))
  index.append(dict(object=label,base_staple_entries=expected,replacement_entries=3,rows=rows))
 tags=[dict(name='tag '+n,sequence=q,role='separate_tag_not_base_staple') for n,q in re.findall(r'^\s*tag ([αβ](?: ctrl)?)\s+([ACGT]+)\s*$',s,re.M)];assert len(tags)==4
 composition={str(n):{'active_handle_helices':{0:[],1:[2],2:[0,2],3:[0,2,4]}[n],'control_replacement_helices':{0:[0,2,4],1:[0,4],2:[4],3:[]}[n]} for n in range(4)}
 L.atomic(L.HERE/'peptide2019_sequence_index.json',json.dumps(dict(evidence=se,objects=index,tags=tags,valency_composition_for_each_object=composition,limitations='PDF-extracted rows with printed IDs and fluorophore annotations; author-reported base counts agree. Not a certified synthesis set or sequence-to-route validation. Tag and peptide chemistry remain separate components; no molecular authoring.'),indent=2)+'\n')
 note='Two new asymmetric origami identifiers A/B each have a6HB core with one/two concentric sleeves, folded from2686nt pUC19-derived ssDNA. Main reports69/67 base staples, reconciled to SI tables: A59MID+6LEFT+4RIG; B57MID+6LEFT+4RIG. Each table additionally lists3LEFT control replacements and2separate tags. SI FigsS9 pp21–22 show blue scaffold and staple routes, helix labels0–23, and7base coordinate ticks; core helices0–5 extend outside sleeve regions. This supports a conventional bundled architecture, but native lattice coordinates and per-base map remain unverified. Handles atLEFT0/2/4 are23nt extensions. FigS10 p23 shows valency3 uses all handles;2 uses0/2;1 uses2;0 usesnone, with controls replacing the other positions. Tags carryT8 spacers; end staples generallyT4, except A right helix2 hasT6. A MID37 has5primeCy3; B MID41 has5primeCy5. These labels, tags, controls and peptide conjugates are distinct from core geometry. SI methods prepare ss pUC19 using Nt.BspQI/ExoIII; folding60nM scaffold with5fold staples inTE16mM MgCl2. Main assembly experiments measure peptide-mediated homo/heterodimerization and polyvalency, not new core geometries per valency.'
 unresolved=['Verify native caDNAno routing/cross-section and exact scaffold sequence/orientation; no native file in retained single PDF supplement.','Verify every base/replacement/tag sequence against route and complete peptide/tag chemistry before source-completeness certification.','Reconcile geometry/parent identity against prior6HB/sleeve designs and follow all backward/forward citations; method citations alone do not establish exact design reuse.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [me,se,ce]:
  if e not in p['evidence']:p['evidence'].append(e)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',access='main_and_SI_available_native_routing_unverified',rationale=note,reviewer='Codex primary results/methods, visual routing/handle diagrams and sequence-table inspection',run_id=rid,date=L.DATE,date_evidence={'date':'2019-08-05','source':me,'corroboration':ce,'primary_verified':True,'meaning':'Primary XML publication date corroborated by publisher-deposited online date; print2019-09-24; legacy2019-08-08 superseded'},temporal_scope='pre2020_verified',unresolved_questions=unresolved)
 L.upsert('publication_reviews',p,'Record two cores, functional variants and corroborated online date')
 did='RDE0050';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or key in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=['Origami A one-sleeve6HB','Origami B two-sleeve6HB','A0–A3 and B0–B3 handle/peptide valency variants'],identity_status='Two core geometries with eight documented valency variants; parent identity unresolved',lattice_decision='Bundled6HB/concentric sleeves and7base routing grid support conventional honeycomb interpretation; exact native cross-section not verified',catalog_eligibility='unresolved',core_variant_composition=note,variant_composition=composition,relationships=[],variant_links=[],source_completeness='not_verified',evidence=[me,se],source_files=[se],outstanding_checks=unresolved,review_stage='source_reviewed',review_run=batch,run_id=rid,date=L.DATE,legacy_record={}), 'Record two cores separately from valency/replacement/tag components')
 refs=list(r.iter('ref'));assert len(refs)==50
 for n,ref in enumerate(refs,1):
  ds=[x.get('{http://www.w3.org/1999/xlink}href') for x in ref.iter('ext-link') if x.get('ext-link-type')=='doi'];target=ds[0].lower() if ds else 'citation:peptide2019:'+str(n)
  L.upsert('discovery_edges',dict(edge_id='peptide2019:reference:'+str(n),source_key=key,target_key=target,relation='cites',citation=' '.join(ref.itertext()),evidence_url=me['url'],local_file=me['local_file'],sha256=me['sha256'],locator='XML '+ref.get('id'),reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all50 primary references')
 part=s.rsplit('Supporting References',1)[1];ms=list(re.finditer(r'^\s*(\d+)\.\s+',part,re.M));assert [int(m[1]) for m in ms]==list(range(1,6))
 for i,m in enumerate(ms):
  cit=' '.join(part[m.end():ms[i+1].start() if i+1<len(ms) else len(part)].split());cit=re.sub(r'\s+45$','',cit)
  L.upsert('discovery_edges',dict(edge_id='peptide2019:SIreference:'+m[1],source_key=key,target_key='citation:peptide2019:SI:'+m[1],relation='cites',citation=cit,evidence_url=se['url'],local_file=se['local_file'],sha256=se['sha256'],locator='SI supporting reference'+m[1]+' p45',reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all five SI references')
 for edge in L.read('discovery_edges'):
  if edge['edge_id'].startswith(rid+':') and edge['target_key']==key:
   edge.update(reconciliation_state='primary_identity_date_and_designs_reviewed; source_completeness_pending');L.upsert('discovery_edges',edge,'Reconcile author-history occurrence against primary source')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Downloaded ACS supplement and retained primary XML from Turberfield history',before_counts=before,after_counts=L.counts(),completed_actions=['Inspected two routed designs and eight handle-valency diagrams; indexed69/67 base staples plus3 controls/object and2 tags/object.','Corroborated online2019-08-05 date with publisher Crossref; preserved legacy revision history.','Retained50 main and5 SI references.'],validation=[L.validate()],unresolved_keys=[key],next_queue=unresolved+['Rotate low-keyword Oxford records and remaining named-author histories; retain DAEDALUS/TALOS and Shih/Qian queues; FNANO deferred.']), 'Save diagram/table evidence, source limits and citation queue')
 print(L.validate());print(L.counts())
if __name__=='__main__':main()
