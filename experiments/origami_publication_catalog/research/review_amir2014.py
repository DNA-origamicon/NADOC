"""Audit qualifying robot strand pool while preserving legacy D025 identity."""
import json,re,subprocess,collections,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nnano.2014.58';run='SEQ0001-followup';a=L.ROOT/'assets/sources';si=a/'PMC4012984-41565_2014_BFnnano201458_MOESM9_ESM.pdf';xml=a/'PMC4012984.xml'
 em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4012984/fullTextXML','Main opening throughAND/OR/XOR/halfadder/NAND/NOT/CNOT descriptions andref19 inspected; remainingmain not fullyread. XMLepub2014-04-06.')
 es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fnnano.2014.58/MediaObjects/41565_2014_BFnnano201458_MOESM9_ESM.pdf','PDF1 correctionnotice,PDF4truth table,PDF5nativefile statement,PDF8-14numberedstrand list,PDF15robot gate/payload recipes andPDF16folding/purification. RemainingSI notfullyreviewed; tablebase imageaudit pending.')
 pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f');rows=[];cur=None
 for i in range(7,14):
  for line in pages[i].split('\n'):
   m=re.match(r'\s*(\d+)\s+([A-Za-z]+)\s+(.*)',line)
   if m:
    ident=int(m[1]);rest=m[3];seq=re.search(r'[ACGT]{10,}',rest)
    if not seq:continue
    cur=dict(id=ident,category=m[2],label=rest[:seq.start()].strip(),sequence=seq.group(),pdf_page=i+1);rows.append(cur)
   elif cur and re.fullmatch(r'\s*[ACGT]+\s*',line):cur['sequence']+=line.strip()
 assert [r['id'] for r in rows]==list(range(1,279))
 counts=dict(collections.Counter(r['category'] for r in rows))
 L.atomic(L.HERE/'amir2014_strand_index.json',json.dumps(dict(evidence=es,rows=rows,categories=counts,limitations='Literal numberedpool extraction with wrappedlines joined. Includesgatealternatives,guides andremovalstrands; not278strands per robot. Modifications/variantrecipes andper-baseimage verification pending.'),indent=2)+'\n')
 note='Main explicitly reuses Douglas/Bachelet/Church2012robot(ref19,10.1126/science.1214081). D025retained. CorrectedSI lists278numberedentries:153core,82edge,1Keyhandle,11handles,7guides,7guideremoval,17gates. These form a pool,not a single278-staple recipe. PDF15provides E/P1/P2/N/F/P3 gate andpayload combinations; Eopen lacks sensingstrands. Positivekeys andnegativeclasps changeinteraction logic; AND/OR/XOR/NAND/NOT/CNOT mixtures are not newcoregeometries. M13mp18NEBN4040. PDF5states nativecaDNAnoJSON downloadable but not incurrentacquired set. PDF1documents2014-04-17SIcorrection addingNote6; do not confuse correctiondate withpublicationdate.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['reused_design','modified_design'],catalog_eligibility='unresolved',rationale=note,access='main_XML_correctedSI_PDF_available; nativeJSON_pending',reviewer='Codex targeted robot sourcepool/variant review',run_id=run,date=L.DATE,unresolved_questions=['Verifyper-robot core+edge+gate+handle recipes andguide removal;278entrypool isnot completeindividualrecipe.','Inspect statednativecaDNAnoJSON ifdirectly available; compare2012parent routing before exactcoreidentity claim.','Independent tablebase/image audit,mainremainingsections andSIremainingfigures pending.','PreserveSIcorrection chronology andverify narrowcatalogeligibility independently.'])
 for e in [em,es]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence']=dict(date='2014-04-06',primary_verified=True,source=em,meaning='DepositedXMLexplicit epub;SIcorrectedApril17')
 L.upsert('publication_reviews',p,'Recordexplicitreuse andnumberedsourcepool withoutnewcorecount')
 d=next(x for x in L.read('design_evidence') if x['design_id']=='D025')
 for f in ['evidence','source_files']:
  for e in [em,es]:
   if e not in d[f]:d[f].append(e)
 if note not in d['core_variant_composition']:d['core_variant_composition']+=' '+note
 for q in p['unresolved_questions']:
  if q not in d['outstanding_checks']:d['outstanding_checks'].append(q)
 d.update(review_stage='source_reviewed',review_run=run,source_completeness='not_verified')
 L.upsert('design_evidence',d,'EnrichstableD025 withliteralstrandpool andexplicitreuse evidence')
 root=E.parse(xml).getroot();refs=root.findall('.//ref-list/ref')
 for r in refs:
  n=r.get('id');doi=r.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='AMIR2014:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:amir2014:'+n,relation='cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retainentirebibliography ofgatepassingpaper')
 L.upsert('discovery_edges',dict(edge_id='AMIR2014:reuse2012',source_key=k,target_key='10.1126/science.1214081',relation='reuses_design_from',evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='Mainopening andref19',reconciliation_state='explicit_reuse; exact_variant_pending',run_id=run,date=L.DATE),'Explicitreuse attribution; exactnativevariantunverified')
 print(json.dumps(dict(categories=counts,refs=len(refs),validation=L.validate())))
if __name__=='__main__':main()
