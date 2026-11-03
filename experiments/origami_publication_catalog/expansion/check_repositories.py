from pathlib import Path
import requests,json,re,hashlib,time
O=Path('experiments/origami_publication_catalog/assets/sources/pre2020-expansion');D=O/'repositories';D.mkdir(exist_ok=True);records=json.loads((O/'screening.json').read_text());results=[]
for r in records:
 if not r.get('repository_links')or not r.get('sequence_evidence')or any('review'in t.lower()for t in r['publication_types']):continue
 if re.search('wireframe|free-form|Bioproduction',r['title'],re.I):continue
 for url in r['repository_links']:
  m=re.search(r'github.com/([^/]+/[^/#]+)',url)
  if not m:continue
  repo=m[1];entry={'doi':r['doi'],'repository':url,'files':[]}
  try:
   res=requests.get('https://api.github.com/repos/'+repo,timeout=20);res.raise_for_status();branch=res.json()['default_branch'];res=requests.get('https://api.github.com/repos/'+repo+'/git/trees/'+branch,params={'recursive':1},timeout=20);res.raise_for_status();tree=res.json();entry['tree_sha']=tree['sha'];entry['tree_truncated']=tree.get('truncated',False);entry['tree_paths']=[x['path']for x in tree.get('tree',[])if x['type']=='blob']
   for item in tree.get('tree',[]):
    path=item['path']
    if item['type']!='blob' or item.get('size',0)>5*1024*1024 or not re.search(r'\.(json|cdn|sc|csv|txt|xlsx)$',path,re.I)or re.search('brick|wireframe|icosahedron',path,re.I):continue
    u=f'https://raw.githubusercontent.com/{repo}/{tree["sha"]}/{path}';res=requests.get(u,timeout=20);res.raise_for_status();b=res.content;kind=None
    if path.endswith(('.json','.cdn','.sc')):
     try:
      obj=res.json()
      if isinstance(obj,dict) and (obj.get('vstrands')or obj.get('helices')and obj.get('strands')):kind='native_design'
     except ValueError:pass
    elif len(re.findall(rb'[ACGT]{16,}',b))>=20:kind='sequence_list_or_scaffold_sequence'
    if kind:
     dest=D/(repo.replace('/','__')+'__'+path.replace('/','__'));dest.write_bytes(b);entry['files'].append({'path':path,'kind':kind,'local_file':str(dest.relative_to(O.parents[1])),'url':u,'sha256':hashlib.sha256(b).hexdigest(),'variant_matching':'unverified; retained author source, not automatically a new eligible structure'})
   entry['status']='tree_checked'
  except Exception as e:entry['status']='access_failed';entry['error']=str(e)
  results.append(entry);print(repo,entry['status'],len(entry['files']),flush=True)
(O/'repository_audit.json').write_text(json.dumps(results,indent=2))
