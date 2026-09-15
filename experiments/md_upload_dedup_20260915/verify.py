"""Rebuild only anchor composition in an isolated copy; compare every stage's inputs."""
import hashlib,json,pathlib,shutil,tempfile,time
from backend.api.routes_md import _harmonicize_seed_anchors
from backend.core.md_executor import stage_plan,_bundle_setup_files
source=pathlib.Path('workspace/md_jobs/75af92defc27/package/cube_pore_namd_solvated').resolve()
root=pathlib.Path(__file__).resolve().parent

def field(path,key):
    return next(line.split()[1] for line in path.read_text().splitlines() if line.startswith(key))
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(4*1024*1024),b''):h.update(data)
    return h.hexdigest()
with tempfile.TemporaryDirectory(prefix='nadoc-dedup-check-') as tmp:
    p=pathlib.Path(tmp)/'package';p.mkdir()
    for f,relative in stage_plan(source):
        if f.name.startswith('restraints_combined_'):continue
        target=p/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if f.suffix=='.conf' or f.name=='manifest.json':shutil.copyfile(f,target)
        else:target.symlink_to(f)
    before={c.name:(field(c,'consref'),digest(source/field(c,'conskfile'))) for c in source.glob('*.conf')}
    started=time.monotonic()
    _harmonicize_seed_anchors(p,name_stem='cube_pore')
    elapsed=time.monotonic()-started
    for c in p.glob('*.conf'):
        ref,expected=before[c.name]
        assert field(c,'consref')==ref
        assert digest(p/field(c,'conskfile'))==expected,c.name
    original_plan=stage_plan(source);new_plan=stage_plan(p)
    small=[(f,rel) for f,rel in new_plan if f.stat().st_size<=1024*1024]
    archive=pathlib.Path(tmp)/'setup.tar';_bundle_setup_files(small,archive,gpu=True)
    result={'job_template':'75af92defc27','stage_configs_verified':len(before),
            'original_combined_files':len(list(source.glob('restraints_combined_*.pdb'))),
            'new_combined_files':len(list(p.glob('restraints_combined_*.pdb'))),
            'original_package_bytes':sum(f.stat().st_size for f,_ in original_plan),
            'new_package_bytes':sum(f.stat().st_size for f,_ in new_plan),
            'original_uploads':len(original_plan),'new_uploads':len(new_plan)-len(small)+1,
            'small_files_bundled':len(small),'bundle_bytes':archive.stat().st_size,
            'composition_seconds':elapsed}
    print(json.dumps(result,indent=2));(root/'results.json').write_text(json.dumps(result,indent=2)+'\n')
