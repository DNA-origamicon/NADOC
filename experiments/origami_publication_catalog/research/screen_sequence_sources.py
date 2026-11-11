"""Rapid supplement index; flags candidates, never automatically excludes scientific relevance."""
import sys,json,re,subprocess,hashlib
from pathlib import Path

import ledger as L
import argparse,time
parser=argparse.ArgumentParser();parser.add_argument('--keys',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
keys=json.loads(args.keys.read_text());allrows={r['registry_key']:r for r in L.read('publication_reviews')};rs=[allrows[k] for k in keys];started=time.monotonic()
results=[]
for r in rs:
 fs=[];seen=set()
 for s in r['legacy_record']['downloaded_supplements']:
  if not s['local_file'].endswith('.pdf'):continue
  p=L.ROOT/'assets'/s['local_file']; h=hashlib.sha256(p.read_bytes()).hexdigest()
  if h in seen:continue
  seen.add(h);v=subprocess.run(['pdftotext','-layout',str(p),'-'],capture_output=True);t=v.stdout.decode(errors='replace');pages=t.split('\f')
  seq=[]
  for i,pg in enumerate(pages,1):
   for line in pg.split('\n'):
    for m in re.finditer(r'(?<![A-Za-z])(?:[ACGT]{2,}[ \t]*){1,}(?![A-Za-z])',line):
     x=re.sub(r'\s','',m.group())
     if len(x)>=18:seq.append({'page':i,'sequence':x,'line':line.strip()})
  hits=[(i,line.strip()) for i,pg in enumerate(pages,1) for line in pg.split('\n') if re.search(r'staple|sequence|oligonucleotide',line,re.I)]
  fs.append(dict(local_file=str(p.relative_to(L.ROOT)),sha256=h,url=s.get('url'),count=len(seq),unique=len(set(x['sequence'] for x in seq)),entries=seq,hits=hits,parser_returncode=v.returncode,parser_warnings=v.stderr.decode(errors='replace')))

 results.append(dict(key=r['registry_key'],title=r['legacy_record']['publication'],files=fs))
 print(r['registry_key'],r['legacy_record']['publication'])
 for f in fs:print('count',f['count'],'unique',f['unique'],'hits',f['hits'][:5],'sample',f['entries'][:1])
L.atomic(args.output,json.dumps({'records':results,'extraction_seconds':time.monotonic()-started,'method':'Candidate ACGT runs >=18nt, whitespace joined within a line; count is NOT strand count. Human table-region review required; scaffold runs, repeated controls, image tables, lowercase bases and modified bases need checking.'},indent=2)+'\n')
