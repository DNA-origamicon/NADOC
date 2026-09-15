"""Pilot-derived whole-water inventory correction; no interaction fitting."""
import json
import numpy as np
import campaign as c
from analyze_campaign import analyze

target_rho=np.mean([json.loads((c.ROOT/f'bulk_{s}/npt_analysis.json').read_text())['late_density'] for s in c.SEEDS])
plan={}
for kind in ('slab','nanoparticle'):
    estimates=[];rows=[]
    for seed in c.SEEDS:
        p=c.ROOT/f'{kind}_{seed}_initial';r=analyze(p,'pilot')
        m=json.loads((p/'manifest.json').read_text());cell=np.array(m['cell_nm'])
        # Hold the first adsorption layers' inventory fixed for this first update.
        # 0.65 nm is an operational boundary beyond the two observed planar peaks,
        # not a universal material length or a physical acceptance criterion.
        volumes=[]
        for shell in (.6,.65,.8):
            v=(np.prod(cell[:2])*(m['geometry']['liquid_bounds_nm'][1]-m['geometry']['liquid_bounds_nm'][0]-2*shell)
                 if kind=='slab' else np.prod(cell)-4*np.pi/3*(m['geometry']['radius_nm']+shell)**3)
            volumes.append(float(v))
        targets=[r['n_water']+(target_rho-r['late_density'])*v for v in volumes]
        estimates.append(targets[1]);rows.append(dict(seed=seed,initial_water=r['n_water'],initial_density=r['late_density'],
            response_volumes_nm3=volumes,target_water_sensitivity=targets))
    target=int(round(np.mean(estimates)))
    plan[kind]=dict(bulk_density_reference=target_rho,target_water=target,operational_layer_boundaries_nm=[.6,.65,.8],pilots=rows,
                   note='Mass-balance first update assuming adsorbed inventory changes little; validated by new independent NVT runs')
(c.ROOT/'inventory_revision.json').write_text(json.dumps(plan,indent=2))
for kind in ('slab','nanoparticle'):
    target=plan[kind]['target_water']
    for seed in c.SEEDS:
        initial=next(r['initial_water'] for r in plan[kind]['pilots'] if r['seed']==seed)
        scale=max(1.,target/initial)*1.06
        p=c.gold(kind,seed,scale=scale,suffix='revised',target_water=target)
        c.execute(p,'minimize',0,minimize=500)
        c.execute(p,'pilot',200000,'minimize')
        analyze(p,'pilot')
