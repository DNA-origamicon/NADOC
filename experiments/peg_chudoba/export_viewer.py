"""Export completed 294 K validation trajectories for the read-only Help viewer.

No engine execution. Source trajectories remain untouched. Regenerate after
new completed cohorts are added to campaign_comparison/validation.json.
"""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT/'frontend/public/peg-trajectories'
REPORT = ROOT/'workspace/peg_chudoba/scheduling_294_20260910/validation.json'


def read(path):
    return json.loads(path.read_text())


def sample_trajectory(path, n, chains, limit):
    """Read actual saved frames; unwrap bonds, retaining periodic chain placement."""
    particles = n*chains
    offsets = []
    with path.open('rb') as stream:
        while True:
            offset = stream.tell()
            header = stream.readline()
            if not header:
                break
            if not header.startswith(b't ='):
                raise ValueError(f'Invalid trajectory header: {path}')
            for _ in range(particles+2):
                if not stream.readline():
                    raise ValueError(f'Incomplete saved frame: {path}')
            offsets.append(offset)
        if not offsets:
            raise ValueError(f'Empty trajectory: {path}')
        indices = np.unique(np.linspace(0, len(offsets)-1, min(limit, len(offsets)), dtype=int))
        frames, steps, boxes, radii = [], [], [], []
        for index in indices:
            stream.seek(offsets[index])
            steps.append(int(stream.readline().split(b'=')[1]))
            box = np.fromstring(stream.readline().split(b'=')[1], sep=' ')*.8518
            stream.readline()
            xyz = np.array([np.fromstring(stream.readline().decode(), sep=' ')[:3] for _ in range(particles)])*.8518
            xyz = xyz.reshape(chains,n,3)
            bonds = np.diff(xyz,axis=1)
            bonds -= box*np.rint(bonds/box)
            xyz = np.concatenate([xyz[:,:1],xyz[:,:1]+np.cumsum(bonds,axis=1)],axis=1)
            centers = xyz.mean(axis=1,keepdims=True)
            radii.append(float(np.sqrt(np.mean(np.sum((xyz-centers)**2,axis=2)))))
            xyz = xyz-centers if chains==1 else xyz-box*np.floor(centers/box)-box/2
            if not np.isfinite(xyz).all():
                raise ValueError('Nonfinite coordinates')
            frames.append(xyz.reshape(-1,3));boxes.append(box.tolist())
    return np.asarray(frames,dtype='<f4'),steps,boxes,radii,len(offsets)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report=read(REPORT)
    candidates=[]
    for row in read(HERE/'campaign_comparison.json')['comparisons']:
        if row['cutoff']=='zero_tail' and row['temperature_K']==294:
            verdict=next((r for r in report['chains'] if r['n']==row['n']),{})
            candidates.extend((Path(d),'CPU chain',verdict.get('passed',False)) for d in row['directories'])
    for row in report['gpu'].values():
        candidates.extend((Path(d),'GPU chain',row['passed']) for d in row['directories'])
    for row in report['eos'].values():
        candidates.extend((Path(d),'Bulk solution',row['passed']) for d in row['directories'])
    entries=[]; seen=set()
    for directory,kind,passed in candidates:
        directory=directory.resolve()
        if directory in seen:
            continue
        seen.add(directory)
        meta=read(directory/'run.json')
        if meta['status']!='completed':
            continue
        n=meta['n'];chains=meta.get('chains',1)
        trajectory=directory/'trajectory.dat'
        if not trajectory.exists():
            continue
        source_hash=hashlib.sha256((directory/'run.json').read_bytes()).hexdigest()
        identity=hashlib.sha256(str(directory).encode()).hexdigest()[:16]
        filename=f'{identity}-{source_hash[:10]}.f32'
        frames,steps,boxes,radii,total=sample_trajectory(trajectory,n,chains,32 if chains>1 else 160)
        (OUT/filename).write_bytes(frames.tobytes())
        replica=meta.get('replica_id',meta['seed'])
        detail=f"{meta['pressure_kpa']:g} kPa" if chains>1 else (f"{meta['dt_fs']:g} fs" if meta['sampling']=='md' else 'pivot MC')
        entries.append(dict(id=identity,n=n,chains=chains,particles=n*chains,kind=kind,
            label=f'{kind} · {detail} · replica {replica}',replica=replica,
            temperature=meta['temperature'],sampling=meta['sampling'],dtFs=meta.get('dt_fs'),
            pressureKpa=meta.get('pressure_kpa'),completed=True,validationPassed=bool(passed),
            validationScope='294 K bulk zero-tail benchmark; cohort verdict, not a trajectory-frame verdict',
            source=str(directory),sourceMetadataSha256=source_hash,
            url=f'/peg-trajectories/{filename}',frames=len(frames),steps=steps,boxes=boxes,
            rmsRgNm=radii,availableFrames=total,
            radiusNm=float(np.linalg.norm(frames,axis=2).max()),
            coordinates='nm; whole chains; single-chain center removed; bulk chain centers wrapped into centered periodic box'))
        print(f'N{n}: {entries[-1]["label"]} ({len(frames)} of {total} frames)',flush=True)
    entries.sort(key=lambda e:(e['n'],{'GPU chain':0,'CPU chain':1,'Bulk solution':2}[e['kind']],e.get('dtFs') or 0,e.get('pressureKpa') or 0,e['replica']))
    manifest=dict(version=1,generatedUnix=time.time(),entries=entries,
                  description='Completed allocations from current 294 K validation cohorts; display frames are subsampled, not interpolated.')
    temporary=OUT/'manifest.tmp'
    temporary.write_text(json.dumps(manifest,separators=(',',':'),allow_nan=False)+'\n')
    temporary.replace(OUT/'manifest.json')
    print(f'Exported {len(entries)} completed trajectories to {OUT}')


if __name__=='__main__':
    main()
