"""Preserve a supported candidate relation without merging publication identities."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 pubs=L.read('publication_reviews');target=next(p for p in pubs if p['registry_key']=='10.1021/nn203161y')
 source=next(p for p in pubs if p.get('run_id')=='fnano-2012' and p.get('authors')==['Verena Schüller'])
 ev=evidence(L.HERE/'fnano2012_counterpart_search.json','https://pubmed.ncbi.nlm.nih.gov/22092186/','Primary indexed article author list/abstract/DOI; publisher dated November17 versus PubMed Epub November23,2011')
 note='All eight program authors match the journal group, and CpG origami immunostimulation agrees. Article abstract specifies hollow30helix tubes with up to62CpG sequences. Exact presentation results overlap remains unverified; no identity merge. Publisher November17 and PubMed November23 electronic dates disagree; issue December27,2011.'
 L.upsert('discovery_edges',dict(edge_id='fnano2012:counterpart:'+source['registry_key'],source_key=source['registry_key'],target_key=target['registry_key'],relation='possible_journal_counterpart',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=note,reconciliation_state='bibliographic_candidate_supported; exact_scope_identity_pending',run_id='fnano-2012',date=L.DATE),'Retain primary-supported counterpart candidate, distinct from identity confirmation')
 if ev not in source['evidence']:source['evidence'].append(ev)
 q='Candidate10.1021/nn203161y: '+note
 if q not in source['unresolved_questions']:source['unresolved_questions'].insert(0,q)
 L.upsert('publication_reviews',source,'Add inspectable counterpart evidence; preserve program uncertainty')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2012')
 if ev not in run['evidence']:run['evidence'].append(ev)
 run['checkpoint']+=' Counterpart search supports Schüller nn203161y candidate; ParMRC exact-title query yielded no supporting result, absence not established. Page7 image confirms missing dimensional numerals in printed titles.'
 L.upsert('discovery_runs',run,'Save counterpart search and source typography verification')
 audit=json.loads((L.HERE/'fnano2012_schedule_audit.json').read_text())
 audit['visual_followup']='Page7 rendered at1700px: missing numerals in Encapsulation of D DNA and D and D DNA Lattices are visible in source; p6 author continuation confirmed at p7 top.'
 audit['counterpart_candidate']='10.1021/nn203161y; full8author program group matches journal, exact scope pending'
 audit['validation']=L.validate();audit['counts']=L.counts()
 L.atomic(L.HERE/'fnano2012_schedule_audit.json',json.dumps(audit,indent=2)+'\n');print(audit['validation'])
if __name__=='__main__':main()
