"""Mobile rigid gold cores and permanent, body-fixed thiol grafts (CUDA only).

Effective short-linker model, not reactive Au-S chemistry. Parameter provenance
and qualification limits are in docs/oxdna_mobile_gold.md.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import numpy as np
from backend.core.constants import NM_TO_OXDNA

MODEL = 'mobile_gold_v1'
BTYPE = 499


def has_mobile_gold(design):
    return bool(design.nanoparticle_conjugations) or any(p.coating and not p.oxdna_fixed_core for p in design.nanoparticles)


def find_mobile_gold_oxdna():
    path = Path(os.environ.get('NADOC_GOLD_OXDNA_BIN', str(Path.home()/'.local/share/nadoc/engines/oxdna-mobile-gold/current/bin/oxDNA')))
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def configure_mobile_gold_stages(stages):
    for stage in stages:
        if stage.parfile or stage.interaction not in (None, 'DNA2', 'DNA2GOLD'):
            raise ValueError('Mobile gold currently supports DNA2 without proteins/PEG')
        # MC is replaced with GPU MD rather than leaving a CPU-only first stage.
        if stage.sim_type == 'MC':
            stage.steps = max(stage.steps, 10000)
            stage.kind = 'md_relax'
            stage.name = stage.name.replace('mc', 'gpu')
        stage.sim_type = 'MD'
        stage.backend = 'CUDA'
        stage.interaction = 'DNA2GOLD'
        stage.gold_file = 'mobile_gold.dat'
        stage.dt = min(stage.dt, 0.002)
        stage.thermostat = 'langevin'
        stage.diff_coeff = 2.5
        stage.refresh_vel = False


def append_mobile_gold(design, directory, *, linker_k=10., clearance_nm=0.4, exclusion_k=100.):
    """Append core particles once, resolving termini by strand identity, not helix ID."""
    from backend.physics.oxdna_interface import _walk_strand_nucleotides
    directory = Path(directory)
    particles = list(design.nanoparticles)
    if not particles or len(particles)>64:
        raise ValueError('Mobile gold requires 1..64 gold cores')
    if any(p.kind != 'gold_nanosphere' or p.oxdna_fixed_core for p in particles):
        raise ValueError('Mobile gold requires mobile gold spheres')
    if any(c.scheme != 'direct_thiol' for c in design.nanoparticle_conjugations):
        raise ValueError('Mobile gold v1 supports direct_thiol/C3 only; alkyl and PEG require separate linker calibration')
    for value in (linker_k, clearance_nm, exclusion_k):
        if not math.isfinite(value) or value<=0: raise ValueError('Invalid mobile gold parameter')
    top = (directory/'topology.top').read_text().splitlines()
    conf = (directory/'conf.dat').read_text().splitlines()
    n, ns = map(int,top[0].split())
    walk = list(_walk_strand_nucleotides(design))
    if len(walk)!=n or len(conf)!=n+3:
        raise ValueError('Mobile gold cannot append to hybrid/capture/already-expanded topology')
    by_strand = {}
    for i,step in enumerate(walk): by_strand.setdefault(step.strand.id,[]).append(i)
    core_ids = {p.id:j for j,p in enumerate(particles)}
    cores, grafts = [], []
    for j,p in enumerate(particles):
        radius = p.diameter_nm/2
        # Bulk gold density 19.3 g/cm3; oxDNA nucleotide mass unit 315.75 Da.
        mass = 19.3*602.214076*(4*math.pi/3)*radius**3/315.75
        r = radius*NM_TO_OXDNA
        # Stokes-Einstein water at 298 K (eta=0.890 mPa s); time unit 3.03 ps.
        diffusion_nm2_ps = 1.380649e-23*298.15/(6*math.pi*0.000890*radius*1e-9)*1e6
        diffusion = diffusion_nm2_ps*3.03*NM_TO_OXDNA**2
        cores.append(dict(id=p.id,index=n+j,radius=r,mass=mass,inertia=.4*mass*r*r,
                          diffusion=diffusion,rotation_diffusion=3*diffusion/(4*r*r)))
        pose = p.pose.to_array()
        a1, a3 = pose[:3,0], pose[:3,2]
        values = [*(pose[:3,3]*NM_TO_OXDNA),*a1,*a3,0,0,0,0,0,0]
        conf.append(' '.join(f'{v:.12g}' for v in values))
        top.append(f'{ns+j+1} {BTYPE} -1 -1')
    seen=set()
    for conj in design.nanoparticle_conjugations:
        if conj.nanoparticle_id not in core_ids: raise ValueError('Missing conjugated gold core')
        for record in conj.surface_strands:
            indices=by_strand.get(record.strand_id,[])
            if not indices: raise ValueError('Missing thiolated DNA strand')
            terminal=indices[0] if conj.attach_end=='5p' else indices[-1]
            if terminal in seen: raise ValueError('Duplicate gold graft on DNA terminus')
            seen.add(terminal)
            # C3 linker effective extension; retain explicit user spacer, no fit to seed strain.
            if not 0.3<=conj.spacer_nm<=1.5:
                raise ValueError('C3 effective spacer must be 0.3..1.5 nm')
            grafts.append(dict(dna=terminal,core=core_ids[conj.nanoparticle_id],
                site=(np.asarray(record.sulfur_local_nm)*NM_TO_OXDNA).tolist(),
                length=conj.spacer_nm*NM_TO_OXDNA,k=float(linker_k),strand_id=record.strand_id,attach_end=conj.attach_end))
    from backend.physics.oxdna_mobile_strep import coating_grafts
    coating, extra_grafts = coating_grafts(particles, by_strand, seen)
    grafts.extend(extra_grafts)
    # Periodic box must contain each sphere and leave room for a unique image.
    xyz=np.array([[float(v) for v in line.split()[:3]] for line in conf[3:]])
    for j, c in enumerate(cores):
        center = xyz[c['index']]
        if np.min(np.linalg.norm(xyz[:n] - center, axis=1)) < c['radius']:
            raise ValueError('DNA seed intersects the gold core; move/relax the attachment geometry first')
        for other in cores[:j]:
            if np.linalg.norm(center - xyz[other['index']]) < c['radius'] + other['radius']:
                raise ValueError('Gold core seeds overlap')
    extent=np.ptp(xyz,axis=0)+2*max(c['radius'] for c in cores)+10
    oldbox=np.array([float(v) for v in conf[1].split('=')[1].split()])
    box=max(float(max(extent)),float(max(oldbox)))
    conf[1]=f'b = {box:.12g} {box:.12g} {box:.12g}'
    top[0]=f'{n+len(cores)} {ns+len(cores)}'
    manifest=dict(model=MODEL,dna_count=n,n_cores=len(cores),cores=cores,grafts=grafts,
                  clearance_nm=clearance_nm,exclusion_k=exclusion_k,coating=coating,
                  binding='permanent effective grafts; nonreactive',parameters_qualified=False,
                  coating_approximation='rigid gold-strep and occupied biotin; flexible DNA linker' if coating else None,
                  hydrodynamics='bare gold sphere; coating mass and drag omitted')
    lines=[f'{n} {len(cores)} {len(grafts)} {clearance_nm*NM_TO_OXDNA:.12g} {exclusion_k}']
    for c in cores: lines.append(' '.join(str(c[k]) for k in ('index','radius','mass','inertia','diffusion','rotation_diffusion')))
    for g in grafts: lines.append(' '.join(map(str,[g['dna'],g['core'],*g['site'],g['length'],g['k']])))
    if coating:
        lines.append(f'COATING_V1 {len(coating)}')
        for c in coating: lines.append(' '.join(map(str,[c['core'],*c['center'],c['radius']])))
    (directory/'mobile_gold.dat').write_text('\n'.join(lines)+'\n')
    (directory/'mobile_gold.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (directory/'topology.top').write_text('\n'.join(top)+'\n')
    (directory/'conf.dat').write_text('\n'.join(conf)+'\n')
    return manifest


def read_core_poses(path, manifest):
    """Raw trajectory core transforms; row-major matrices in nm, same frame as DNA."""
    rows=np.loadtxt(path,skiprows=3)
    result=[]
    for core in manifest['cores']:
        row=rows[core['index']]
        a1,a3=row[3:6],row[6:9]
        pose=np.eye(4); pose[:3,:3]=np.column_stack((a1,np.cross(a3,a1),a3))
        pose[:3,3]=row[:3]/NM_TO_OXDNA
        result.append(dict(id=core['id'],pose=pose.ravel().tolist()))
    return result
