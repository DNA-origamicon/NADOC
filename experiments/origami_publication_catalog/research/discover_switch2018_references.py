"""Unfiltered reference extraction from the inspected switch SI."""
import re,subprocess,hashlib,json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acs.nanolett.8b00592';path=L.ROOT/'assets/sources/acs-expansion-20261104/10871972-nl8b00592_si_001.pdf'
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('SUPPORTING REFERENCES')[-1]
 matches=list(re.finditer(r'^\((\d+)\)\s+',text,re.M));assert [int(m[1]) for m in matches]==list(range(1,22))
 ev=evidence(path,'https://ndownloader.figshare.com/files/10871972','SIp19entire21item bibliography; no relevance filter')
 refs=[]
 for i,m in enumerate(matches):
  raw=' '.join(text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].split());raw=re.sub(r'\s+S19$','',raw);label=m[1];refs.append({'label':label,'raw':raw})
  L.upsert('discovery_edges',dict(edge_id='switch2018si:ref:'+label,source_key=key,target_key='pending-reference:'+hashlib.sha256(raw.encode()).hexdigest()[:16],relation='cites',raw_reference=raw,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SIp19reference'+label,reconciliation_state='identity_scope_pending',run_id='backward-switch2018-si',date=L.DATE),'Retain every SI reference without title-based eligibility filtering')
 L.upsert('discovery_runs',dict(run_id='backward-switch2018-si',route='backward_citations',query_or_seed=[key],source_url=ev['url'],date=L.DATE,pagination={'method':'complete numbered SI bibliography','complete':True},provider_total=21,retrieved_count=21,deduplicated_additions=21,additions_unit='Pending reference targets, not new publication decisions',evidence=[ev],failures=[],closure_state='exhausted',closure_scope='This SI reference extraction only; identity reconciliation and recursive discovery pending',checkpoint='Resolve design parents refs3/4 and all other21refs; main bibliography still open'),'Save bounded reference enumeration')
 L.atomic(L.HERE/'switch2018_reference_audit.json',json.dumps({'references':refs,'validation':L.validate()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
