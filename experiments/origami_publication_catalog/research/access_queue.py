"""Local human handoff for research access; no credentials, cookies or browser sessions.
Single writer, like the research ledgers. Acquisition never implies scientific review.
"""
import argparse
from datetime import datetime, timezone
import hashlib, html, io, json, os, re, tempfile, zipfile
from pathlib import Path
from urllib.parse import urlsplit
import ledger as L
QUEUE=L.HERE/'access_requests.json'
ASSETS=L.ROOT/'assets/human-assisted'
PAGE=L.HERE/'ACCESS_REQUESTS.html'

def now():return datetime.now(timezone.utc).isoformat()
def read():return json.loads(QUEUE.read_text()) if QUEUE.exists() else []
def save(rows):L.atomic(QUEUE,json.dumps(rows,indent=2)+'\n');render(rows)
def public_url(url):
 p=urlsplit(url)
 if p.scheme not in ('http','https') or not p.netloc or p.username or p.password or p.query or p.fragment:
  raise ValueError('Use a stable public URL without credentials, query parameters or fragments.')
 return url

def request(doi,url,reason,attempts,kind='download'):
 url=public_url(url)
 if not attempts:raise ValueError('Document attempted automatic routes before requesting help.')
 rid='ACCESS-'+hashlib.sha256((doi+'|'+url+'|'+kind).encode()).hexdigest()[:10]
 rows=read();old=next((r for r in rows if r['id']==rid),None)
 if old:return old
 row=dict(id=rid,doi=doi,url=url,kind=kind,reason=reason,automatic_attempts=attempts,status='needs_user',created=now(),events=[])
 rows.append(row);save(rows);return row

def payload(path):
 if path.stat().st_size>100*1024**2:raise ValueError('File exceeds100MiB; inspect separately.')
 data=path.read_bytes();suffix=path.suffix.lower()
 if suffix=='.pdf':
  if b'%PDF-' not in data[:1024]:raise ValueError('Not a PDF; may be an access challenge.')
 elif suffix in ('.zip','.xlsx'):
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   if sum(x.file_size for x in z.infolist())>500*1024**2:raise ValueError('Expanded archive exceeds500MiB; inspect separately.')
   if z.testzip():raise ValueError('Corrupt ZIP member')
   if suffix=='.xlsx' and '[Content_Types].xml' not in z.namelist():raise ValueError('Not an XLSX package')
 else:raise ValueError('Supported handoff files: PDF, ZIP, XLSX. Other formats require explicit inspection.')
 return data,suffix

def ingest(rid,path):
 rows=read();row=next(r for r in rows if r['id']==rid)
 if row['kind']!='download':raise ValueError('This request expects an answer, not a file.')
 data,suffix=payload(Path(path));digest=hashlib.sha256(data).hexdigest()
 if row['status']=='received':
  if row['file']['sha256']!=digest:raise ValueError('Different file already received; preserve original and request a separate resource.')
  dest=L.ROOT/row['file']['local_file']
  if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise ValueError('Stored file missing or modified.')
  return row
 dest=ASSETS/(rid+'-'+digest[:12]+suffix);dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.exists():
  if dest.read_bytes()!=data:raise ValueError('Destination conflict')
 else:
  fd,tmp=tempfile.mkstemp(prefix=rid,dir=dest.parent)
  try:
   with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
   os.replace(tmp,dest)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 row.update(status='received',file=dict(local_file=str(dest.relative_to(L.ROOT)),sha256=digest,bytes=len(data),source_url=row['url'],review_status='identity_and_contents_not_verified'))
 row['events'].append(dict(at=now(),action='file_received; agent verification required'));save(rows);return row

def answer(rid,text):
 rows=read();row=next(r for r in rows if r['id']==rid)
 if row['kind']!='question':raise ValueError('This request expects a file.')
 if not text.strip():raise ValueError('Empty answer')
 if row['status']=='answered':raise ValueError('Answer already saved; do not overwrite history.')
 row.update(status='answered',answer=text);row['events'].append(dict(at=now(),action='answer_received'));save(rows);return row

def render(rows):
 esc=html.escape;cards=[]
 for r in rows:
  instruction=('Download in your normal browser. Save as '+r['id']+'.pdf (or .zip/.xlsx) in your Downloads folder. Tell the agent it is ready; no upload or credential sharing is needed.' if r['kind']=='download' else 'Reply in chat with this request ID and your answer. Do not include credentials.')
  cards.append('<article><h2>'+esc(r['id'])+' — '+esc(r['status'])+'</h2><p>'+esc(r['doi'])+'</p><p>'+esc(r['reason'])+'</p><a target="_blank" rel="noreferrer" href="'+esc(r['url'],quote=True)+'">Open resource in your browser</a><p>'+esc(instruction)+'</p><details><summary>Automatic attempts</summary><ul>'+''.join('<li>'+esc(a)+'</li>' for a in r['automatic_attempts'])+'</ul></details></article>')
 L.atomic(PAGE,'<!doctype html><meta charset="utf-8"><title>Research access requests</title><style>body{font:17px system-ui;max-width:850px;margin:3em auto;padding:0 1em}article{border:1px solid #bbb;padding:1em;margin:1em 0}h2{font-size:1.1em}</style><h1>Research access requests</h1><p>Use your usual CU-connected browser. Authentication stays there. Never send passwords, cookies or tokens.</p>'+(''.join(cards) if cards else '<p>No human action needed. Research continues automatically.</p>'))

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
 sub.add_parser('list');sub.add_parser('render')
 a=sub.add_parser('request');a.add_argument('--doi',required=True);a.add_argument('--url',required=True);a.add_argument('--reason',required=True);a.add_argument('--attempt',action='append',required=True);a.add_argument('--kind',choices=['download','question'],default='download')
 a=sub.add_parser('ingest');a.add_argument('id');a.add_argument('path',type=Path)
 a=sub.add_parser('answer');a.add_argument('id');a.add_argument('text')
 a=sub.add_parser('collect');a.add_argument('directory',type=Path)
 args=p.parse_args()
 if args.cmd=='request':print(json.dumps(request(args.doi,args.url,args.reason,args.attempt,args.kind),indent=2))
 elif args.cmd=='ingest':print(json.dumps(ingest(args.id,args.path),indent=2))
 elif args.cmd=='answer':print(json.dumps(answer(args.id,args.text),indent=2))
 elif args.cmd=='collect':
  for r in read():
   if r['status']=='needs_user' and r['kind']=='download':
    files=[f for f in args.directory.glob(r['id']+'.*') if f.is_file() and f.suffix.lower() in ('.pdf','.zip','.xlsx')]
    if len(files)>1:print(r['id']+': multiple files; specify ingest path explicitly')
    elif files:print(json.dumps(ingest(r['id'],files[0]),indent=2))
 elif args.cmd=='render':
  if not QUEUE.exists():save([])
  else:render(read())
  print(PAGE)
 else:print(json.dumps(read(),indent=2))
if __name__=='__main__':main()
