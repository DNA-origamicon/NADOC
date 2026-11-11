"""Primary Rothemund source audit: distinguish seam variants and diagram caveats."""
import re,json,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1038/nature04586';rid='B0017';a=L.ROOT/'assets/sources/pre2020-expansion'
 e1=evidence(a/'rothemund2006-s1.pdf','https://rothemundlab.caltech.edu/downloads/folding_dna_supp1.pdf','NoteS1design workflow opening; NoteS3overviewPDF20; tallrectangleFiguresS35-S38PDF42-45; scaffoldFigureS39captionPDF46; MethodsS4.1PDF47. PDF44FigureS37 visuallyinspected. RemainingSI notfullyread.')
 e2=evidence(a/'rothemund2006-s2.pdf','https://rothemundlab.caltech.edu/downloads/folding_dna_supp2.pdf','Note12PDF1 introduction and explicitsmiley diagramwarnings; figurecaption index. Fullbase/routing diagrams not independently audited.')
 em=evidence(L.ROOT/'assets/research-20261105/rothemund2006-main.pdf','https://rothemundlab.caltech.edu/downloads/folding_dna.pdf','Primarypaper header16March2006, title/abstract/opening inspected only; remainingmain pending.')
 pages=subprocess.check_output(['pdftotext','-layout',str(a/'rothemund2006-s1.pdf'),'-']).decode().split('\f');rows=[dict(name=n,well=w,sequence=s,pdf_page=45) for n,w,s in re.findall(r'([\w-]+),([A-H]\d{1,2}),([ACGT]+)',pages[44])]
 assert len(rows)==225 and len({x['name'] for x in rows})==225
 L.atomic(L.HERE/'rothemund2006_tall_rectangle_index.json',json.dumps(dict(evidence=e1,rows=rows,limitations='LiteralTableS38 extraction for bridgedseam. Threecolumnplate identity not reconstructed; not experimentalmap recipe. Unbridgedseam andanti-stacking modifications need explicitvariant mapping; fullbase audit pending.'),indent=2)+'\n')
 note='Primarysources support existingS001-S007families, no newgroupcreated. TallrectangleS007:32helices,224ntnominalwidth(FigS35), bridgedseam basicdiagramS36 versus unbridgedexperimentalmapdiagramS37. S37adds edgeT4loops andtwo cornerT4tails. S38lists225uniquelynamedsequence rows explicitlyforBRIDGEDseam, so do not equate this list withmapexperimentmixture. S2Note12also labels tallrectanglebridgedseam. SourceS39providesNEBM13mp18clone sequence basedon2002resequencing; cloneidentity matters for downstreamreuse. Square/starlinearization andtriangleassembly modifications are described inMethods andrequire separatevariant audits.'
 qs=['Read mainpaper andremainingSI, retain completebibliographies andallvariant evidence.','MapS007225bridgedrows toactualunbridgedmap andanti-stacking variants; independentlyverify sequences andplateidentity.','Audit remainingS001-S006sourcevariants without assuming sevenlegacygroups exhaust designs.','SmileyS004: Note12explicitly warns noncentralseams haveincorrectscaffoldcrossovers andspuriousdashes; usecoloredstrandcontinuity andfoldingpath, notuncorrectedASCIItopology.','Review partialsquare,patternedstrands,trianglehexamers/lattices andallcontrols separately; no fixeddesigncount.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',access='main_and_twoSI_PDFs_available',rationale=note,reviewer='Codex targetedprimarySI andsource-variant audit',run_id=rid,date=L.DATE,unresolved_questions=qs)
 for e in [e1,e2,em]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence'].update(primary_verified=True,source=em,meaning='Primarypaperissueheader16March2006; pre2020confirmed, exactearliestonline notseparatelyreconciled')
 L.upsert('publication_reviews',p,'Reviewprimarysources without conflating listed andexperimental variants')
 for did,newnote,evs in [('S007',note,[e1,e2]),('S004','Note12 explicitly warns incorrect scaffoldcrossovers at noncentral seams andspuriousdashes maymisrepresentstaplecontinuity. Colored bases andoriginalfoldingpath must resolve routing beforecomplete-source certification.',[e2])]:
  d=next(d for d in L.read('design_evidence') if d['design_id']==did)
  for e in evs:
   if e not in d['evidence']:d['evidence'].append(e)
   if e not in d['source_files']:d['source_files'].append(e)
  if newnote not in d['core_variant_composition']:d['core_variant_composition']+=' '+newnote
  for q in qs:
   if q not in d['outstanding_checks']:d['outstanding_checks'].append(q)
  d.update(source_completeness='not_verified',review_stage='source_reviewed',review_run=rid)
  L.upsert('design_evidence',d,'Preserve stablelegacyID andattach specificsource caveat')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed1of25: Rothemund2006targetedSI;S007bridged225rowlist distinguished fromunbridgedmap;S004explicitdiagramwarnings recorded. MainPDFacquired, mostlyunread.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['ReadRothemundmain andremainingSI/variants; sourcecompletenessopen.','NextbalancedinputPMC7080001, thenremainingB0017queue.','Continuepriorityauthor histories andcitationroutes; FNANOdeferred.']);L.upsert('batches',b,'Save1of25sourceaudit andconcretenextqueue');print(L.validate())
if __name__=='__main__':main()
