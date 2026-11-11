"""Targeted source review of gate-passing DNA-PAINT designs and variant tables."""
import json,re,subprocess,hashlib,zipfile,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nmeth.2835';run='SEQ0001-followup';a=L.ROOT/'assets/sources/pre2020-expansion';pfx='PMC4153392-41592_2014_BFnmeth2835_MOESM'
 pdf=a/'supplements'/(pfx+'233_ESM.pdf');xml=a/'PMC4153392.xml';archive=a/'supplements'/(pfx+'234_ESM.zip')
 em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4153392/fullTextXML','Targeted Results origami imaging/ten-color sections; Methods materials,DNAorigami self-assembly,origami imaging,drift correction. Remainingcellular/opticalanalysis not fullyread.')
 es=evidence(pdf,'https://static-content.springer.com/esm/art%3A10.1038%2Fnmeth.2835/MediaObjects/41592_2014_BFnmeth2835_MOESM233_ESM.pdf','SI contents,Figure1PDF2 visuallyinspected;Tables1-5PDF14-34 headings andrepresentative rows/ends;Table8PDF37docking context. Notfullbase-by-base audit. Table5explicitly modifiedstrands only.')
 ez=evidence(archive,'https://static-content.springer.com/esm/art%3A10.1038%2Fnmeth.2835/MediaObjects/41592_2014_BFnmeth2835_MOESM234_ESM.zip','ZIPmember inventory andhashes only; DNA-PAINT Processing exe/dll/config/data paths,not a nativeDNA design archive. Nothing executed.')
 pages=subprocess.check_output(['pdftotext','-layout',str(pdf),'-']).decode().split('\f');rows=[];table=None
 for i in range(13,34):
  t=' '.join(pages[i].split())
  tokens=list(re.finditer(r'Supplementary Table ([1-5])\s*\||(?P<pos>\d+\[\d+\]\d+\[\d+\])\s+(?P<seq>(?:Biotin-)?[ACGT]+)',t))
  for m in tokens:
   if m.group(1):table=int(m.group(1))
   else:rows.append(dict(table=table,position=m.group('pos'),printed_sequence=m.group('seq'),pdf_page=i+1))
 assert all(x['table'] for x in rows)
 from collections import Counter
 counts=dict(Counter(x['table'] for x in rows));assert counts[1]>=100 and counts[2]>=100
 z=zipfile.ZipFile(archive);members=[dict(name=x.filename,bytes=x.file_size,sha256=hashlib.sha256(z.read(x)).hexdigest()) for x in z.infolist() if not x.is_dir()];assert z.testzip() is None
 L.atomic(L.HERE/'paint2014_source_index.json',json.dumps(dict(evidence=[es,ez],rows=rows,table_candidate_row_counts=counts,archive_members=members,limitations='Literal position/firstcontiguoussequence extraction,not complete synthesis lists. Colors,extensions,odd/even digit pooling andmodified-onlyTable5 require reconciliation. Spreadsheet companions remain unparsed.'),indent=2)+'\n')
 notes=[('RDE0074',['p8064 microtubule-like monomer','Connector-mediated homopolymer and docking variants'],'Main reports16x16x75nm tunnel-like monomer,p8064scaffold; opposingfaces carry3primeDNA-PAINT docking strands,bottombiotinanchors. Table1 listsstructure,docking,biotin andconnector categories;FigureS1a colors identify these roles. Monomers gel-purified before48h polymerization with5foldconnector excess. Polymerization is separate assembly,not an ordinarycoreextension.'),('RDE0075',['Single-layer rectangular drift marker','Odd/even digit0-9 pattern variants','Modified-only digit0-3 overlay strands'],'FigureS1b is single-layer driftmarker;M13mp18 scaffold. Table2driftmarker staples;Tables3/4odd/even digit pattern recipes andcore/biotin entries;Table5explicitly lists ONLYmodified strands fordigits0-3. Main uses tenrectangular patterned objects andfourpatterns ononeobject. This sourcefamily groups relatedrectangular variants provisionally,not proof allhaveidenticalcore routing or tennewgeometries. Exactparent/core matching toRothemund18 remains pending.')]
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',access='main_XML_SI_PDF_spreadsheets_andsoftwareZIP_available',rationale=' '.join(n for _,_,n in notes)+' Source gate passes. ScaffoldTables6/7 andshortdockingTable8 mustnotcount asnewstaple sets. ZIPcontainsimagingsoftware,notnative design. Tablepresence doesnotcertifyper-variantcompleteness.',reviewer='Codex targetedmain/SIvariant review',run_id=run,date=L.DATE,unresolved_questions=['Verify table rows,color-coded extensions andspecificcore+replacementrecipes for eachdigit;Table5notstandalone.','Compare rectangular core routing andparentreferences; no canonicalreuse merge yet.','Inspect spreadsheet companions andcomplete SI/scaffold/basecoverage before synthesis-set certification.','Microtubulecrosssection/lattice andwholeobject eligibility requireindependent audit; no narrowcatalogpromotion.'])
 for e in [em,es,ez]:
  if e not in p['evidence']:p['evidence'].append(e)
 root=E.parse(xml).getroot();ep=root.find('.//article-meta/pub-date[@pub-type="epub"]')
 if ep is not None:
  date='-'.join([ep.findtext('year'),ep.findtext('month','01').zfill(2),ep.findtext('day','01').zfill(2)])
  p['date_evidence']=dict(date=date,primary_verified=True,source=em,meaning='Deposited manuscriptXMLepub')
 L.upsert('publication_reviews',p,'Review qualifyingpaintsource without conflating modified lists orsoftware withcomplete designs')
 for did,names,note in notes:
  old=next((x for x in L.read('design_evidence') if x['design_id']==did),None);assert old is None or old['publication_keys']==[k]
  d=dict(design_id=did,publication_keys=[k],named_objects=names,identity_status='Provisional sourcefamily;exactvariant/core reconciliation pending',core_variant_composition=note,lattice_decision='Primaryrouting figure inspected; exactlattice andsourceeligibility notcertified.',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='unresolved',review_stage='source_reviewed',review_run=run,run_id=run,date=L.DATE,legacy_record={},relationships=[],variant_links=[],outstanding_checks=p['unresolved_questions'])
  L.upsert('design_evidence',d,'Recordsourcefamily with explicitassembly andvariant distinctions')
 refs=root.findall('.//ref-list/ref')
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='PAINT2014:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:paint2014:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retainentirebibliography fromgatepassingarticle')
 print(json.dumps(dict(table_rows=counts,references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
