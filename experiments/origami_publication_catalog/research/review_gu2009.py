"""Review a source-gate passing paper; preserve core/device distinctions."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nnano.2009.5';rid='B0017';a=L.ROOT/'assets/sources/pre2020-expansion';mainfile=a/'PMC2836238.xml';si=a/'supplements/PMC2836238-41565_2009_BFnnano20095_MOESM188_ESM.pdf'
 em=evidence(mainfile,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2836238/fullTextXML','Entire main body text read; manuscript XML explicit epub2009-02-15;14references. Main figure images not independently audited.')
 es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fnnano.2009.5/MediaObjects/41565_2009_BFnnano20095_MOESM188_ESM.pdf','PDF1-3 experimental methods,PDF3-11helper list,PDF12FigureS1 routing visually inspected,endingtwo references. Remainingcapture/cassette sequence diagrams andquantitation not fully audited.')
 pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
 seq=[dict(name=m.group(1)+','+m.group(2),sequence=m.group(3),pdf_page=i) for i,pg in enumerate(pages[:11],1) for m in re.finditer(r'(?m)^\s*(\d+),\s*(\d+);\s*([ACGT]+)',pg)]
 assert len(seq)==208 and len({r['name'] for r in seq})==208
 L.atomic(L.HERE/'gu2009_helper_index.json',json.dumps(dict(source=es,rows=seq,limitations='Literal helper-list extraction; no independent per-base image audit,scaffold coverage or cassette/capture recipe certification.'),indent=2)+'\n')
 note='New120x50nm planar origami substrate with two cassette slots and asymmetric orientation notch. SI lists208uniquely named helper strands and provides colored strand routing(FigS1). Main explicitly distinguishes substrate from two independently programmed PX/JX2 cassettes and four capture tiles:two opposite triangle orientations,diamond,andlinear three-domain motif. Four binary cassette combinations are device states,not four distinct origami cores. M13 plasmid fromNEB,1:7scaffold:staple ratio; exact clone/full scaffold sequence and unused-region treatment need source verification. Main citesRothemund2006method,not proof of identical rectangle routing. Source gate passes; base/variant completeness unverified.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design'],catalog_eligibility='unresolved',access='main_XML_and_SI_PDF_available',rationale=note,reviewer='Codex full main body and targeted SI/table/routing review',run_id=rid,date=L.DATE,unresolved_questions=['Verify208helper sequences against source images and scaffold complementarity/coverage; exactM13clone andunused region unresolved.','Audit SI FiguresS2-S6 cassette,capture,set/fuel strands; do not conflate ancillary tiles with origami core.','Adjudicate narrow lattice/source eligibility after source checks; main figure images andremainingSIquantitation not independently reviewed.'])
 for e in [em,es]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence']=dict(date='2009-02-15',primary_verified=True,source=em,meaning='Deposited manuscriptXML explicit epub;April2009isissue.')
 L.upsert('publication_reviews',p,'Review qualifying208helper source and distinguish core from device states')
 did='RDE0073';existing=next((x for x in L.read('design_evidence') if x['design_id']==did),None)
 assert existing is None or existing['publication_keys']==[k]
 d=dict(design_id=did,publication_keys=[k],named_objects=['120x50nm notched two-slot origami substrate','PX/JX2 cassette-state andcapture-tile functional variants'],identity_status='Newsourcegroup; no exact parent-core identity asserted',core_variant_composition=note,lattice_decision='FigureS1 shows planar parallel scaffold/staple routing withslots/notch; narroweligibility unresolved pendingsource audit.',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='unresolved',review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={},relationships=[],variant_links=[],outstanding_checks=p['unresolved_questions'])
 L.upsert('design_evidence',d,'Record one qualifying origami substrate family; no molecular authoring')
 root=E.parse(mainfile).getroot();refs=root.findall('.//ref-list/ref');assert len(refs)==14
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='B0017:gu2009:'+n,source_key=k,target_key=doi.text.lower() if doi is not None else 'citation:gu2009:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XMLreference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain entire14reference bibliography of gate-passing paper')
 for n,c in enumerate(['Seeman1990 DeNovoDesign of sequences for nucleic acid structure engineering,JBiomolStructDyn8,573-581.','Ke,Lindsay,Chang,Liu,Yan2008 Self-assembled water-soluble nucleic acid probe molecules for label-free RNA hybridization,Science319,180-183.'],1):
  L.upsert('discovery_edges',dict(edge_id=f'B0017:gu2009:si:{n}',source_key=k,target_key=f'citation:gu2009:si:{n}',relation='cites',citation=c,evidence_url=es['url'],local_file=es['local_file'],sha256=es['sha256'],locator='SIendingreference'+str(n),reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain twoSIreferences; method use not exactdesign reuse')
 b=next(x for x in L.read('batches') if x['batch_id']==rid)
 action='Gu2009 qualifying source reviewed:208namedhelpers,RDE0073notchedtwo-slot substrate,16main/SIreferences; sourcecompletenessunverified. FiveB0017inputs nowhave substantive/metadata review before/aftergate;25gate dispositions remain.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Nextsource-gate passing paper10.1038/nmeth.2835; preserve separatevariants and avoid scaffold-string counts.','Continue otherSEQ0001passing sources andbalanced firstscreens; no rescue of no-table cases.','Gu2009 cassette/set/fuel/sourcecoverage audit remains,not required to block nextpassing paper. FNANOdeferred.'])
 L.upsert('batches',b,'Checkpoint source-gate passing scientific review')
 print(L.validate())
if __name__=='__main__':main()
