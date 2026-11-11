"""Qualifying multi-bundle source review; omit-strand controls remain variants."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/ncomms4691';run='SEQ0001-followup';a=L.ROOT/'assets/sources';xml=a/'PMC3997801.xml';si=a/'pre2020-expansion/supplements/PMC3997801-41467_2014_BFncomms4691_MOESM86_ESM.pdf'
 em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3997801/fullTextXML','Targeted pseudo-defect architecture paragraphs,probe discussion,refining self-assembly section,andmolecularself-assembly Methods inspected; not complete article review.')
 es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fncomms4691/MediaObjects/41467_2014_BFncomms4691_MOESM86_ESM.pdf','Figure2/3 routing captions;Tables1,3,5,7,9,11captions andsequence/length rows inPDF38-42,45-49,52-56,59-63,66-70,73-77;Table12PDF78omissions. Sourceimages andallbase/variantmapping not independentlyaudited.')
 pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
 ranges={1:(38,42),3:(45,49),5:(52,56),7:(59,63),9:(66,70),11:(73,77)};tables={}
 for n,(start,end) in ranges.items():
  rows=[]
  for i in range(start,end+1):
   for m in re.finditer(r'(?m)^\s*(Cy5-)?([ACGT]+)\s+(\d+)\s*$',pages[i-1]):rows.append(dict(sequence=m[2],printed_length=int(m[3]),modification='Cy5' if m[1] else None,pdf_page=i))
  assert len(rows)>=100
  tables[n]=dict(rows=rows,length_mismatches=[r for r in rows if len(r['sequence'])!=r['printed_length']],limitations='Onlysame-line sequence/length pairs; labels withlengthonotherlines omitted. No complete synthesis-set claim.')
 overlap=len(set(r['sequence'] for r in tables[9]['rows']) & set(r['sequence'] for r in tables[11]['rows']))
 L.atomic(L.HERE/'quality2014_sequence_index.json',json.dumps(dict(evidence=es,tables=tables,table9_table11_sequence_overlap=overlap,limitations='Table11caption names42HBinternaldefects; extractedoverlap withTable9 requiresoriginalimage/sourceverification. Preservewithoutrepair. Omission tables notfullymapped.'),indent=2)+'\n')
 note='Primarypaper experimentally tests6/8/10/12/42helix bundles withp7560scaffold andcaDNAno0.2. Pseudo-defects created byomittingselectedstaples; Cy5objectlabel andCy3deBruijn defectprobes aredistinct. 42HBhasTTanti-stackingtails andreported207staples;8HBreported184. Two42HBvariants differ inbestisothermal foldingtemperature48/52C; thermalprotocols are notnewcoregeometries. OddnumberedSItables containbasepools,evennumberedtables omissions. Table11caption says42HBinternaldefects butextractedlist overlapsTable9(12HB), requiringaudit; noimputedcorrection.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',rationale=note,reviewer='Codex targetedbundle/sourcepool review',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=['Verifysequence/length rows andmissingseparatelinelabels againstoriginaltableimages.','ResolveTable11caption/listoverlap withTable9 beforeassigninginternaldefectrecipe.','Mapomittedstrands andCy5replacements toeachcore;comparepublishedparents beforeclaiminguniqueness.','Auditcrosssections/lattice,nativefiles andscaffoldcoverage; no complete-source certification.'])
 for e in [em,es]:
  if e not in p['evidence']:p['evidence'].append(e)
 root=E.parse(xml).getroot();ep=root.find('.//article-meta/pub-date[@pub-type="epub"]')
 if ep is not None and ep.findtext('day'):
  p['date_evidence']=dict(date=ep.findtext('year')+'-'+ep.findtext('month').zfill(2)+'-'+ep.findtext('day').zfill(2),primary_verified=True,source=em,meaning='PrimaryXMLepub')
 L.upsert('publication_reviews',p,'Reviewqualifyingbundlepools andpreservesourceambiguity')
 d=next(x for x in L.read('design_evidence') if x['design_id']=='D020')
 for f in ['evidence','source_files']:
  for e in [em,es]:
   if e not in d[f]:d[f].append(e)
 if note not in d['core_variant_composition']:d['core_variant_composition']+=' '+note
 for q in p['unresolved_questions']:
  if q not in d['outstanding_checks']:d['outstanding_checks'].append(q)
 d.update(review_stage='source_reviewed',review_run=run,source_completeness='not_verified');L.upsert('design_evidence',d,'Enrichstable42HB recordwithoutcountingomissions asnewcores')
 for did,h,t in [('RDE0076',6,3),('RDE0077',8,5),('RDE0078',10,7),('RDE0079',12,9)]:
  old=next((x for x in L.read('design_evidence') if x['design_id']==did),None);assert old is None or old['publication_keys']==[k]
  d=dict(design_id=did,publication_keys=[k],named_objects=[f'{h}-helix bundle', 'Staple-omission pseudo-defect variants'],identity_status='Distinctreportedarchitecture;priorparent/coreidentityunreconciled',core_variant_composition=f'Experimentallyreported{h}HB,p7560scaffold;SI Table{t}basepool andTable{t+1}omissionvariants. Cy5objectlabel separatefromdeBruijn defectprobe. '+note,lattice_decision='Multihelixbundleexplicit;crosssection/narroweligibility notyetindependentlyaudited.',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='unresolved',review_stage='source_reviewed',review_run=run,run_id=run,date=L.DATE,legacy_record={},relationships=[],variant_links=[],outstanding_checks=p['unresolved_questions'])
  L.upsert('design_evidence',d,'Recordreportedbundlearchitecture withqualifyingsequencepool')
 refs=root.findall('.//ref-list/ref')
 for r in refs:
  n=r.get('id');doi=r.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='QUALITY2014:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:quality2014:'+n,relation='cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retainentirequalifyingpaperbibliography')
 print(json.dumps(dict(table_counts={n:len(t['rows']) for n,t in tables.items()},overlap=overlap,references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
