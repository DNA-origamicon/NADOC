"""Retain verified metrics, then optionally prune only this owned research tree."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
import shutil
import time


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def retain(source,dest,prune=False):
    source=Path(source).resolve(strict=True);dest=Path(dest).resolve(strict=True)
    if source.name!='equilibrium-tm-20261121' or dest.is_relative_to(source):
        raise ValueError('Refusing a different ownership boundary')
    if any(source.rglob('*.nadoc')) or any(source.rglob('*.nass')):
        raise ValueError('Unexpected molecular documents in scratch')
    started=time.monotonic();copied=[]
    def copy(p,d):
        d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
        assert digest(p)==digest(d)
        copied.append(str(d.relative_to(dest)))
    globals_keep=['dependencies.json','environment.json','calibration.json','validation.json','nearest_neighbor.json','historical_vmmc_roundtrips.json','control_command.json','confirmation_command.json','confirmation_analysis_timing.json','statistical_replay.json','worktree-inventory.txt']
    for name in globals_keep:
        if (source/name).exists():copy(source/name,dest/name)
    for p in sorted(source.iterdir()):
        if not p.is_dir() or not (p/'manifest.json').exists():continue
        target=dest/'campaigns'/p.name
        keep=['manifest.json','driver_source.py','result.json','events.jsonl','frozen_weights.txt','full_analysis.json','sufficient_statistics.npz','distance_audit.json','distance_samples.npz','binding_definition.json','pairing_audit/summary.json','pairing_audit/pairing_states.npz']
        for name in keep:
            if (p/name).exists():copy(p/name,target/name)
        for checkpoint in p.glob('checkpoint_*.json'):copy(checkpoint,target/checkpoint.name)
        stages=[]
        def stage_order(path):
            name=path.parent.name
            phase=0 if name.startswith('tune') else 1 if name.startswith('equil') else 2
            return phase,tuple(map(int,re.findall(r'\d+',name)))
        for e in sorted(p.glob('*/execution.json'),key=stage_order):
            d=e.parent;receipt=json.loads(e.read_text())
            assert receipt['input_sha256']==digest(d/'input.txt')
            stages.append(dict(name=d.name,execution=receipt,complete=(d/'complete.json').exists(),
                               input=(d/'input.txt').read_text(),weights=(d/'weights.txt').read_text(),
                               output_sha256={x.name:digest(x) for x in d.iterdir() if x.is_file() and x.name in ['native.log','energy.dat','trajectory.dat','last_conf.dat','last_hist.dat','traj_hist.dat']}))
        (target/'stages.json').write_text(json.dumps(stages,indent=2)+'\n')
    from tools.oxdna_tm_research.replay import replay
    checks=replay(dest/'campaigns')
    (dest/'retained_replay.json').write_text(json.dumps(checks,indent=2)+'\n')
    inventory=[dict(path=str(p.relative_to(source)),bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(source.rglob('*')) if p.is_file()]
    with gzip.open(dest/'raw_inventory.json.gz','wt') as f:json.dump(inventory,f)
    # Check only this owned tree; never stop or alter unrelated processes.
    references=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():continue
        paths=[process/'cwd']
        try:paths+=list((process/'fd').iterdir())
        except (OSError,PermissionError):pass
        for path in paths:
            try:linked=path.resolve(strict=True)
            except (OSError,RuntimeError):continue
            if linked==source or linked.is_relative_to(source):references.append(str(path))
        try:
            if str(source) in (process/'maps').read_text():references.append(str(process/'maps'))
        except (OSError,PermissionError):pass
    if references:raise RuntimeError(f'Owned data still referenced: {references}')
    result=dict(source=str(source),retained=str(dest),raw_files=len(inventory),raw_logical_bytes=sum(x['bytes'] for x in inventory),copied_files_verified=len(copied),statistical_replays_verified=len(checks),active_references=references,pruned=False,qualification='Original raw paths in manifests are historical after pruning. Existing source exports, managed jobs, prior experiments and installed engines are outside ownership boundary.')
    if prune:
        shutil.rmtree(source);assert not source.exists();result['pruned']=True
    result['retained_files']=sum(p.is_file() for p in dest.rglob('*'))
    result['retained_logical_bytes']=sum(p.stat().st_size for p in dest.rglob('*') if p.is_file())
    result['retention_seconds']=time.monotonic()-started
    (dest/'cleanup.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('dest');p.add_argument('--prune',action='store_true');a=p.parse_args();retain(a.source,a.dest,a.prune)
