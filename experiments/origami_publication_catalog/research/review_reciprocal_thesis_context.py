"""Partial reproduction supplies parent evidence; do not backdate thesis additions."""
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acs.nanolett.9b02786';rid='B0016'
 ev=evidence(L.ROOT/'assets/research-20261105/johnson-control-thesis.pdf','https://etd.ohiolink.edu/acprod/odb_etd/ws/send_file/send?accession=osu1577996668813983&disposition=inline','Printed121/156chapter contribution statements; section3.4printed124(PDF145);3.8.1printed148(PDF169);4.4printed158(PDF179);4.5printed165-167; bibliographyrefs2/284. Targeted sections read,not complete chapters.')
 note='Johnson2020thesis chapters3/4 explicitly reproduced in part from2019Reciprocal paper. Section3.4 and3.8.1 explicitly identify prior hinge ref2(Marras2015ProgrammableMotion,10.1073/pnas.1408869112); section3.4 also cites ref284(Le2016NucleosomeNanocaliper). Three NP-binding strands perarm/site; top20A, bottom9A atsites1-3 and bottom5-9A atsite4; NPcoating23T. Section4.4 confirms54unique polymerizationoverhangs,consistent withSIlabel count. Exact extra bottomset roles remain unresolved. ThesisMethods call scaffoldm13mp18 whereasSIgel labels8064; do not substitute7249nt without source evidence. Chapter4 also presents sideways arrays and controlledlength/NPplacement beyond shared zigzag topic; partialreproduction does not prove these appeared before2020.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p['rationale']+=' '+note
 p['evidence'].append(ev)
 p['unresolved_questions']=[q for q in p['unresolved_questions'] if not q.startswith('Review Johnson2020thesis relevantchapters')]
 p['unresolved_questions']+=['Compare exact hinge variant against Marras2015 and Le2016sources; parent relation supported but unchangedsequence identity not established.','Reconcile8064gel scaffold label with generically namedm13mp18 inthesisMethods.','Read remaining relevant thesis/journal content; do not attribute thesis sideways-array additions to2019without corroboration.']
 p['reviewer']='Codex SI review plus targeted author-dissertation context';p['run_id']=rid
 L.upsert('publication_reviews',p,'Add explicit priorhinge attribution and preserve partialreproduction boundary')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='RDE0065')
 d['evidence'].append(ev);d['core_variant_composition']+=' '+note
 d['relationships'].append(dict(relation='modified_design_from',publication_key='10.1073/pnas.1408869112',qualification='Explicitthesis3.4/3.8.1ref2; exactsourcevariant remains unverified',evidence=ev))
 d['outstanding_checks']=p['unresolved_questions'];L.upsert('design_evidence',d,'Attach supported parent relation without merging sourcegroups')
 for suffix,target,relation,citation in [('parent','10.1073/pnas.1408869112','modifies_design_from','Marras2015Programmable motion of DNA origami mechanisms; thesisref2 explicitlystartinghinge.'),('nanocaliper','10.1021/acsnano.6b03218','related_source_lead','LeJVetal.Probing Nucleosome Stability with a DNA Origami Nanocaliper.ACSNano2016,10(7),7073-84; thesisref284 cited alongside parenthinge.')]:
  L.upsert('discovery_edges',dict(edge_id='B0016:reciprocal:thesis:'+suffix,source_key=k,target_key=target,relation=relation,citation=citation,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='explicit_parent_attribution; exact_variant_pending',run_id=rid,date=L.DATE),'Retain explicitparent/context references from author thesis')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Followup to13of25: Johnsonthesis targetedsections supportMarras2015hingeparent and54uniqueoverhangs; separate additional2020sidewaysarrays from partially reproduced2019paper.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining12B0016inputs; next10.1021/acsnano.9b05746.','ReviewMarras2015/Le2016parent sourcevariants and remaining thesis/journal content; source recipes remain unverified.','Continue priorityauthor histories/backward-forward reconciliation; FNANO deferred.']);L.upsert('batches',b,'Saveparentfollowup without incrementing firstpass count');print(L.validate())
if __name__=='__main__':main()
