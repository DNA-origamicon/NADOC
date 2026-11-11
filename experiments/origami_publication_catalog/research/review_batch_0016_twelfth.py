"""Enzyme triangle SI: configuration inventory and literal sequence-length audit."""
import json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsnano.9b05746';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/19205261-nn9b05746_si_001.pdf'
 ev=evidence(path,'https://ndownloader.figshare.com/files/19205261','SI3intro enzyme-labeling roles;SI6-8,12,19-22,25,38text inspected. Four staple tables22-37extracted/indexed;PDF22visually confirms sequence/length mismatches rows2/3. Kinetic sections and all individual bases not fully audited.')
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');variants=['2:2:2','2:4:2','2:6:2','2:2:2F'];rows=[]
 for i in range(21,37):
  for m in re.finditer(r'^\s*(\d+)\s+([ACGT]+)\s+(\d+)\s+(.*?)\s*$',pages[i],re.M):
   n,seq,length,rest=m.groups();rows.append(dict(variant=variants[(i-21)//4],number=int(n),sequence_literal=seq,stated_length=int(length),actual_length=len(seq),pdf_page=i+1,remaining_columns=rest))
 assert len(rows)==832;assert all(sum(r['variant']==v for r in rows)==208 for v in variants)
 bad=[r for r in rows if r['stated_length']!=r['actual_length']];assert len(bad)==21
 assert all({r['number'] for r in rows if r['variant']==v}==set(range(1,209)) for v in variants)
 prior=json.loads((L.HERE/'nanocluster_sequence_index.json').read_text());priorseq={r['sequence'] for r in prior['triangle_original_rows']}
 matches={v:sum(r['sequence_literal'] in priorseq for r in rows if r['variant']==v) for v in variants}
 L.atomic(L.HERE/'cascade_triangle_sequence_index.json',json.dumps(dict(evidence=ev,rows=rows,length_mismatches=bad,distinct_literal_sequences=len({r['sequence_literal'] for r in rows}),exact_sequence_matches_to_nanocluster_triangle=matches,limitations='832row occurrences from4varianttables,not832distinctstrands.21lengthmismatches; only PDF22rows2/3visuallychecked. Sharedsequence overlap does not establish full parentdesign identity. Protein coding and conjugation oligos excluded from stapleindex.'),indent=2)+'\n')
 note='SI describes seven enzyme arrangements: three singleenzyme controls and four cascade arrangements(2:2:2,2:4:2,2:6:2,2:2:2F;amylase:maltase:glucokinase). F arrangement moves enzymes to outer edge to increase separation. Four staple tables each list1-208;832rowoccurrences contain226distinctliteral sequences.21rows have actualsequence length different from printedlength;PDF22rows2/3show32ntsequences with47printed,visuallyconfirmed. Do not silently append inferred15nt extensions. GuideON/RxnON/DisGuideON/DisLADstrands inSI6perform enzymeconjugation/attachment and are distinct from trianglecore staples; protein coding sequencesSI3-5are not scaffold sequences. Similarity to other208strand triangle lists warrants parentcomparison but not automatic merge. Mainarticle,scaffoldidentity,routing/fullmodifiedstrand recipes and catalog eligibility unresolved.'
 qs=['Acquire/read mainarticle,identify exact triangleparent and scaffold; resolve originalpublicationdate.','Resolve21sequence-length mismatches against authoritative correction/native/source tables; only first2visuallyconfirmed.','Map enzymeattachment extensions and bridgeoligos to complete variant staple mixtures; no missing bases inferred.','Compare coretriangle with existinglegacy and RDE0063sequences; sharedseq overlap does not prove entire designidentity.','Review remaining kinetic/assemblymethods and verify narrow catalog wholetriangle scope.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design'],catalog_eligibility='unresolved',access='SI_PDF_available; main_pending',rationale=note,reviewer='Codex targetedSI review and sequence-table audit with PDF22visualcheck',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Record enzymeplacement variants and literal sequence discrepancies')
 did='RDE0066';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['Enzyme-functionalized triangle:2:2:2,2:4:2,2:6:2,2:2:2F','Singleenzyme triangle controls'],identity_status='Modifiedtriangle sourcegroup; coreparent and fullvariant sets not verified',lattice_decision='Triangle template reported; exactpacking/whole-object scope requires main/routing review.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified; sequence_length_discrepancies',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Retain modification sourcegroup without completenessclaim')
 refs=[('1','Kodal ALB,Rosen CB,Mortensen MR,Torring T,Gothelf KV.DNA-Templated Introduction of an Aldehyde Handle in Proteins.ChemBioChem2016,17,1338-1342.'),('2','Shaw A,Benson E,Hogberg B.Purification of Functionalized DNA Origami Nanostructures.ACSNano2015,9,4968-4975.')]
 for n,c in refs:
  L.upsert('discovery_edges',dict(edge_id='B0016:cascade:SIref'+n,source_key=k,target_key='citation:cascade:SI:'+n,relation='cites',citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI38reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain2SIreferences')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed14of25: enzyme-triangleSI,4x208stapletables indexed;21lengthdiscrepancies saved,first2visuallyconfirmed.7enzyme configurations kept separate from coregeometry count;2SIreferences retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining11B0016inputs; next10.1021/jacs.9b09093 downloadedSI.',*qs]);L.upsert('batches',b,'Save14of25progress and source-length audit');print(L.validate())
if __name__=='__main__':main()
