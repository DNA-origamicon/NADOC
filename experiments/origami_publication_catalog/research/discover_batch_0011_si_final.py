"""Enumerate complete available reference lists; identity and relevance remain separate."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 pubs=L.read('publication_reviews');known={p['doi']:p['registry_key'] for p in pubs if p['doi']};sets=[]
 for doi,name,fid,page,n in [
 ('10.1021/acssensors.7b00628','9972970-se7b00628_si_001.pdf','9972970',12,8),
 ('10.1021/acsnano.7b08044','10301766-nn7b08044_si_001.pdf','10301766',7,11)]:
  path=L.ROOT/'assets/sources/acs-expansion-20261104'/name
  txt=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f')[page-1]
  if fid=='10301766':
   txt=txt.split('SI REFERENCES',1)[1].split('SUPPORTING FIGURES',1)[0]
   pattern=r'^\s*(\d+)\.[ \t]+(?=[A-Z])'
  else: pattern=r'^\s*\((\d+)\)\s+'
  matches=list(re.finditer(pattern,txt,re.M))
  assert [int(m[1]) for m in matches]==list(range(1,n+1))
  refs=[]
  for i,m in enumerate(matches):
   raw=txt[m.start():matches[i+1].start() if i+1<len(matches) else len(txt)]
   raw=re.sub(r'^\s*S\d+\s*$','',raw,flags=re.M)
   refs.append((int(m[1]),' '.join(raw.split())))
  sets.append((doi,path,'https://ndownloader.figshare.com/files/'+fid,refs))
 total=0;targets=set();evs=[];audit=[]
 for doi,path,url,refs in sets:
  ev=evidence(path,url,'Complete reference list; raw entries retained without title filtering');evs.append(ev)
  for number,raw in refs:
   ds=re.findall(r'10\.\d{4,9}/[^\s†【】]+',raw);d=ds[0].rstrip('.,;').lower() if ds else ''
   target=known.get(d,d or f'reference:{doi}:si:{number}')
   L.upsert('discovery_edges',dict(edge_id=f'cites:{doi}:si-ref{number}',source_key=doi,target_key=target,relation='cites',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=f'Supplement reference {number}',target_doi=d,raw_reference=raw,reconciliation_state='matched_registry_doi' if d in known else 'pending_identity_and_scope',run_id='backward-B0011-si-final',date=L.DATE),'Enumerate every available source reference, independent of relevance')
   total+=1;targets.add(target)
  audit.append({'source':doi,'expected':len(refs),'saved':sum(e['source_key']==doi and e.get('run_id')=='backward-B0011-si-final' for e in L.read('discovery_edges'))})
 L.upsert('discovery_runs',dict(run_id='backward-B0011-si-final',route='backward_citations',query_or_seed=[x[0] for x in sets],source_url='Primary PDF/publisher web renderings',date=L.DATE,pagination={'method':'numbered reference lists, asserted contiguous and complete','complete':True},provider_total=total,retrieved_count=total,unique_targets=len(targets),evidence=evs,failures=[],closure_state='exhausted',closure_scope='Only two supplement reference lists; main and remaining supplement bibliographies not yet enumerated; recursive identity/scope review pending',checkpoint='Resolve raw references/DOIs; enumerate other B0011 bibliographies'),'Complete bounded list enumeration, not bibliographic discovery')
 out={'sources':audit,'total_references':total,'unique_targets':len(targets),'validation':L.validate()}
 L.atomic(L.HERE/'batch_0011_si_final_reference_audit.json',json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
