"""Retain all references in two inspected primary bibliographies, without caps."""
import json
import ledger as L
from review_batch_0001 import evidence
from discover_positioner_references import References

def main():
 known={p['doi']:p['registry_key'] for p in L.read('publication_reviews') if p['doi']}
 audit=[]
 for label,doi,filename,url,total in [
  ('liu-fan-2013','10.1007/978-3-642-36077-0_10','liu-fan-2013-chapter.html','https://link.springer.com/chapter/10.1007/978-3-642-36077-0_10',73),
  ('jin-graphene-2013','10.1038/ncomms2690','shen-2013-graphene.html','https://www.nature.com/articles/ncomms2690',60)]:
  path=L.ROOT/'assets/research-20261105'/filename;p=References();p.feed(path.read_text())
  assert [r['number'] for r in p.rows]==list(range(1,total+1))
  assert all(r['text'] for r in p.rows)
  ev=evidence(path,url,'Complete primary References list ref-CR1 through ref-CR'+str(total));run='backward-'+label+'-20261105'
  matched=0
  for r in p.rows:
   target=known.get(r['dois'][0],r['dois'][0]) if len(r['dois'])==1 else 'reference:'+label+':'+str(r['number'])
   match=target in known.values();matched+=match
   L.upsert('discovery_edges',dict(edge_id=run+':'+str(r['number']),source_key=doi,target_key=target,relation='cites',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator='HTML#ref-CR'+str(r['number']),target_metadata=r,reconciliation_state='matched_explicit_doi; relevance_pending' if match else 'pending_identity_and_scope',run_id=run,date=L.DATE),'Enumerate bibliography including non-origami and pre2006 method leads; no relevance inference')
  L.atomic(L.HERE/(label+'_reference_inventory.json'),json.dumps(p.rows,indent=2,ensure_ascii=False)+'\n')
  L.upsert('discovery_runs',dict(run_id=run,route='backward_citations',query_or_seed=doi+' complete primary bibliography',source_url=url,date=L.DATE,pagination={'references':total,'first':1,'last':total,'all_enumerated':True},provider_total=total,retrieved_count=total,deduplicated_additions=total,additions_unit='Citation edges, not new publications or eligible works',evidence=[ev],failures=[],closure_state='exhausted',checkpoint='Only this source bibliography enumerated; unmatched identities, target relevance, recursion and forward routes remain open.'),'Record complete source-local enumeration, not census closure')
  saved=[e for e in L.read('discovery_edges') if e.get('run_id')==run];assert len(saved)==total
  audit.append({'run_id':run,'references_saved':total,'matched_existing_explicit_doi':matched,'unresolved_targets':total-matched,'last_reference':p.rows[-1]})
 L.atomic(L.HERE/'batch_0008_reference_audit.json',json.dumps({'sources':audit,'validation':L.validate()},indent=2)+'\n')
 print(audit)
if __name__=='__main__':main()
