"""Check saved input hashes, chemical definitions and source immutability."""
import json,hashlib,sys
from pathlib import Path
from collect import confread
from backend.core.md_job import MdJob
from backend.core.photoproduct_chemistry import chemical_definition_asset
O=Path(__file__).resolve().parent;R=json.loads((O/'results.json').read_text());J={j.job_id:j for j in MdJob.list_jobs(Path('workspace'))};out=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for r in R:
 j=J[r['job_id']];jd=j.job_dir(Path('workspace'));d=json.loads((jd/'job.json').read_text());pkg=jd/d['package_subdir'];cfg=pkg/(d['segments'][0]['name']+'.conf');p=pkg/'photoproduct_forcefield_manifest.json';assets=[]
 if p.exists():
  prod=json.loads(p.read_text());lesion=prod['lesions'][0]
  active=chemical_definition_asset(lesion['product'],lesion['stereochemistry'])
  packaged_definition=next(a for a in prod['assets'] if a['kind']=='chemical_definition')
  # cis-syn copies differ in serialization bytes, but the complete parsed definitions agree.
  assert json.loads(Path(active['path']).read_text())==json.loads((pkg/'forcefield'/packaged_definition['relative_path']).read_text())
  for a in json.loads(p.read_text())['assets']:
   f=pkg/'forcefield'/a['relative_path'];actual=sha(f);assert actual==a['sha256'],f
   current=Path('backend/data/forcefield')/a['relative_path']
   assets.append(dict(path=str(f),sha256=actual,matches_current=sha(current)==actual if current.exists() else None))
 for f in r['files']:
  s=Path(f['path']).stat();assert (s.st_size,s.st_mtime_ns)==(f['bytes'],f['mtime_ns'])
 out.append(dict(job_id=r['job_id'],design_sha256=sha(jd/'design.json'),config_sha256=sha(cfg),wc_plan_sha256=sha(Path(r['wc_plan'])),assets=assets,chemical_definition_semantic_match=True if p.exists() else None,chemical_definition_byte_match=(active['sha256']==packaged_definition['sha256']) if p.exists() else None,dcd_size_mtime_unchanged=True))
(O/'provenance_checks.json').write_text(json.dumps(out,indent=2)+'\n');print('Verified',len(out),'job source snapshots; packaged asset hashes and current-file comparisons recorded.')
