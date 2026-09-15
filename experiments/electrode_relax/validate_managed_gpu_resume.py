"""Bounded native proof of the ordinary resume writer's GPU initializer ordering."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from backend.core.namd_runner import _write_resume_conf


def main():
    p=argparse.ArgumentParser()
    for key in ('package','output','binary'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();src=a.package.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    m=json.loads((src/'manifest.json').read_text());last=m['segments'][-1];name='managed_gpu_resume_probe'
    for path in src.iterdir():
        if path.name=='output' or path.suffix in ('.log','.conf'):continue
        (out/path.name).symlink_to(path.resolve())
    (out/'output').mkdir()
    for ext in ('coor','vel','xsc'):
        shutil.copy2(src/'output'/f"{last['name']}.restart.{ext}",out/'output'/f'{name}.restart.{ext}')
    (out/f'{name}.conf').write_text((src/f"{last['name']}.conf").read_text().replace(last['name'],name))
    stem=_write_resume_conf(out,out/'output',name,last['steps'],last['steps']+20)
    with (out/'resume.log').open('w') as f:
        r=subprocess.run([str(a.binary.resolve()),'+p1','+devices','0',stem+'.conf'],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=60)
    text=(out/'resume.log').read_text()
    assert r.returncode==0 and 'End of program' in text
    final_step=int((out/'output'/f'{name}.xsc').read_text().splitlines()[-1].split()[0])
    assert final_step==last['steps']+20
    result=dict(passed=True,start_step=last['steps'],end_step=final_step,timestep_fs=last['timestep_fs'],
                config=stem+'.conf',scope='20 native steps from a real checkpoint using NADOC resume writer')
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(result)


if __name__=='__main__':main()
