"""Enumerate complete available reference lists; identity and relevance remain separate."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 pubs=L.read('publication_reviews');known={p['doi']:p['registry_key'] for p in pubs if p['doi']};sets=[]
 path=L.ROOT/'assets/research-20261105/shi-2013-review.pdf'
 txt=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode()
 txt=txt.split('参考文献',1)[1].split('Recent progress in DNA origami',1)[0]
 matches=list(re.finditer(r'^\s*(\d{1,2})\s+([A-Z][^\n]+)',txt,re.M))
 assert [int(m[1]) for m in matches]==list(range(1,91))
 refs=[]
 for i,m in enumerate(matches):
  raw=txt[m.start():matches[i+1].start() if i+1<len(matches) else len(txt)]
  raw=re.sub(r'^\s*\d{4}\s*$','',raw,flags=re.M)
  refs.append((int(m[1]),' '.join(raw.split())))
 sets.append(('10.1360/972012-1626',path,'https://www.sciengine.com/parse/pdf/0023-074X/dwcXJEJ7f3k22FtWR.pdf',refs))
 for doi,name,start,end,pattern,n,url in [
 ('10.1515/nanoph-2013-0011','batch_0010_rotation_more.json','L238: ## References','L265:',r'^L\d+: \[(\d+)\] (.+)$',22,'https://www.degruyterbrill.com/document/doi/10.1515/nanoph-2013-0011/html'),
 ('10.1140/epje/i2013-13101-5','batch_0010_rotation_primary.json','L91: ## References','L182:',r'^L\d+:\s+(\d+)\. (.+)$',49,'https://link.springer.com/article/10.1140/epje/i2013-13101-5')]:
  path=L.HERE/name;txt=json.loads(path.read_text()).split(start,1)[1].split(end,1)[0]
  refs=[(int(m[1]),m[2]) for m in re.finditer(pattern,txt,re.M)]
  assert [x[0] for x in refs]==list(range(1,n+1)),(doi,len(refs))
  sets.append((doi,path,url,refs))
 path=L.ROOT/'assets/research-20261105/endo-2013-review.pdf'
 txt=subprocess.check_output(['pdftotext','-raw',str(path),'-']).decode().split('文 献',1)[1]
 matches=list(re.finditer(r'^(\d{1,2})\) ',txt,re.M))
 assert [int(m[1]) for m in matches]==list(range(1,17))
 refs=[(int(m[1]),' '.join(txt[m.start():matches[i+1].start() if i+1<len(matches) else len(txt)].split())) for i,m in enumerate(matches)]
 sets.append(('10.2142/biophys.53.153',path,'https://www.jstage.jst.go.jp/article/biophys/53/3/53_153/_pdf/-char/en',refs))
 total=0;targets=set();evs=[];audit=[]
 for doi,path,url,refs in sets:
  ev=evidence(path,url,'Complete reference list; raw entries retained without title filtering');evs.append(ev)
  for number,raw in refs:
   ds=re.findall(r'10\.\d{4,9}/[^\s†【】]+',raw);d=ds[0].rstrip('.,;').lower() if ds else ''
   target=known.get(d,d or f'reference:{doi}:{number}')
   L.upsert('discovery_edges',dict(edge_id=f'cites:{doi}:ref{number}',source_key=doi,target_key=target,relation='cites',evidence_url=url,local_file=ev['local_file'],sha256=ev['sha256'],locator=f'Reference {number}',target_doi=d,raw_reference=raw,reconciliation_state='matched_registry_doi' if d in known else 'pending_identity_and_scope',run_id='backward-B0010-rotation',date=L.DATE),'Enumerate every available source reference, independent of relevance')
   total+=1;targets.add(target)
  audit.append({'source':doi,'expected':len(refs),'saved':sum(e['source_key']==doi and e.get('run_id')=='backward-B0010-rotation' for e in L.read('discovery_edges'))})
 L.upsert('discovery_runs',dict(run_id='backward-B0010-rotation',route='backward_citations',query_or_seed=[x[0] for x in sets],source_url='Primary PDF/publisher web renderings',date=L.DATE,pagination={'method':'numbered reference lists, asserted contiguous and complete','complete':True},provider_total=total,retrieved_count=total,unique_targets=len(targets),evidence=evs,failures=[],closure_state='exhausted',closure_scope='Only four accessible reference lists; remaining source bibliographies not yet enumerated; recursive identity/scope review pending',checkpoint='Resolve raw references/DOIs; enumerate other B0010 bibliographies'),'Complete bounded list enumeration, not bibliographic discovery')
 out={'sources':audit,'total_references':total,'unique_targets':len(targets),'validation':L.validate()}
 L.atomic(L.HERE/'batch_0010_rotation_reference_audit.json',json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
