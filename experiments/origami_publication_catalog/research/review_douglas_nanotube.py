"""Save manually inspected author-hosted primary nanotube evidence; no reconstruction."""
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1073/pnas.0700930104';run='douglas-nanotube-primary-20261105'
 ev=evidence(L.ROOT/'assets/research-20261105/douglas-2007_PNAS_nanotube.txt','https://bionano.ucsf.edu/txt/2007_PNAS_nanotube.txt','Abstract; DNA-nanotube design; Heterodimerization and liquid crystal formation; Fig1–2 captions; Methods; references')
 questions=['Acquire and inspect SI Methods and Appendices1/2, including scaffold register permutations, sequence-generating program and actual staple sets.','Resolve front/rear blocking and joining strands separately from 168 core staples per monomer; verify complete sequence-to-routing mapping.','Verify narrower catalog lattice/source eligibility from full diagrams and sources; 120-degree six-helix arrangement alone is not a completed catalog check.']
 p=next(r for r in L.read('publication_reviews') if r['registry_key']==key)
 p.update(review_stage='fulltext_reviewed',relevance='design_bearing',design_contributions=['new_design'],catalog_eligibility='unresolved',evidence=[ev],rationale='Primary author-hosted text reports two 7308nt scaffolded six-helix monomers, each with168 core42nt staples and distinct scaffold cyclic registers/end blockers. Separately folded front/rear components join into a heterodimer with an extra42bp segment; TEM characterizes monomers and dimers. This is an experimental origami design, not merely an NMR citation.',unresolved_questions=questions,reviewer='Codex primary text section inspection',access='partial',run_id=run,date=L.DATE)
 L.upsert('publication_reviews',p,'Inspect primary nanotube design, assembly and experimental characterization')
 d=dict(design_id='RDE0008',publication_keys=[key],named_objects=['Front six-helix nanotube monomer','Rear six-helix nanotube monomer','Front/rear heterodimer assembly'],core_variant_composition='Each7308nt monomer has168 core42nt staples; different cyclic scaffold registers and outer-end blockers. Joining ends include three unpaired staples each and create a42bp interfacial segment. Core variants and assembled heterodimer remain distinct within this source-review family.',lattice_decision='six_helix_120_degree_arrangement_reported; catalog_check_pending',catalog_eligibility='unresolved',source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=questions,relationships=[],variant_links=[],legacy_record={},review_run=run,date=L.DATE)
 old=next((d for d in L.read('design_evidence') if d['design_id']=='RDE0008'),None)
 assert old is None or old['publication_keys']==[key]
 L.upsert('design_evidence',d,'Retain distinct component/assembly evidence without claiming complete synthesis sources')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0004')
 actions=['Reconciled two Douglas bibliography PMID links from local primary XML DOI identifiers.','Compared original2018 pScaf2268 CSV with pinned copy: identical; native49-position staple path does not resolve51-character ambiguous sequence.','Inspected author-hosted2007 nanotube primary text and recorded RDE0008 front/rear/heterodimer source-review family.','Seven-PMID EuropePMC identity request failed HTTP503; other routes remain open.']
 for a in actions:
  if a not in b['completed_actions']:b['completed_actions'].append(a)
 if key not in b['input_keys']:b['input_keys'].append(key)
 b['after_counts']=L.counts();b['validation']=[L.validate()]
 b['next_queue']=['Acquire2007 nanotube SI Methods and Appendices1/2; reconcile later NMR protocol reuse.','Resolve remaining Douglas bibliography identifiers and inspect2017 Perspective reference list.','Inspect pScaf connector sets; retain original-source2268 ambiguity.','Rotate to next balanced screening batch, then remaining FNANO years and citation routes.']
 L.upsert('batches',b,'Save primary-source follow-up and explicit access/source limitations')
 print(L.validate())
if __name__=='__main__':main()
