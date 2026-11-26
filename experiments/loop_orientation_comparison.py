"""Isolated CG-only loop orientation A/B. Never imported by production code.

Requires a prior scoped user grant in the evidence record. No candidate NADOC,
atomistic model, simulation, production selector or placement change is emitted.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import BASE_DISPLACEMENT
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from experiments.recorded_review_process import Process
from scripts.agent_structure_guard import audit, publish

HALF = np.array([.15, .03, .35])  # Full's default 0.30 x 0.06 x 0.70 nm slab
BEAD_RADIUS = .10  # Full default, not an atomic van der Waals radius
EPS = 1e-9
LABEL = 'A/B diagnostic — not an authored design or approved production geometry.'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def slab_gap(center, matrix, centers, matrices):
    """Signed SAT separating gap for one box against N oriented boxes.

    Negative means visible box intersection; positive is a separating projection,
    not the exact Euclidean surface distance. Parallel cross axes are omitted.
    """
    n = len(centers)
    a = np.broadcast_to(matrix.T, (n, 3, 3))
    b = matrices.transpose(0, 2, 1)
    cross = np.cross(a[:, :, None, :], b[:, None, :, :]).reshape(n, 9, 3)
    axes = np.concatenate((a, b, cross), axis=1)
    lengths = np.linalg.norm(axes, axis=2)
    valid = lengths > 1e-10
    axes /= np.maximum(lengths[..., None], 1e-10)
    ra = np.abs(axes @ matrix) @ HALF
    rb = np.einsum('naj,njk->nak', axes, matrices)
    rb = np.abs(rb) @ HALF
    gap = np.abs(np.einsum('naj,nj->na', axes, centers-center)) - ra - rb
    return np.where(valid, gap, -np.inf).max(axis=1)


def bead_gap(center, matrix, beads):
    local = (beads-center) @ matrix
    return np.linalg.norm(np.maximum(np.abs(local)-HALF, 0), axis=1)-BEAD_RADIUS


def self_check():
    eye = np.eye(3)
    mats = np.array([eye, eye, Rotation.from_euler('z', 45, degrees=True).as_matrix()])
    gaps = slab_gap(np.zeros(3), eye, np.array([[0,0,0],[2,0,0],[0,0,0]]), mats)
    assert gaps[0] < 0 and gaps[1] > 0 and gaps[2] < 0
    np.testing.assert_allclose(bead_gap(np.zeros(3), eye, np.array([[0,0,0],[.25,0,0],[1,0,0]])), [-.1,0,.75], atol=1e-12)
    # Independent corner-projection SAT oracle for random box pairs.
    rng = np.random.default_rng(6125)
    corners = np.array(np.meshgrid(*[[-1,1]]*3)).T.reshape(-1,3)*HALF
    for _ in range(100):
        a, b = Rotation.random(2, random_state=rng).as_matrix()
        c = rng.uniform(-.8,.8,3)
        axes = [*a.T, *b.T, *np.cross(a.T[:,None,:], b.T[None,:,:]).reshape(-1,3)]
        values=[]
        for axis in axes:
            if np.linalg.norm(axis)<1e-10:
                continue
            axis=axis/np.linalg.norm(axis)
            pa=(corners@a.T)@axis
            pb=(corners@b.T+c)@axis
            values.append(max(pb.min()-pa.max(),pa.min()-pb.max()))
        np.testing.assert_allclose(slab_gap(np.zeros(3),a,c[None,:],b[None,:,:])[0],max(values),atol=1e-12)


def build_input(out, count, bp, direction):
    case = f'loop-{count}-{direction.lower()}-bp{bp}'
    path = out/'inputs'/f'{case}.nadoc'
    if path.exists():
        design = Design.model_validate_json(path.read_text())
    else:
        p=Process(case)
        p.append('bundle-create', {'_proof_version':1,'history_seed':str(UUID(int=281125)),
            'cells':[[0,0],[0,1]],'length_bp':84,'name':case,
            'lattice_type':'HONEYCOMB','ligate_adjacent':False}, 'F1: Create Bundle 1 [two helices, 84 bp]')
        host=p.design.helices[0].id
        s=next(s for s in p.design.strands if s.domains[0].helix_id==host and s.domains[0].direction.value==direction)
        p.append('strand-loop-set', {'_proof_version':1,'strand_id':s.id,'helix_id':host,
            'bp_index':bp,'direction':direction,'length':count,'aspect_ratio':3.,'rotation_deg':0.},
            f'F2: Add loop here 1 [{count} bases after bp {bp}]')
        publish(p.design,path)
        design=Design.model_validate_json(path.read_text())
    proof=audit(design)
    return case,path,design,proof


def context(records):
    loops=[i for i,r in enumerate(records) if r.get('loop_order',0)>0]
    first=records[loops[0]]
    anchor=next(i for i,r in enumerate(records) if r['strand_id']==first['strand_id'] and
                r['bp_index']==first['bp_index'] and not r.get('loop_order',0))
    nxtbp=first['bp_index']+(1 if first['direction']=='FORWARD' else -1)
    following=next(i for i,r in enumerate(records) if r['strand_id']==first['strand_id'] and r['bp_index']==nxtbp and not r.get('loop_order',0))
    beads=np.array([r['backbone_position'] for r in records])
    centers=np.array([r['slab_position'] for r in records])
    mats=Rotation.from_quat([r['slab_quaternion'] for r in records]).as_matrix()
    outward=-np.array(records[anchor]['base_normal'])
    axis=np.array(records[anchor]['axis_tangent'])
    outward-=axis*np.dot(outward,axis); outward/=np.linalg.norm(outward)
    projection=(beads[loops]-beads[anchor])@outward
    near=[i for i,p in zip(loops,projection) if p<=projection.max()/2+EPS]
    return dict(loops=loops,near=near,anchor=anchor,following=following,beads=beads,centers=centers,mats=mats)


def pose(records,ctx,i,angle):
    rotation=Rotation.from_rotvec(np.array(records[i]['axis_tangent'])*np.deg2rad(angle))
    matrix=rotation.as_matrix()@ctx['mats'][i]
    # Rigid rotation of the current slab/base about its fixed backbone center.
    center=ctx['beads'][i]+rotation.apply(ctx['centers'][i]-ctx['beads'][i])
    return center,matrix


def variants(records,ctx):
    yield 'current',{},ctx['centers'].copy(),ctx['mats'].copy()
    for angle in (90,-90,180):
        centers,mats=ctx['centers'].copy(),ctx['mats'].copy()
        angles={i:angle for i in ctx['near']}
        for i in angles:
            centers[i],mats[i]=pose(records,ctx,i,angle)
        yield f'rotate_{angle:+d}',angles,centers,mats
    # Deterministic finite coordinate search; consider both other helices and
    # other loop bases, preserving the current pose as an admissible choice.
    centers,mats=ctx['centers'].copy(),ctx['mats'].copy()
    angles={i:0 for i in ctx['near']}
    tried=list(range(-180,180,15))
    for _ in range(2):
        for i in ctx['near']:
            keep=np.arange(len(records))!=i
            def score(angle):
                c,m=pose(records,ctx,i,angle)
                g=slab_gap(c,m,centers[keep],mats[keep])
                h=bead_gap(c,m,ctx['beads'][keep])
                # Slab-vs-slab and slab-vs-bead contacts share first priority;
                # tie: smaller overlap, then smaller absolute angular change.
                return (int(np.sum(g < -EPS)+np.sum(h < -EPS)),
                        float(np.maximum(-g,0).sum()+np.maximum(-h,0).sum()),abs(angle),angle)
            angle=min(tried,key=score)
            angles[i]=angle
            centers[i],mats[i]=pose(records,ctx,i,angle)
    yield 'searched_15deg',angles,centers,mats


def identity(r):
    return {'helix_id':r['helix_id'],'bp':r['bp_index'],'direction':r['direction'],
            'strand_id':r['strand_id'],'loop_ordinal':r.get('loop_order',0)}


def measure(records,ctx,centers,mats):
    loops=set(ctx['loops']); host=records[ctx['anchor']]['helix_id']
    contacts=[]
    def group(j):
        return 'loop' if j in loops else ('parent_helix' if records[j]['helix_id']==host else 'other_helix')
    def add(kind,i,j,g):
        contacts.append({'kind':kind,'a':i,'b':int(j),'group':group(j),'gap_nm':float(g)})
    for i in ctx['loops']:
        gaps=slab_gap(centers[i],mats[i],centers,mats)
        for j in np.flatnonzero(gaps < -EPS):
            if j==i or (j in loops and j<i): continue
            add('slab_slab',i,j,gaps[j])
        gaps=bead_gap(centers[i],mats[i],ctx['beads'])
        for j in np.flatnonzero(gaps < -EPS):
            if j!=i: add('loop_slab_bead',i,j,gaps[j])
        # Include host slabs pierced by a loop bead; orientation cannot repair these.
        for j in np.flatnonzero(np.linalg.norm(centers-ctx['beads'][i],axis=1)<.6):
            if j in loops: continue
            gap=bead_gap(centers[j],mats[j],ctx['beads'][i:i+1])[0]
            if gap < -EPS: add('loop_bead_host_slab',i,j,gap)
    chain=[ctx['anchor'],*ctx['loops'],ctx['following']]
    bonded={frozenset((i,j)) for i,j in zip(chain[:-1],chain[1:])}
    proximity=[]
    for i in ctx['loops']:
        distances=np.linalg.norm(ctx['beads']-ctx['beads'][i],axis=1)
        for j in np.flatnonzero(distances<.65):
            if j==i or (j in loops and j<i) or frozenset((i,int(j))) in bonded: continue
            proximity.append({'a':i,'b':int(j),'distance_nm':float(distances[j]),'group':group(j),
                              'visible_beads_overlap':bool(distances[j]<2*BEAD_RADIUS-EPS)})
    bonds=np.linalg.norm(np.diff(ctx['beads'][chain],axis=0),axis=1)
    counts={kind:sum(c['kind']==kind for c in contacts) for kind in ('slab_slab','loop_slab_bead','loop_bead_host_slab')}
    return {'counts':counts,'total_display_contacts':len(contacts),'contacts':contacts,
            'by_group':{g:sum(c['group']==g for c in contacts) for g in ('parent_helix','other_helix','loop')},
            'nonbonded_backbone_under_065nm':proximity,'visible_backbone_overlaps':sum(p['visible_beads_overlap'] for p in proximity),
            'backbone_min_distance_nm':min((p['distance_nm'] for p in proximity),default=None),
            'root_bonds_nm':[float(bonds[0]),float(bonds[-1])], 'max_backbone_step_nm':float(bonds.max()),
            'atomic_clashes':None,'ring_piercings':None}


def evaluate(records):
    ctx=context(records)
    output={}
    for name,angles,centers,mats in variants(records,ctx):
        changed=set(angles)
        keep=[i for i in range(len(records)) if i not in changed]
        np.testing.assert_array_equal(centers[keep],ctx['centers'][keep])
        np.testing.assert_array_equal(mats[keep],ctx['mats'][keep])
        np.testing.assert_allclose(np.linalg.norm(centers[ctx['loops']]-ctx['beads'][ctx['loops']],axis=1),BASE_DISPLACEMENT,atol=1e-12)
        metrics=measure(records,ctx,centers,mats)
        disp=np.linalg.norm(centers-ctx['centers'],axis=1)
        metrics['max_slab_displacement_nm']=float(disp.max())
        metrics['per_base_displacement_nm']=[{'index':i,'loop_ordinal':records[i]['loop_order'],
            'angle_deg':angles[i],'displacement_nm':float(disp[i])} for i in sorted(angles)]
        metrics['backbone_displacement_nm']=0.0
        metrics['attachment_displacement_nm']=0.0
        output[name]={'metrics':metrics,'angles':{str(k):v for k,v in angles.items()},
                      'slab_centers':centers.tolist(),'slab_quaternions':Rotation.from_matrix(mats).as_quat().tolist()}
    baseline={(c['kind'],c['a'],c['b']) for c in output['current']['metrics']['contacts']}
    for value in output.values():
        contacts={(c['kind'],c['a'],c['b']) for c in value['metrics']['contacts']}
        value['metrics']['removed_contacts']=len(baseline-contacts)
        value['metrics']['introduced_contacts']=len(contacts-baseline)
    return {'near_indices':ctx['near'],'loop_indices':ctx['loops'],'anchor_index':ctx['anchor'],
            'following_index':ctx['following'],'variants':output}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    grant=json.loads((out/'process.json').read_text())
    assert 'a/b testing authorized' in grant['user_grant'].lower()
    self_check()
    (out/'inputs').mkdir(exist_ok=True)
    (out/'cases').mkdir(exist_ok=True)
    lengths=[30] if args.pilot else [6,30,80]
    directions=['FORWARD'] if args.pilot else ['FORWARD','REVERSE']
    bps=[40] if args.pilot else list(range(30,51))
    summaries=[]
    for length in lengths:
        for direction in directions:
            for bp in bps:
                case,path,design,proof=build_input(out,length,bp,direction)
                before=path.read_bytes()
                records=_geometry_for_design(design)
                result=evaluate(records)
                assert path.read_bytes()==before
                value={'label':LABEL,'case':case,'length':length,'direction':direction,'bp':bp,
                       'input_sha256':digest(path),'proof':proof,'records':records,**result}
                target=out/'cases'/f'{case}.json.gz'
                encoded=pack(value)
                if args.verify:
                    expected=gzip.decompress(target.read_bytes())
                    if expected!=encoded:
                        raise RuntimeError(f'Independent regeneration differs: {case}')
                else:
                    with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f: f.write(encoded)
                summaries.append({'case':case,'length':length,'direction':direction,'bp':bp,
                    'input_sha256':digest(path),'near_count':len(result['near_indices']),
                    'variants':{name:value['metrics'] for name,value in result['variants'].items()}})
            print(f'{"VERIFIED" if args.verify else "EVALUATED"} {length} nt {direction}: {len(bps)} phase sites',flush=True)
    if args.verify:
        (out/('pilot-replay.json' if args.pilot else 'replay.json')).write_text(json.dumps({'status':'verified','cases':len(summaries),
            'comparison':'all saved records, poses and metrics identical after independent input replay and candidate recomputation',
            'coordinate_tolerance_nm':0,'source_process':'native inputs independently audited; candidates never serialized into native files'},indent=2))
    else:
        (out/('pilot-summary.json' if args.pilot else 'summary.json')).write_text(json.dumps(summaries,indent=2))


if __name__=='__main__':
    main()
