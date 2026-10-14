"""Standalone local restart runner: verify immutable inputs, never overwrite a run."""
import argparse,hashlib,json,math,os,signal,subprocess,time
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def verify(root):
    manifest=json.loads((root/'manifest.json').read_text())
    for rel,expected in manifest['files'].items():
        p=root/rel
        if not p.is_file() or digest(p)!=expected:raise ValueError(f'Input hash mismatch: {rel}')
    return manifest

def run(root,case,output,namd,steps):
    if not 0<=steps<=500000 or steps%5000:raise ValueError('Use0 for static check,or at most1ns in10ps increments; audit before another chunk')
    manifest=verify(root);state=manifest['states'][case]
    if any(c in str(root) for c in '{}\n\r'):raise ValueError('Package path contains unsupported Tcl delimiter')
    template=root/'templates'/f'{case}.{"probe" if steps==0 else "continue"}.conf'
    cfg=template.read_text().replace('@ROOT@',str(root)).replace('@STEPS@',str(steps))
    output.mkdir(parents=True,exist_ok=False);(output/'run.conf').write_text(cfg)
    command=[str(namd.resolve()),'+p4','+setcpuaffinity','+devices','0','run.conf']
    receipt=dict(started_at=time.time(),case=case,steps=steps,hard_seconds=7200,command=command,simulation_ready=False,minimum_certified=False,scientific_review_required=True)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2))
    with (output/'run.log').open('w') as log:
        p=subprocess.Popen(command,cwd=output,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:code=p.wait(timeout=7200)
        except BaseException:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            receipt.update(finished_at=time.time(),returncode=p.returncode,passed=False)
            (output/'receipt.json').write_text(json.dumps(receipt,indent=2));raise
    lines=(output/'run.log').read_text().splitlines();headers=next((l.split()[1:] for l in lines if l.startswith('ETITLE:')),[])
    rows=[dict(zip(headers,map(float,l.split()[1:]))) for l in lines if l.startswith('ENERGY:')]
    limit=max(.01,1e-6*abs(state['potential_kcal']))
    passed=bool(code==0 and rows and any('End of program' in l for l in lines) and all(math.isfinite(v) for r in rows for v in r.values()) and rows[0]['TS']==5530000 and rows[-1]['TS']==5530000+steps and abs(rows[0]['POTENTIAL']-state['potential_kcal'])<=limit)
    receipt.update(finished_at=time.time(),returncode=code,passed=passed,restart_energy_error_kcal=abs(rows[0]['POTENTIAL']-state['potential_kcal']) if rows else None,energy_limit_kcal=limit,scope='Static restart energy check' if steps==0 else 'Native completion and initial energy only; full geometry/cell/solvent/structural audit required before continuation')
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2))
    if not passed:raise RuntimeError('Native restart check failed; preserve outputs and investigate')
    print(json.dumps(receipt))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');p.add_argument('--case');p.add_argument('--output',type=Path);p.add_argument('--namd',type=Path);p.add_argument('--steps',type=int,default=0);a=p.parse_args();root=Path(__file__).resolve().parent
    if a.verify_only:verify(root);print('Package hashes verified')
    else:
        if not all([a.case,a.output,a.namd]):p.error('--case,--output and --namd required')
        run(root,a.case,a.output.resolve(),a.namd,a.steps)
