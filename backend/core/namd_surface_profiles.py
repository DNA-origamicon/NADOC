"""Planar ion profiles for a closed, fixed-volume periodic wall.

Ion-only compensation is not the microscopic electric field: water polarization
is deliberately excluded. The finite-slit Debye fit is diagnostic, not validation.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from backend.core.dcd_fast import read_layout, read_frame, cell_to_dimensions

MOLAR_PER_NM3 = 1 / .602214076


def fit_screening(distance, residual, half_depth, fit_min, fit_max):
    """Fit A*sinh((h-d)/lambda)/sinh(h/lambda), with free amplitude."""
    x, y = np.asarray(distance), np.asarray(residual)
    use = (x >= fit_min) & (x <= fit_max) & np.isfinite(y)
    if use.sum() < 5 or np.max(np.abs(y[use])) < .02:
        return {'available': False, 'reason': 'Insufficient resolved signal or fit bins.'}
    x, y = x[use], y[use]
    if np.any(y <= 0):
        return {'available': False, 'reason': 'Residual changes sign or overscreens in the fit window.'}

    def shape(d, length):
        return np.exp(-d / length) * (-np.expm1(-2*(half_depth-d)/length)) / (-np.expm1(-2*half_depth/length))

    result = least_squares(lambda p: p[0]*shape(x, p[1])-y, [1., .6], bounds=([0., .05], [20., 20.]))
    amplitude, length = result.x
    prediction = amplitude * shape(x, length)
    ss = float(np.sum((y-y.mean())**2))
    r2 = 1-float(np.sum((prediction-y)**2))/ss if ss > 1e-12 else None
    usable = bool(result.success and .051 < length < 19.99 and amplitude < 19.99 and r2 is not None and r2 > .8)
    return dict(available=usable, lambda_nm=float(length), amplitude=float(amplitude), r_squared=r2,
                reason='Diagnostic fit only; correlated bins and finite sampling preclude a confidence claim.' if usable else 'Poor fit or parameter at bound.',
                distance_nm=x.tolist(), prediction=prediction.tolist(), model='finite_slit_linear_PB')


def summarize_profiles(counts, edges, area, wall_charge, temperature=298.15, dielectric=78.4,
                       fit_min=.6, fit_max=2.0):
    """counts[frame,face,species,bin], species fixed Na+, Cl-. Volume is A*dz."""
    counts = np.asarray(counts, dtype=float)
    edges = np.asarray(edges, dtype=float)
    if counts.ndim != 4 or counts.shape[1:3] != (2,2) or counts.shape[-1] != len(edges)-1 or not len(counts):
        raise ValueError('Expected nonempty frame × two faces × Na/Cl × distance counts.')
    if not np.all(np.isfinite(counts)) or np.any(counts < 0) or area <= 0 or np.any(np.diff(edges) <= 0):
        raise ValueError('Invalid histogram or slab volume.')
    dz = np.diff(edges)
    conc = counts.mean(axis=0) / (area * dz) * MOLAR_PER_NM3 * 1000
    blocks = [b for b in np.array_split(counts, min(4, len(counts))) if len(b)]
    block_conc = np.array([b.mean(axis=0)/(area*dz)*MOLAR_PER_NM3*1000 for b in blocks])
    sem = block_conc.std(axis=0, ddof=1)/np.sqrt(len(blocks)) if len(blocks)>1 else np.zeros_like(conc)
    centers = (edges[1:]+edges[:-1])/2
    ionic = (counts[:,:,0,:]-counts[:,:,1,:]).mean(axis=0)/area/dz
    pooled_charge = counts.mean(axis=(0,1))
    residual = None if wall_charge == 0 else 1 + np.cumsum(pooled_charge[0]-pooled_charge[1]) / (wall_charge/2)
    bulk = centers >= .8*edges[-1]
    bulk_species = conc[:,:,bulk].mean(axis=(0,2))
    ionic_strength = float(bulk_species.sum()/2000)
    debye = float(np.sqrt(8.8541878128e-12*dielectric*1.380649e-23*temperature /
                  (2*6.02214076e23*1000*ionic_strength*(1.602176634e-19)**2))*1e9) if ionic_strength>0 else None
    reference = (np.exp(-edges[1:]/debye)*(-np.expm1(-2*(edges[-1]-edges[1:])/debye))/(-np.expm1(-2*edges[-1]/debye))).tolist() if debye else None
    fit = fit_screening(edges[1:], residual, edges[-1], fit_min, fit_max) if residual is not None else {'available':False,'reason':'Neutral wall: compensation fraction and charged-wall fit are undefined.'}
    block_fits = []
    for b in blocks:
        pool = b.mean(axis=(0,1))
        f = fit_screening(edges[1:], 1+np.cumsum(pool[0]-pool[1])/(wall_charge/2), edges[-1], fit_min, fit_max) if wall_charge else {'available':False}
        block_fits.append(f.get('lambda_nm') if f['available'] else None)
    return dict(distance_nm=centers.tolist(), edge_distance_nm=edges[1:].tolist(),
                concentration_mM={face:{name:conc[i,j].tolist() for j,name in enumerate(['Na+','Cl-'])} for i,face in enumerate(['positive','negative'])},
                concentration_block_sem_mM={face:{name:sem[i,j].tolist() for j,name in enumerate(['Na+','Cl-'])} for i,face in enumerate(['positive','negative'])},
                ionic_charge_e_nm3={face:ionic[i].tolist() for i,face in enumerate(['positive','negative'])},
                residual_sheet_fraction=None if residual is None else residual.tolist(),
                compensated_fraction=None if residual is None else (1-residual).tolist(),
                bulk_region_nm=[float(.8*edges[-1]),float(edges[-1])], bulk_Na_mM=float(bulk_species[0]), bulk_Cl_mM=float(bulk_species[1]),
                reference_residual_sheet_fraction=reference, reference_debye_nm=debye, reference_dielectric=dielectric, temperature_K=temperature,
                screening_fit=fit, block_lambda_nm=block_fits, blocks=len(blocks),
                first_last_concentration_rms_mM=float(np.sqrt(np.mean((block_conc[-1]-block_conc[0])**2))),
                net_charge_e=float(wall_charge+counts.mean(axis=0).sum(axis=(0,2)) @ np.array([1.,-1.])),
                sampling='Equal saved-frame weights; four contiguous blocks at most; block SEM is not an independent-sample confidence interval.',
                interpretation='Ion-only compensation, excluding water polarization. Finite-slit fit is diagnostic; screening and equilibration are not automatically certified. The pooled midpoint compensation is fixed by global neutrality, not evidence of screening.')


def analyze_surface_package(package: Path, name_stem: str, segments, *, bins=48, max_frames=256,
                            discard_fraction=.5, fit_min_nm=.6, fit_max_nm=2., dielectric=78.4):
    manifest = json.loads((package/'manifest.json').read_text())
    spec = manifest.get('graphene_nanopore') or {}
    pressure_equilibrated = spec.get('cell_policy') == 'fixed_area_normal_pressure'
    if spec.get('pore_diameter_nm') != 0 or spec.get('layers',1) != 1 or spec.get('cell_policy') not in {'fixed_volume', 'fixed_area_normal_pressure'}:
        raise ValueError('Profiles require one closed, fixed-volume periodic wall.')
    if manifest.get('field') or manifest.get('ion_transport'):
        raise ValueError('Equilibrium screening analysis requires no external E-field.')
    box = np.asarray(spec['periodic_box_nm'],dtype=float)
    normal = np.asarray(spec['dir'],dtype=float)
    axis = int(np.argmax(np.abs(normal)))
    if not np.isclose(np.abs(normal[axis]),1) or np.count_nonzero(np.abs(normal)>1e-8)!=1:
        raise ValueError('Profiles require a Cartesian surface normal.')
    lines=(package/f'{name_stem}.psf').read_text().splitlines()
    start=next(i for i,line in enumerate(lines) if '!NATOM' in line)
    n=int(lines[start].split()[0]); atoms=[s.split() for s in lines[start+1:start+1+n]]
    allowed={'GRP','TIP3','SOD','CLA'}
    if any(a[3] not in allowed for a in atoms):
        raise ValueError('Initial screening analysis supports the NaCl/water/wall control only.')
    groups=[np.array([i for i,a in enumerate(atoms) if a[3]==r],dtype=int) for r in ['SOD','CLA']]
    for group, expected in zip(groups,[1.,-1.]):
        if any(not np.isclose(float(atoms[i][6]),expected) for i in group):
            raise ValueError('Ion PSF charges disagree with Na+/Cl- species.')
    wall=np.array([i for i,a in enumerate(atoms) if a[3]=='GRP'],dtype=int)
    q=sum(float(atoms[i][6]) for i in wall)
    if not len(wall) or abs(sum(float(a[6]) for a in atoms))>1e-5:
        raise ValueError('Missing wall or nonneutral topology; rebuild the package.')
    from backend.core.namd_graphene import validate_graphene_wall_package
    validate_graphene_wall_package(package)
    # Restart epoch wins on overlap, including rollback beyond several old frames.
    refs=[]; sources=[]
    names=list(dict.fromkeys(s[0] for s in segments))
    for name in names:
        epoch=[]
        pieces=[Path(s[2]) for s in segments if s[0]==name]
        pieces.sort(key=lambda p: int(m.group(1)) if (m:=re.search(r'\.cont(\d+)\.dcd$',p.name)) else 0)
        for path in pieces:
            layout=read_layout(path)
            if layout.n_atoms != n: raise ValueError('Trajectory/topology atom count mismatch.')
            if not layout.n_frames: continue
            epoch=[r for r in epoch if r[3] < layout.istart]
            epoch.extend((path,layout,i,layout.istart+i*layout.nsavc) for i in range(layout.n_frames))
            sources.append(dict(file=path.name,bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,complete_frames=layout.n_frames))
        refs.extend(epoch)
    total=len(refs)
    refs=refs[int(total*discard_fraction):]
    if not refs: raise ValueError('No complete trajectory frames yet. Run dynamics before generating profiles.')
    refs=[refs[i] for i in np.unique(np.linspace(0,len(refs)-1,min(len(refs),max_frames),dtype=int))]
    if pressure_equilibrated:
        # Production inherits the equilibrated cell, which differs from the original
        # solvation descriptor. Never normalize its density by that original volume.
        path, layout, index, _ = refs[0]
        _, raw = read_frame(path, layout, index)
        dims = cell_to_dimensions(raw)
        if dims is None:
            raise ValueError('Pressure-equilibrated wall profiles require saved trajectory cell dimensions.')
        box = np.asarray(dims[:3], float) / 10
    half = box[axis]/2
    if not 0 <= fit_min_nm < fit_max_nm < half:
        raise ValueError(f'Fit window must lie between 0 and reservoir midpoint {half:g} nm.')
    area=float(np.prod(np.delete(box,axis))); edges=np.linspace(0,half,bins+1); counts=[]
    plane=float(spec['plane_point_nm'][axis]); sign=float(normal[axis])
    for path,layout,index,_ in refs:
        xyz,raw=read_frame(path,layout,index); xyz=xyz.astype(float)/10
        dims=cell_to_dimensions(raw)
        if dims is not None and (not np.allclose(dims[:3]/10,box,atol=.005) or not np.allclose(dims[3:],90,atol=.01)):
            raise ValueError('Trajectory cell changed or is nonorthogonal; fixed-slab normalization is invalid. Use the subsequent NVT production trajectory for screening profiles.')
        # Track the restrained wall's mean displacement, using periodic offsets.
        wall_offset=(xyz[wall,axis]-plane+half)%(2*half)-half
        center=plane+float(wall_offset.mean())
        hist=[]
        for side in [1,-1]:
            species=[]
            for group in groups:
                d=((xyz[group,axis]-center+half)%(2*half)-half)*sign
                species.append(np.histogram(np.abs(d[d>=0] if side==1 else d[d<0]),bins=edges)[0])
            hist.append(species)
        if any(sum(np.sum(hist[face][species]) for face in range(2)) != len(group) for species,group in enumerate(groups)):
            raise ValueError('Ion histogram lost atoms; check trajectory coordinates and surface registration.')
        counts.append(hist)
    result=summarize_profiles(counts,edges,area,q,float(spec.get('temperature_K',300)),dielectric,fit_min_nm,fit_max_nm)
    result.update(schema_version=1,frames=len(refs),available_frames=total,sources=sources,
                  area_nm2=area,half_depth_nm=float(half),wall_charge_e=q,
                  options=dict(bins=bins,max_frames=max_frames,discard_fraction=discard_fraction,fit_min_nm=fit_min_nm,fit_max_nm=fit_max_nm,dielectric=dielectric))
    return result


def persist_profile(path, result):
    """Atomic replacement with a unique writer path, including concurrent refreshes."""
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(result,indent=2,allow_nan=False));tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
