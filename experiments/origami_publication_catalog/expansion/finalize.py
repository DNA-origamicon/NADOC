"""Export audit inventories and validate the research map's local references."""
import json,csv,hashlib,re
from pathlib import Path
from urllib.parse import urlsplit,unquote
from html.parser import HTMLParser
H=Path(__file__).resolve().parents[1];A=H/'assets';O=A/'sources/pre2020-expansion'
def read(p):return json.loads(p.read_text())
def csvout(name,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with(H/name).open('w',newline='')as f:
  w=csv.DictWriter(f,keys);w.writeheader();w.writerows({k:json.dumps(v)if isinstance(v,(list,dict))else v for k,v in r.items()}for r in rows)
repo=read(O/'repository_audit.json');fs=[]
for r in repo:
 for f in r.get('files',[]):fs.append(dict(doi=r['doi'],repository=r['repository'],**f))
csvout('expansion_repository_files.csv',fs)
registry=read(H/'publication_registry.json');gaps=[r for r in registry if r['priority']=='sequence_evidence_to_review'or r['review_status'].startswith('named_structure_candidate')]
csvout('priority_review_gaps.csv',gaps)
# Hash all retrieved evidence referenced by the new map and repository audit.
manifest={}
for r in read(H/'structure_map.json')['rows']:
 for f in r.get('publication_supplements',[])+r.get('design_files',[]):
  if isinstance(f,str):f={'local_file':f}
  if not f.get('local_file'):continue
  p=A/f['local_file'];assert p.is_file(),p
  h=hashlib.sha256(p.read_bytes()).hexdigest()
  if f.get('sha256'):assert h==f['sha256'],p
  manifest[f['local_file']]=dict(local_file=f['local_file'],bytes=p.stat().st_size,sha256=h)
for f in fs:
 p=A/f['local_file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256'],p
manifest=list(manifest.values());(H/'expansion_assets_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
class Links(HTMLParser):
 def __init__(self):super().__init__();self.paths=[]
 def handle_starttag(self,tag,attrs):
  for k,v in attrs:
   if k in ('href','src')and v and not urlsplit(v).scheme and not v.startswith('#'):self.paths.append(v.split('#')[0])
for name in ['structure_map.html','publication_registry.html']:
 parser=Links();parser.feed((H/name).read_text())
 for path in parser.paths:assert (H/unquote(path)).exists(),(name,path)
rows=read(H/'structure_map.json')['rows'];assert len({r['id']for r in rows})==len(rows)
for r in rows:
 assert r['first_publication_date']<'2020-01-01',r['id']
 if not r.get('image_file'):assert r['quality_score']is None
assert not Path('workspace/Image_Recovery_First5_20261102').exists()
assert read(H/'recovery/PAUSED.json')['status']=='paused_by_user'
result=dict(structure_groups=len(rows),registry_records=len(registry),priority_review_records=len(gaps),hashed_referenced_files=len(manifest),repository_files_verified=len(fs),html_local_links='all_exist',cutoff_and_unique_ids='passed',missing_image_scores='null',recovery_workspace='deleted',recovery_status='paused')
(H/'expansion_validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
