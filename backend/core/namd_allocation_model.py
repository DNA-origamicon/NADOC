"""Prepared-coordinate features and build-matched PME allocation accounting.

These describe expected allocations, separately from conservative admission.
Coordinate bins are not NAMD's hydrogen-group assignment or future coordinates.
"""
from functools import lru_cache
from itertools import product
import json
import math
import os
from pathlib import Path
import struct
import subprocess

import numpy as np

QUALIFIED_ENGINE = '2fda225c5f8838e5dbcb6a4e6a3e7e337f498df61cae2e6e320f994cb7c8b9bf'
QUALIFIED_CUFFT_ARCHIVE = '96f78236a76263c8ddfcec383ea201da17dadcd533527c5b198da2512e2c4286'
MIB=1024**2


def probe_manifest_path():
    return Path(os.environ.get('NADOC_CUFFT_PROBE_MANIFEST',
        str(Path.home()/'.cache/nadoc/namd-cufft-probe/manifest.json')))


@lru_cache(maxsize=256)
def _workspace(grid,device,helper,helper_hash,driver):
    # No grid/workspace allocation; the separate process releases CUDA context
    # memory when it exits. Reserve that context before querying a new plan.
    from backend.core.memory_budget import reserve
    with reserve(512*MIB,label='FFT plan sizing',gpu_mib=512,devices=device):
        result=subprocess.run([helper,*map(str,grid),device],capture_output=True,
                              text=True,timeout=15,check=True)
    data=json.loads(result.stdout)
    if data['grid']!=list(grid) or any(type(data[k]) is not int or data[k]<0
            for k in ('forward_bytes','backward_bytes')):
        raise ValueError('Invalid FFT plan response')
    return data


def matching_workspace(grid, *, engine_binary=None, device='0'):
    """Unknown/mismatched builds return a reason, never borrow another FFT plan."""
    from backend.core.namd_provenance import file_identity
    try:
        manifest=json.loads(probe_manifest_path().read_text())
        if not engine_binary:
            from backend.core.namd_runner import find_namd
            engine_binary=find_namd()
        if file_identity(engine_binary)['sha256']!=QUALIFIED_ENGINE or manifest['engine_sha256']!=QUALIFIED_ENGINE:
            raise ValueError('FFT helper does not match this NAMD build')
        if manifest.get('cufft_archive_sha256')!=QUALIFIED_CUFFT_ARCHIVE:
            raise ValueError('FFT archive has not been matched to this NAMD build')
        helper=manifest['helper']
        if file_identity(helper)['sha256']!=manifest['helper_sha256']:
            raise ValueError('FFT helper identity changed')
        if not str(device).isdigit():raise ValueError('Single numeric GPU required for FFT sizing')
        identity=subprocess.run(['nvidia-smi','--id='+str(device),'--query-gpu=uuid,driver_version',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        data=_workspace(tuple(grid),str(device),helper,manifest['helper_sha256'],identity)
        return {**data,'source':'matching static cuFFT plans; workspace auto-allocation disabled',
                'engine_sha256':QUALIFIED_ENGINE,'helper_sha256':manifest['helper_sha256'],
                'device_identity':identity}
    except (OSError,ValueError,KeyError,MemoryError,subprocess.SubprocessError) as exc:
        return dict(unavailable=str(exc))


def pme_allocation(atoms, grid, workspace, *, resident=True):
    """Single-GPU 3D solver: grids + separate forward/backward plan workspaces.

    The qualified resident build retains the initial PME solver as well as its
    resident solver (confirmed by allocation traces). Both pairs of plans count.
    Small metadata and driver allocations remain in the residual engine model.
    """
    if 'unavailable' in workspace:return dict(unavailable=workspace['unavailable'])
    x,y,z=grid;points=x*y*z
    alignment=workspace['texture_alignment']
    resident_grid=math.ceil(points/alignment)*alignment*4
    initial_grid=points*4
    complex_grid=(x//2+1)*y*z*8
    plans=workspace['forward_bytes']+workspace['backward_bytes']
    grid_bytes=initial_grid+complex_grid+(resident_grid+complex_grid if resident else 0)
    workspace_bytes=plans*(2 if resident else 1)
    # Resident atom/force arrays are fixed-size; the offload solver uses 1.5x
    # staging capacity. This atom term is not the FFT workspace itself.
    atom_bytes=(28 if resident else 42)*atoms
    return dict(grid=list(grid),grid_bytes=grid_bytes,workspace_bytes=workspace_bytes,
        atom_staging_bytes=atom_bytes,plan_pairs=2 if resident else 1,
        expected_mib=(grid_bytes+workspace_bytes+atom_bytes)/MIB,
        workspace=workspace,excludes='small PME metadata, driver/context allocations')


def coordinate_features(coordinates, box, grid, away, *, origin=None):
    """Count current coordinate bins and conservative candidate tile pairs.

    Scratch buffers are bounded by 100k atoms. Periodic images are counted, even
    for a grid shorter than the neighbor stencil. No full atom-pair list is built.
    The candidate count precedes NAMD tile bounding-box rejection and is an upper
    proxy for this bin assignment, not a certified bound on future tile capacity.
    """
    box=np.asarray(box,dtype=float);grid=np.asarray(grid,dtype=int)
    if box.shape!=(3,) or grid.shape!=(3,) or np.any(box<=0) or np.any(grid<1):
        raise ValueError('Positive box and patch grid required')
    if not np.isfinite(box).all() or math.prod(map(int,grid))>1_000_000:
        raise ValueError('Coordinate feature grid outside sizing limits')
    lower=np.asarray(origin,dtype=float)-box/2 if origin is not None else np.zeros(3)
    counts=np.zeros(tuple(grid),dtype=np.int64)
    for start in range(0,len(coordinates),100_000):
        block=np.asarray(coordinates[start:start+100_000],dtype=float)
        if block.ndim!=2 or block.shape[1]!=3 or not np.isfinite(block).all():
            raise ValueError('Invalid coordinates')
        bins=np.floor(np.mod(block-lower,box)/box*grid).astype(int)
        np.add.at(counts,tuple(bins.T),1)
    tiles=(counts+31)//32
    pairs=int(np.sum(tiles*(tiles+1)//2));lists=int(tiles.sum())
    for offset in product(*(range(-int(a),int(a)+1) for a in away)):
        if offset<=(0,0,0):continue
        other=np.roll(tiles,offset,axis=(0,1,2))
        pairs+=int(np.sum(tiles*other))
        lists+=int(np.sum(tiles*(other>0)))
    total=int(counts.sum());patches=counts.size
    return dict(atoms=total,grid=grid.tolist(),max_bin_atoms=int(counts.max()),
        mean_bin_atoms=total/patches,padded_atoms=int(tiles.sum()*32),
        density_heterogeneity=float(np.sum(counts.astype(float)**2)*patches/max(1,total**2)),
        candidate_jtiles=pairs,candidate_tile_lists=lists,
        candidate_capacity_mib=2*(268*pairs+304*lists)/MIB,
        growth_factor=2.,scope='current atom bins; candidate tiles before distance rejection; NAMD hydrogen-group bins may differ')


def spatial_tile_features(coordinates,box,grid,away,pairlist,origin=None,sample_tiles=1024):
    """Approximate NAMD's 32-atom recursive spatial partition and BB rejection.

    All tile boxes are built; a fixed evenly spaced subset of tiles is queried.
    This bounds query memory independently of total pair count. The sample is a
    deterministic predictor feature, not a statistical upper bound.
    """
    from scipy.spatial import cKDTree
    box=np.asarray(box,dtype=float);grid=np.asarray(grid,dtype=int)
    lower=np.asarray(origin,dtype=float)-box/2 if origin is not None else np.zeros(3)
    xyz=np.mod(np.asarray(coordinates)-lower,box)
    bins=np.floor(xyz/box*grid).astype(int)
    flat=np.ravel_multi_index(bins.T,tuple(grid));order=np.argsort(flat,kind='stable')
    boundaries=np.flatnonzero(np.r_[True,flat[order][1:]!=flat[order][:-1],True])
    centres=[];halves=[];patches=[]
    def boxes(ids,begin,end,patch):
        selected=xyz[ids[begin:end]]
        if end-begin<=32:
            lo=selected.min(axis=0);hi=selected.max(axis=0)
            centres.append((hi+lo)/2);halves.append((hi-lo)/2);patches.append(patch);return
        axis=int(np.argmax(np.ptp(selected,axis=0)))
        split=((begin+end+32)//64)*32
        ids[begin:end]=ids[begin:end][np.argpartition(selected[:,axis],split-begin)]
        boxes(ids,begin,split,patch);boxes(ids,split,end,patch)
    for a,b in zip(boundaries,boundaries[1:]):
        ids=order[a:b].copy();boxes(ids,0,len(ids),bins[ids[0]])
    centre=np.asarray(centres);half=np.asarray(halves);patch=np.asarray(patches)
    tree=cKDTree(centre,boxsize=box);selected=np.linspace(0,len(centre)-1,min(sample_tiles,len(centre)),dtype=int)
    radius=pairlist+2*float(np.linalg.norm(half,axis=1).max());accepted=0
    for i in selected:
        js=np.asarray(tree.query_ball_point(centre[i],radius),dtype=int)
        delta=np.abs(centre[js]-centre[i]);delta=np.minimum(delta,box-delta)
        gap=np.maximum(0,delta-half[js]-half[i]);dp=np.abs(patch[js]-patch[i]);dp=np.minimum(dp,grid-dp)
        accepted+=np.count_nonzero((np.sum(gap*gap,axis=1)<pairlist**2)&np.all(dp<=away,axis=1))
    pairs=(accepted/len(selected)+1)*len(centre)/2
    return dict(spatial_jtiles=pairs,spatial_tile_pair_capacity_mib=536*pairs/MIB,
        tile_sample_count=len(selected),total_spatial_tiles=len(centre),
        scope='sampled 32-atom bounding-box tile pairs; atom bins approximate hydrogen-group bins')


@lru_cache(maxsize=64)
def _file_features(path,size,mtime,atoms,box,grid,away,origin,pairlist):
    path=Path(path)
    if path.suffix.lower() in ('.coor','.bin') or size==4+atoms*24:
        with path.open('rb') as stream:header=stream.read(4)
        endian=next((e for e in ('<','>') if struct.unpack(e+'i',header)[0]==atoms),None)
        if endian is None or size!=4+atoms*24:raise ValueError('Coordinate/topology count mismatch')
        xyz=np.memmap(path,dtype=endian+'f8',offset=4,mode='r',shape=(atoms,3))
    else:
        xyz=np.empty((atoms,3));n=0
        with path.open() as stream:
            for line in stream:
                if line.startswith(('ATOM  ','HETATM')):
                    if n>=atoms:raise ValueError('Coordinate/topology count mismatch')
                    xyz[n]=[float(line[i:i+8]) for i in (30,38,46)];n+=1
        if n!=atoms:raise ValueError('Coordinate/topology count mismatch')
    result=coordinate_features(xyz,box,grid,away,origin=origin)
    result.update(spatial_tile_features(xyz,box,grid,away,pairlist,origin=origin))
    return result


def prepared_features(path, atoms, box, layout, origin=None,pairlist=13.5):
    from backend.core.memory_budget import reserve
    if not 0<atoms<=3_000_000:raise ValueError('Coordinate feature size outside qualified range')
    path=Path(path).resolve();stat=path.stat()
    with reserve(512*MIB,label='Prepared-coordinate memory forecast'):
        return _file_features(str(path),stat.st_size,stat.st_mtime_ns,atoms,tuple(box),
            tuple(layout['grid']),tuple(layout['away']),tuple(origin) if origin is not None else None,float(pairlist))


def prepared_allocation(configuration, options, box, estimate, *, engine_binary=None,device='0',threads=16):
    """Expected usage is descriptive; ram_mib/gpu_mib still control admission."""
    from backend.core.namd_pme import pme_grid
    name=options.get('bincoordinates',options.get('coordinates'))
    try:
        if not name:raise ValueError('Starting coordinates are unresolved')
        origin=list(map(float,options['cellorigin'].split())) if 'cellorigin' in options else None
        coordinate=Path(configuration).parent/name
        coordinate_basis='stage starting coordinates'
        if not coordinate.exists() and options.get('coordinates'):
            coordinate=Path(configuration).parent/options['coordinates']
            coordinate_basis='prepared initial coordinates; future checkpoint not yet present'
        features=prepared_features(coordinate,estimate.atoms,box,estimate.patch_layout,origin,
                                   float(options.get('pairlistdist',13.5)))
        grid=pme_grid(tuple(box),float(options.get('pmegridspacing',1.5)))
        workspace=matching_workspace(grid,engine_binary=engine_binary,device=device)
        pme=pme_allocation(estimate.atoms,grid,workspace,resident=estimate.gpu_resident)
        result=dict(coordinates=str(coordinate.resolve()),coordinate_basis=coordinate_basis,neighbor=features,pme=pme,
            ram_mib=None,gpu_mib=None,admission_ram_mib=estimate.ram_mib,admission_gpu_mib=estimate.gpu_mib,
            confidence=None,basis='prepared geometry and matching FFT plans',estimate_kind='expected_process_peak',
            limitations=['Coordinate bins approximate NAMD hydrogen-group bins.',
                         'Future capacity growth remains covered by the admission envelope.'])
        model_path=Path(__file__).resolve().parents[1]/'data/namd_resource_expected.json'
        if model_path.exists() and 'unavailable' not in workspace:
            model=json.loads(model_path.read_text());key='resident' if estimate.gpu_resident else 'offload'
            target=workspace.get('device')
            driver=workspace.get('device_identity','').split(',')[-1].strip()
            if model.get('qualified_engine_sha256') != QUALIFIED_ENGINE:
                result['limitations'].append('Expected-usage model has no matching qualified engine identity.')
            elif (target not in model.get('qualified_gpu_names',[]) or driver not in model.get('qualified_drivers',[])
                    or threads not in model.get('qualified_threads',[])):
                result['limitations'].append('Expected-usage residual model is not qualified for this GPU/driver/worker count.')
            elif key in model['modes']:
                bonds=estimate.components['host']['restraints_mib']/192*MIB/1e6
                values=[1.,estimate.atoms/1e6,bonds,features['spatial_tile_pair_capacity_mib'],
                        estimate.atoms/1e6*max(0,(float(options.get('pairlistdist',13.5))/13.5)**3-1),
                        estimate.atoms/1e6 if float(options.get('timestep',1))>=3 else 0,
                        estimate.atoms/1e6 if options.get('constraints','off').lower() in ('on','yes','true','1') else 0,
                        math.prod(features['grid'])/1000]
                fit=model['modes'][key]
                if not all(len(items)==len(values) for items in
                           (model['features'],fit['feature_ranges'],fit['ram'],fit['gpu'])):
                    raise ValueError('Expected-memory model feature schema mismatch')
                result['extrapolated_features']=[model['features'][i] for i,(v,limits) in enumerate(zip(values,fit['feature_ranges']))
                                                if v<limits[0] or v>limits[1]]
                result['ram_mib']=math.ceil(max(0,sum(a*b for a,b in zip(values,fit['ram']))))
                if 'expected_mib' in pme:
                    result['gpu_mib']=math.ceil(max(0,sum(a*b for a,b in zip(values,fit['gpu']))+pme['expected_mib']))
                result['model_basis']=model['basis'];result['validation']=fit['validation']
                result['limitations'].append('Timestep/profile coefficients are empirical; individual geometry errors can exceed the median validation error.')
                result['exceeds_admission']=any(result[k] is not None and result[k]>result['admission_'+k]
                    for k in ('ram_mib','gpu_mib'))
        return result
    except (OSError,ValueError,KeyError,TypeError,MemoryError) as exc:
        return dict(ram_mib=None,gpu_mib=None,unavailable=str(exc),confidence=None)
