"""Network source review and conference lead; close first-pass batch only."""
import re,json,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 rid='B0016';k='10.5539/jmsr.v8n4p14';path=L.ROOT/'assets/research-20261105/amoako2019-publisher.pdf'
 ev=evidence(path,'https://ccsenet.org/journal/index.php/jmsr/article/download/0/0/40935/42269','All7pages extracted text read, includingTable1,Methods,Results,Conclusions andbibliography. Figureimages not yet independently inspected. Headeronline2019-09-30.')
 s=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode();rows=[dict(name=n,sequence=seq,printed_length=int(le),actual_length=len(seq)) for n,seq,le in re.findall(r'^\s*([DEFGK][1-5])\s+([ACGT]+)\s+(\d+)\s*$',s,re.M)];assert len(rows)==18 and all(x['printed_length']==x['actual_length'] for x in rows)
 L.atomic(L.HERE/'amoako2019_connection_index.json',json.dumps(dict(evidence=ev,rows=rows,limitations='18connection-source rows only, not full core staples. MaintextK5 versusTableK2 unresolved; no sequence correction or synthesis package.'),indent=2)+'\n')
 note='Reuses Amoako2015cross and2013nanotube, and2018AuNPattachmentmethod. Cross has four connection sites, two3primebiotinylated strands each, eightmodified D1/D2/E1/E2/F1/F2/G1/G2 replace originalsD3/D4/E3/E4/F3/F4/G3/G4 with8ntATGCATGCextensions. This differs from2015two-end fourstrand variant alreadyRDE0042. Nanotube~100nm has10AuNPsites; authorsreport7occupied inFigure3a and aggregation/distortion of network. One tube-end connection uses biotinylated K1/K2table; prose saysK1/K5, unresolved. Table1has18rows(8extended,8original,2tube), allprintedlengths matchliteral extraction; notfullcores. Streptavidin bridgescross andfourAuNPhelicaltemplates. Experimentalnetwork claim retained with reporteddistortion, no newcrosscore or certifiedsequence set.'
 qs=['Acquire andcompare2013nanotube and2018attachmentprimarysources; exactparent variant unresolved.','Verifycross4site modification against2015RDE0042 and inspectFigure1routing/Figure3TEM visually.','ResolveK5prose versusK2table and exactbiotintermini for nanotubestrands.','Fullcorestaples/scaffold/nativefiles andnanotubelattice remain unverified.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k);p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['reused_design','modified_design'],catalog_eligibility='unresolved',access='mainPDF_available; upstreamsources_pending',rationale=note,reviewer='Codex fullmaintext andconnection-table review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2019-09-30',primary_verified=True,source=ev,meaning='PrimaryPDFexplicitOnlinePublished')
 L.upsert('publication_reviews',p,'Preserve earlier cross reuse and newconnection variant')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='RDE0042')
 if k not in d['publication_keys']:d['publication_keys'].append(k)
 if ev not in d['evidence']:d['evidence'].append(ev)
 if note not in d['core_variant_composition']:d['core_variant_composition']+=' '+note
 d['outstanding_checks']+=qs;L.upsert('design_evidence',d,'Attach2019four-site connectionvariant toexistingcross')
 did='RDE0072';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['Approximately100nm nanotube with10AuNPattachment sites andbiotinendconnection'],identity_status='Provisional reused nanotube sourcegroup;2013parent exactvariantpending',lattice_decision='Nanotube stated, exactpackingpending',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Retain tube separately from existingcross andassemblednetwork')
 # Preserve the entire printed reference region as an indexed source artifact.
 refs=s.split('\nReferences\n',1)[1].split('\nCopyrights\n',1)[0]
 starts=list(re.finditer(r'(?m)^([A-Z][A-Za-z-]+, [A-Z].*?\(\d{4}\))',refs))
 # Author lists can wrap before year; use unindented author-line starts instead.
 lines=refs.splitlines();entries=[];cur=[]
 for line in lines:
  if re.match(r'^[A-Z][A-Za-z-]+, [A-Z]',line):
   if cur:entries.append(' '.join(cur))
   cur=[line.strip()]
  elif cur and line.strip() and not line.startswith('jmsr.') and not re.fullmatch(r'\s*\d+\s*',line):cur.append(line.strip())
 if cur:entries.append(' '.join(cur))
 assert len(entries)==41,len(entries)
 edges=L.read('discovery_edges');known={e['edge_id'] for e in edges}
 for i,c in enumerate(entries,1):
  eid='B0016:amoako2019:ref'+str(i)
  if eid not in known:edges.append(dict(edge_id=eid,source_key=k,target_key='citation:amoako2019:'+str(i),relation='cites',citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Printedbibliography entry'+str(i),reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE,revision_history=[]))
 L.save('discovery_edges',edges)
 # Web-inspected primary abstract and program evidence is a researcher note, not a downloaded source.
 nk='10.4049/jimmunol.202.supp.130.13';np=next(p for p in L.read('publication_reviews') if p['registry_key']==nk)
 npath=L.HERE/'bcr2019_web_evidence.json';L.atomic(npath,json.dumps(dict(date=L.DATE,kind='researcher_summary_of_web_inspection; not_originaldownload',publisher_url='https://academic.oup.com/jimmunol/article-abstract/202/1_Supplement/130.13/7956540',program_url='https://immunology2019.aai.org/wp-content/uploads/2019/04/IMMUNOLOGY-2019-Program.pdf',summary='Publisher abstract datedMay1,2019 reportsIgM/Igk pairedcapture withorigami, electroporation, recovery andsequencing; noinspectablegeometry/sequence set. AAIprogram identifiesposterP1230,abstract130.13 withChaudhary,Schoettle,Dubois,Jones,Ulrich,Yan,Blattman. Localpublisher403 andprogram404/nonPDF; sourcecontent inspected viaweb only.'),indent=2)+'\n')
 ne=evidence(npath,'https://academic.oup.com/jimmunol/article-abstract/202/1_Supplement/130.13/7956540','Researcherwebsummary of primaryabstract andconferenceprogram; notdownloadedoriginal, no design-completeness evidence.')
 np.update(publication_type=['conference_abstract'],review_stage='metadata_screened',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='abstract_and_program_web_inspected; localprimarydownload_failed',rationale='ConferenceposterP1230/abstract130.13 reportsorigami capture probes forpairedBCRanalysis, includingIgM/Igk demonstration. Treat asdesign-bearing lead only; nogeometry,lattice,scaffold,staples orcompletepublicationlink established. Correctlegacyjournal-articletype. No newdesigngroup fromabstract.',reviewer='Codex primarywebabstract andprogramidentity review',run_id=rid,date=L.DATE,unresolved_questions=['Reconcile with fulljournal/preprint andHaoYan/Blattmanpublicationhistory.','Obtaininspectabledesignsources; abstractnotproof ofcompleteness.'])
 if ne not in np['evidence']:np['evidence'].append(ne)
 np['date_evidence'].update(date='2019-05-01',primary_verified=False,source=ne,meaning='Publisherdate viaweb; localoriginal unavailable')
 L.upsert('publication_reviews',np,'Correctconferenceleadtype without promoting abstract tofullsource')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);b['completed_actions'].append('Processed25of25:22substantive reviews+3metadata/abstract-only(Talks,solarnews,BCRposter). Amoako2019crossreuseRDE0042 andtubeRDE0072;18connectionrows and41refs retained. Fullsourcegaps remain.')
 b.update(status='completed',after_counts=L.counts(),validation=[L.validate()],next_queue=['Selectnextbalancedbatch; completionhere meansfirstpass only.','Followpriorityauthor histories andnamedparents:Ahmadi2018,Amoako2013/2018,HaoYanBCRpublicationmatch.','Talks/news access andallunresolvedsourcechecks remainopen; FNANOdeferred.']);L.upsert('batches',b,'Closefirstpass25inputs while preserving substantivecoveragegaps');print(L.validate())
if __name__=='__main__':main()
