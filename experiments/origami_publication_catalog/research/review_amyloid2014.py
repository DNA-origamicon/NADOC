"""Qualifying amyloid template sources; distinguish nonstandard tube and planar platform."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nnano.2014.102';run='SEQ0001-followup';a=L.ROOT/'assets/sources/pre2020-expansion';xml=a/'PMC4082467.xml';si=a/'supplements/PMC4082467-41565_2014_BFnnano2014102_MOESM286_ESM.pdf'
 em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4082467/fullTextXML','Mainopening platform/tube construction andexplicitcross-section angles;SequenceandStructureDesignMethods inspected. Remainingmain notfullyread.')
 es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fnnano.2014.102/MediaObjects/41565_2014_BFnnano2014102_MOESM286_ESM.pdf','SIsections1/2sequence poolsPDF2-25;FigureS1captionPDF27. Tube/sticky/capture/leg labels andfourtileconnector headings inspected. Base-by-base imageaudit andremainingSI pending.')
 pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f');text='\n'.join(pages)
 tube=[]
 for i,pg in enumerate(pages,1):
  last='Sticky 1:' in pg
  if last:pg=pg.split('Sticky 1:')[0]
  for line in pg.split('\n'):
   m=re.match(r'(?:Tube |Staple)(\d+):[ \t]*([ACGT ]*)$',line.strip())
   if m:tube.append(dict(id=int(m[1]),sequence=m[2].replace(' ',''),pdf_page=i))
   elif tube and re.fullmatch(r'[ACGT ]+',line.strip()):tube[-1]['sequence']+=line.strip().replace(' ','')
  if last:break
 assert len(tube)==171 and len({r['id'] for r in tube})==171
 platform=text.split('[2]  SEQUENCES OF ORIGAMI STAPLE STRANDS FOR THE DNA')[1].split('A set of sticky ends for the first tile:')[0]
 base=[dict(id=int(m[1]),sequence=re.sub(r'\s','',m[2])) for m in re.finditer(r'(?m)^\s*(\d+):\s*([ACGT][ACGT \t]*)',platform)]
 assert len(base)>=100
 L.atomic(L.HERE/'amyloid2014_source_index.json',json.dumps(dict(evidence=es,tube_rows=tube,platform_base_rows=base,limitations='Literalbasepool extraction; source labels123 asStaple123 ratherthanTube123. No certificationof completeness; modifiedSticky/Capture/Leg andfour32-entrytileconnector sets remain tobe reconciled withbasepools. Figurecolors encode non-scaffold segments.'),indent=2)+'\n')
 tube_note='20helix tube fromtwo10helixhalf-tubes,M13scaffold. Main specifies9domains15bp,10domains26bp,1domain25bp between crossovers,approximating20gon162degreeangles;one3ntsslink permitsopening. Explicitnonstandardcircularcrosssection excludesnarrowlatticecatalog.171Tube-labelledbaseentries plusdistinctclosingstickystrands,peptideconjugate/biotinconjugate,AuNPcapture andplatformLegvariants;not171strandscompleteperexperiment.'
 plat_note='Fourplanarorigamitiles form2x2platform viafourseparate32-entryconnector sets. Sharednumberedstaplepool andLegattachmentvariants supportthreeone-fibril orientations andonetwo-fibril arrangement. Assemblyorientations do notautomaticallymeanfournewcoregeometries; exacttile/coreparentidentity unresolved.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',rationale=tube_note+' '+plat_note,reviewer='Codex targetedsourcepool andexplicitgeometry review',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=['MapTube/Sticky/Capture/Leg/conjugates intoexact experimentalrecipes;verifysequencecolors andbases.','Mapsharedplatformpool plusfourconnector sets andattachmentLegs;resolveexactcoreparent/reuse.','Independentdiagram/tableimageaudit andcomplete-scaffold/sourceverification pending; nativefilesnotestablished.'])
 for e in [em,es]:
  if e not in p['evidence']:p['evidence'].append(e)
 root=E.parse(xml).getroot();ep=root.find('.//article-meta/pub-date[@pub-type="epub"]')
 if ep is not None and ep.findtext('day'):p['date_evidence']=dict(date=ep.findtext('year')+'-'+ep.findtext('month').zfill(2)+'-'+ep.findtext('day').zfill(2),primary_verified=True,source=em,meaning='DepositedXMLepub')
 L.upsert('publication_reviews',p,'Reviewqualifyingtemplates withoutbroad/narrow scopeconflation')
 for did,names,note,elig in [('RDE0080',['20helixamyloid-nucleatingtube','Conjugate,closing,capture andattachmentvariants'],tube_note,'excluded'),('RDE0081',['Four-tile2x2planarplatform','Tileconnectors andfibrilorientationvariants'],plat_note,'unresolved')]:
  old=next((x for x in L.read('design_evidence') if x['design_id']==did),None);assert old is None or old['publication_keys']==[k]
  d=dict(design_id=did,publication_keys=[k],named_objects=names,identity_status='Provisionalsourcefamily; exactparents/variantsunreconciled',core_variant_composition=note,lattice_decision='Nonstandard20goncrosssectionexplicit;excluded' if elig=='excluded' else 'Planartilesexplicit; exactnarroweligibilitypendingsourceaudit',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility=elig,review_stage='source_reviewed',review_run=run,run_id=run,date=L.DATE,legacy_record={},relationships=[],variant_links=[],outstanding_checks=p['unresolved_questions'])
  L.upsert('design_evidence',d,'Recordsourcefamilyandexplicitnarrowgeometrydecision')
 refs=root.findall('.//ref-list/ref')
 for r in refs:
  n=r.get('id');doi=r.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='AMYLOID2014:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:amyloid2014:'+n,relation='cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retainfullqualifyingpaperbibliography')
 print(json.dumps(dict(tube_rows=len(tube),platform_rows=len(base),references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
