"""COM impulse accounting and bounded literature-motivated NVE controls."""
import json
import numpy as np
import parmed
import diagnose as d

def energies(p, name):
    rows = []
    for line in (p/f'{name}.log').read_text().splitlines():
        if line.startswith('ETITLE:'):
            keys = line.split()[1:]
        elif line.startswith('ENERGY:'):
            rows.append(dict(zip(keys, map(float, line.split()[1:]))))
    return rows

def impulses():
    result = {}
    for kind in ('particle', 'slab'):
        for mode in ('rigid', 'preserve_com'):
            p = d.ROOT/f'{kind}_{mode}'
            atoms = d.parse_psf_atoms((p/'system.psf').read_text())
            mass = np.array([a.mass for a in atoms])
            a, b = [d.read_binary(p/'output'/f'1_0_{s}.vel') for s in ('part', 'zero')]
            com = np.average(a, axis=0, weights=mass)
            delta = b-a
            result[p.name] = dict(com_velocity_A_per_AKMA=com.tolist(),
                max_residual_after_predicted_com_removal=float(abs(delta+com).max()),
                kinetic_change_kcal_mol=float(.5*np.sum(mass[:,None]*(b*b-a*a))),
                predicted_com_kinetic_loss_kcal_mol=float(-.5*mass.sum()*np.dot(com,com)),
                potential_change_kcal_mol=energies(p,'1_0_zero')[0]['POTENTIAL']-energies(p,'1_0_part')[-1]['POTENTIAL'])
    (d.ROOT/'impulses.json').write_text(json.dumps(result,indent=2))

def solvent():
    p = d.prepare('solvent_only_v2', d.REPO/'workspace/gold_validation_20260914/particle')
    # Diagnostic deletion preserves the solvent state/atom order, leaving the old
    # particle cavity. This is a mechanism control, not equilibrated bulk water.
    psf = parmed.load_file(str(p/'system.psf'))
    keep = np.array([a.type != 'NAUI' for a in psf.atoms])
    psf.strip(~keep)
    psf.write_psf(str(p/'solvent.psf'))
    psf.coordinates = d.read_binary(p/'output/seed.coor')[keep]
    psf.write_pdb(str(p/'solvent.pdb'))
    for ext in ('coor','vel'):
        arr = d.read_binary(p/'output'/f'seed.{ext}')[keep]
        (p/'output'/f'solvent.{ext}').write_bytes(np.array([len(arr)],dtype='<i4').tobytes()+arr.astype('<f8').tobytes())
    (p/'output/solvent.xsc').write_bytes((p/'output/seed.xsc').read_bytes())
    result={}
    for mode in ('default','preserved'):
        changes=[('structure system.psf','structure solvent.psf'),('coordinates system.pdb','coordinates solvent.pdb'),('constraints on','constraints off')]
        if mode=='preserved':
            changes += [('wrapAll off','COMmotion yes\nwrapAll off')]
        for name,src,steps in [('full','solvent',40),('part','solvent',20),('split',mode+'_part',20),('zero',mode+'_part',0)]:
            d.run(p,mode+'_'+name,src,steps,1.,changes)
        a,b=[d.read_binary(p/'output'/f'{mode}_{s}.vel') for s in ('full','split')]
        result[mode]={'max_velocity_difference_A_per_AKMA':float(abs(a-b).max())}
    (d.ROOT/'solvent_control.json').write_text(json.dumps(result,indent=2))

def nve():
    result={}
    for kind in ('particle','slab'):
        p=d.ROOT/f'{kind}_preserve_com'
        for dt in (2.,1.,.5):
            name='energy_'+str(dt).replace('.','_')
            d.run(p,name,'seed',int(4000/dt),dt,
                  [('wrapAll off','COMmotion yes\nwrapAll off'),
                   ('outputEnergies 1\n','outputEnergies 1\noutputEnergiesPrecision 10\n')])
            rows=energies(p,name)
            t=np.array([r['TS']-rows[0]['TS'] for r in rows])*dt/1000
            e=np.array([r['TOTAL'] for r in rows])
            # Equal physical windows, retain startup separately; no numerical gate.
            use=t>=.2
            coeff=np.polyfit(t[use],e[use],1)
            result[f'{kind}_{dt}']=dict(duration_ps=float(t[-1]),energy_std_kcal_mol=float(e[use].std()),
                 energy_range_kcal_mol=float(np.ptp(e[use])),slope_kcal_mol_ps=float(coeff[0]),
                 detrended_std_kcal_mol=float((e[use]-np.polyval(coeff,t[use])).std()),
                 initial_energy_kcal_mol=float(e[0]),final_energy_kcal_mol=float(e[-1]))
            (d.ROOT/'nve_energy.json').write_text(json.dumps(result,indent=2))
            print(kind,dt,result[f'{kind}_{dt}'],flush=True)

if __name__=='__main__':
    impulses()
    solvent()
    nve()
