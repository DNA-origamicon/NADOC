"""Source inventory and evidence review, not molecular authoring or reconstruction."""
import json,re,subprocess,collections
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1021/nn5011914';path=L.ROOT/'assets/sources/acs-expansion-20261104/3604944-nn5011914_si_001.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f')
 rows=[]
 for page,text in enumerate(pages,1):
  for start,end,seq,length in re.findall(r'(\d+\[\d+\])\s+(\d+\[\d+\])\s+([ACGT]+)\s+(\d+)',text):
   rows.append(dict(page=page,start=start,end=end,sequence=seq,printed_length=int(length),extracted_length=len(seq)))
 assert len(rows)==144 and len({(r['start'],r['end']) for r in rows})==144
 mismatches=[r for r in rows if r['printed_length']!=r['extracted_length']]
 assert len(mismatches)==12 and all(r['printed_length']==42 and r['extracted_length']==63 and r['page']==13 for r in mismatches)
 ev=evidence(path,'https://ndownloader.figshare.com/files/3604944','SI pp3–11 captions; pp12–15 full table text inventory; p13 rendered1800px confirms blue fluor handles and printed42 length; Note1 only identified, not validated')
 main_ev=evidence(L.ROOT/'assets/sources/PMC4046785.xml','https://doi.org/'+doi,'Results and Discussion; Methods DNA Nanostructure Folding and Encapsulation; author names')
 inventory=dict(source=ev,table_rows=rows,unique_endpoint_pairs=144,printed_length_counts=dict(collections.Counter(r['printed_length'] for r in rows)),length_discrepancies=mismatches,interpretation='Twelve printed42 rows contain63bases:42base prefix plus shared21base suffix AAATTATCTACCACAACTCAC. Rendered p13 colors the added suffix blue, identified as fluorophore handle by Table1 caption. Printed length omits this handle; no sequence corrected. Not a routing, complementarity or complete variant validation.',remaining_checks=['Read colored routing map and verify scaffold/staple paths.','Identify exact handle subsets/replacements for0/12/24outer handle variants.','Verify separate fluor/lipid-conjugate oligonucleotides and scaffold sequence.','Inspect Note1 curvature derivation/code separately; no simulation performed.'])
 L.atomic(L.HERE/'perrault2014_sequence_inventory.json',json.dumps(inventory,indent=2)+'\n')
 note='Extended source review: p7308DNO has12curved6HBstruts,144staples,12inner fluor handles and0/12/24/48outer lipid-handle variants. Nonencapsulated/encapsulated states and lipid formulations are material/composition conditions, not automatically new DNA cores. Table1 contains144unique endpoint rows. Twelve blue fluor-handle rows on PDFp13 contain63bases yet printed length42; rendered color/table confirms21base handle omitted from length column. Preserve raw sequence and printed length independently. Remaining132row lengths agree with extracted sequences. This arithmetic inventory does not certify complementarity/routing or all variant compositions. SI Fig1 notes5Tinter-strut linkers and schematic/TEM size discrepancies; model dimensions are not measured topology. Existing wireframe catalog exclusion retained while broad design-bearing relevance remains.'
 qs=inventory['remaining_checks']+['Exact FNANO2012poster overlap remains unverified despite matching two-author group and encapsulation topic.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==doi)
 for e in [ev,main_ev]:
  if e not in p['evidence']:p['evidence'].append(e)
 if note not in p['rationale']:p['rationale']+=' '+note
 for q in qs:
  if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 p['review_stage']='design_sources_reviewed'
 L.upsert('publication_reviews',p,'Extend source-backed composition and sequence review; preserve existing scope exclusion')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='S041')
 d.update(core_variant_composition=note,outstanding_checks=qs,source_completeness='not_verified')
 for e in [ev,main_ev]:
  if e not in d['evidence']:d['evidence'].append(e)
  if e not in d['source_files']:d['source_files'].append(e)
 L.upsert('design_evidence',d,'Update stable S041 evidence without altering legacy record or creating structures')
 p=next(p for p in L.read('publication_reviews') if p.get('run_id')=='fnano-2012' and p.get('title')=='Encapsulation of D DNA Nanostructures in Lipid Bilayers')
 L.upsert('discovery_edges',dict(edge_id='fnano2012:perrault-counterpart',source_key=p['registry_key'],target_key=doi,relation='possible_publication_counterpart',evidence_url=main_ev['url'],local_file=main_ev['local_file'],sha256=main_ev['sha256'],locator='Program Perrault/Shih author group and membrane encapsulation topic agree; exact2012presentation versus2014paper scope unverified',reconciliation_state='candidate_scope_pending',run_id='fnano2012-sources',date=L.DATE),'Retain conference/journal candidate without identity merge')
 if main_ev not in p['evidence']:p['evidence'].append(main_ev)
 q='Possible2014journal counterpart10.1021/nn5011914; same two authors, exact results overlap pending.'
 if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 L.upsert('publication_reviews',p,'Save matching author/topic candidate with presentation uncertainty')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0008');action='Extended S041 Perrault source review; inventoried144table rows and visually checked12fluor-handle length discrepancies; journal candidate retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),next_queue=['Reconcile Perrault variant subsets/native routing and conference abstract','Balanced screening batch B0012','Full Han gridiron/Bell sources and FNANO2011 program'])
 L.upsert('batches',b,'Save source-review batch handoff')
 print(L.validate())
if __name__=='__main__':main()
