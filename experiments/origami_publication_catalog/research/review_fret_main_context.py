"""Targeted original-paper methods and parent citations; no identity merge."""
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/jacs.9b09093'
 ev=evidence(L.ROOT/'assets/research-20261105/bartnik-thesis.pdf','https://edoc.ub.uni-muenchen.de/26670/1/Bartnik_Kira.pdf','Original paper reprint PDF88-98: Figure1 caption printed816, Results opening817, Materials and Methods DNA Origami Assembly and Purification, Associated Content, references25-27. Targeted reading; remaining results and complete bibliography review pending.')
 note='Original-paper assembly methods explicitly identify a square-lattice two-layer p7560 frame and say the design was inspired by Endo et al.2010 base-excision-repair nanochip (reference25). Results also cite related frames references26-27. This supports inspiration, not unchanged reuse or a verified complete source set. Associated Content lists one PDF and two MOV files; native caDNAno is not listed there. Full experimental geometry and source mapping remain to be audited.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 if note not in p['rationale']: p['rationale']+=' '+note
 if ev not in p['evidence']: p['evidence'].append(ev)
 p['unresolved_questions']=[q for q in p['unresolved_questions'] if not q.startswith('Review remainder of acquiredmainreprint')]
 p['unresolved_questions'].append('Read remaining main results and retain complete main bibliography; reconcile refs25-27 to publication identities and inspect parent source geometry before asserting reuse.')
 L.upsert('publication_reviews',p,'Resolve lattice from explicit original-paper methods; retain inspiration boundary')
 d=next(x for x in L.read('design_evidence') if x['design_id']=='RDE0067')
 d['lattice_decision']='Square-lattice two-layer p7560 frame explicitly stated in original-paper assembly methods. Whole-frame catalog eligibility and source completeness remain unresolved.'
 if note not in d['core_variant_composition']: d['core_variant_composition']+=' '+note
 if ev not in d['evidence']: d['evidence'].append(ev)
 d['outstanding_checks']=p['unresolved_questions']
 L.upsert('design_evidence',d,'Record explicit square lattice without catalog promotion')
 refs=[('25','Endo M; Katsuda Y; Hidaka K; Sugiyama H. A Versatile DNA Nanochip for Direct Analysis of DNA Base-Excision Repair. Angew Chem Int Ed 2010,49,9412-9416.','design_inspired_by'),('26','Endo M et al. Single-Molecule Visualization of the Activity of a Zn2+-Dependent DNAzyme. Angew Chem Int Ed 2015,54,10550-10554.','cites'),('27','Takeuchi Y et al. Single-Molecule Observations of RNA-RNA Kissing Interactions in a DNA Nanostructure. Biomater Sci 2016,4,130-135.','cites')]
 for n,c,relation in refs:
  L.upsert('discovery_edges',dict(edge_id='B0016:fret:mainref'+n,source_key=k,target_key='citation:fret:main:'+n,relation=relation,citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Original paper reference'+n+'; assembly methods for reference25',reconciliation_state='pending_identity_date_scope_reconciliation',run_id='B0016',date=L.DATE),'Retain inspected parent/context lead without inferred DOI or identity')
 b=next(x for x in L.read('batches') if x['batch_id']=='B0016')
 action='FRET followup: explicit square lattice and Endo2010 inspiration recorded; three main-reference leads retained. Still15of25 inputs reviewed,10remaining.'
 if action not in b['completed_actions']: b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Next balanced input10.1021/acsami.9b20707;10inputs remain.','FRET: reconcile refs25-27, retain remaining bibliography, review remaining results and source completeness.','Continue priority author histories and citation routes; FNANO deferred until diminishing returns.'])
 L.upsert('batches',b,'Save targeted methods followup and reproducible queue')
 print(L.validate())
if __name__=='__main__': main()
