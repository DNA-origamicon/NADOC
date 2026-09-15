from pathlib import Path
import hashlib,json,subprocess,datetime
root=Path(__file__).resolve().parent;repo=root.parents[1]
expected=json.loads((root/'input_hashes.json').read_text());checks={}
for path,ref in expected.items():
 p=repo/path;h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
 checks[path]={'size_matches':p.stat().st_size==ref['bytes'],'sha256_matches':h.hexdigest()==ref['sha256']}
diff=hashlib.sha256(subprocess.check_output(['git','diff','--binary'],cwd=repo)).hexdigest();out={'verified_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'application_tracked_diff_unchanged':diff==(root/'application_diff.sha256').read_text().strip(),'original_input_checks':checks};(root/'preservation_check.json').write_text(json.dumps(out,indent=2)+'\n')
assert out['application_tracked_diff_unchanged'] and all(all(v.values()) for v in checks.values())
print('Application tracked diff and',len(checks),'original input hashes unchanged.')
