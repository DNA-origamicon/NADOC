"""Fixed-charge electrode packages with optional DNA and explicit PEG.

Managed relaxation remains experimental pending native force and convergence qualification.
Uses existing TIP3P/CUFIX assets and independently restrained NGRC wall sites.
"""
import json
import math
import shutil
import tempfile
from pathlib import Path

from backend.core import namd_solvate as solvate
from backend.core.models import Design
from backend.core.namd_package import complete_psf
from backend.core.namd_slab import render_slab_tcl
from backend.core.namd_surface_charge import E_PER_NM2_TO_C_M2


def electrode_layout(spec, vacuum_factor=3.):
    axis = {'x': 0, 'y': 1, 'z': 2}.get(spec.get('normal'))
    gap, width, depth, sigma = [float(spec[k]) for k in ('gap_nm', 'width_nm', 'depth_nm', 'working_charge_C_m2')]
    if axis is None or any(not math.isfinite(v) or not 2 <= v <= 200 for v in (gap,width,depth)):
        raise ValueError('Electrode geometry requires Cartesian normal and 2–200 nm dimensions')
    if not math.isfinite(sigma) or abs(sigma) > .5:
        raise ValueError('Electrode charge must be within ±0.5 C/m²')
    if not math.isfinite(vacuum_factor) or vacuum_factor < 3:
        raise ValueError('EW3DC qualification requires at least 3× normal cell height')
    lateral = [i for i in range(3) if i != axis]
    cell = [0.,0.,0.]
    cell[axis] = gap
    cell[lateral[0]], cell[lateral[1]] = width, depth
    nu, nv = math.ceil(width/.2), math.ceil(depth/.2)
    positions = []
    for side in (0., gap):
        for u in range(nu):
            for v in range(nv):
                p = [0.,0.,0.]
                p[axis] = side
                p[lateral[0]], p[lateral[1]] = (u+.5)*width/nu, (v+.5)*depth/nv
                positions.append(p)
    requested = sigma * width * depth / E_PER_NM2_TO_C_M2
    q = int(math.copysign(math.floor(abs(requested)+.5), requested))
    if sigma and not q:
        raise ValueError('Working charge rounds to zero; enlarge the area or charge')
    n = nu*nv
    micro, remainder = divmod(q*1_000_000,n)
    first = [(micro+(i<remainder))/1e6 for i in range(n)]
    return dict(axis=axis,cell_nm=cell,positions_nm=positions,charges=first+[-v for v in first],
                sites_per_electrode=n,working_charge_e=q,
                realized_working_C_m2=q*E_PER_NM2_TO_C_M2/(width*depth),vacuum_factor=vacuum_factor)


def build_qualification_package(destination, spec, *, salt_mM=300., temperature_K=298.15, seed=17, vacuum_factor=3., design=None, atomistic_model=None, mg_mM=0., peg=None, water_oxygen_clearance_nm=.32):
    """Build an isolated control; destination must not exist. May invoke GROMACS."""
    if not math.isfinite(salt_mM) or not 0 <= salt_mM <= 1000 or not math.isfinite(temperature_K) or not 250 <= temperature_K <= 400:
        raise ValueError('Use salt 0–1000 mM and temperature 250–400 K')
    if not math.isfinite(water_oxygen_clearance_nm) or not .15 <= water_oxygen_clearance_nm <= .5:
        raise ValueError('Water oxygen clearance must be within 0.15–0.5 nm')
    layout = electrode_layout(spec, vacuum_factor)
    dest = Path(destination)
    if dest.exists():
        raise ValueError('Qualification destination already exists; choose a new directory')
    solvate._check_ff_files()
    dna_psf = complete_psf(Design())
    dna_pdb = ''
    dna_atoms = 0
    if design is not None and design.strands:
        topology = solvate.build_charmm_psfgen_topology(design, atomistic_model=atomistic_model)
        dna_psf, dna_pdb = topology.psf_text, topology.pdb_text
        atom_rows = [r for r in dna_pdb.splitlines() if r.startswith(('ATOM  ', 'HETATM'))]
        dna_atoms = len(atom_rows)
        xyz = [[float(r[i:i+8])/10 for i in (30,38,46)] for r in atom_rows]
        low = [min(p[i] for p in xyz) for i in range(3)]
        high = [max(p[i] for p in xyz) for i in range(3)]
        if any(high[i]-low[i]+.8 > layout['cell_nm'][i] for i in range(3)):
            raise ValueError('DNA does not fit between electrodes with 0.4 nm clearance; increase gap/width/depth.')
        delta = [10*(layout['cell_nm'][i]-high[i]-low[i])/2 for i in range(3)]
        dna_pdb = '\n'.join(r[:30]+''.join(f'{float(r[30+8*i:38+8*i])+delta[i]:8.3f}' for i in range(3))+r[54:] for r in atom_rows)
    dna_count=dna_atoms
    peg_manifest=None
    if peg and peg.get('enabled'):
        from backend.core.namd_electrode_peg import append_peg
        dna_psf,dna_pdb,peg_manifest=append_peg(dna_psf,dna_pdb,peg['spec'],layout)
        dna_pdb='\n'.join(r for r in dna_pdb.splitlines() if r.startswith(('ATOM  ','HETATM')))
        dna_atoms=len(dna_pdb.splitlines())
    lines = [dna_pdb] if dna_pdb else []
    for index,p in enumerate(layout['positions_nm']):
        seg,resid = solvate._graphene_identity(index)
        lines.append(solvate._hetatm_record(dna_atoms+index+1,'C','GRP','G',resid,*(10*v for v in p),segname=seg))
    dry = '\n'.join(lines)+'\nEND\n'
    with tempfile.TemporaryDirectory(prefix='nadoc_electrode_water_') as tmp:
        waters, cell, dry = solvate._gmx_solvate(dry,0,Path(tmp),box_mode='bbox',box_size_nm=tuple(layout['cell_nm']))
    axis = layout['axis']
    # Carbon/oxygen nonbonded clearance is measured to the oxygen center.
    # Requiring the same clearance for zero-LJ TIP3P hydrogens over-carves solvent.
    # Keep/delete whole molecules; a 0.32 nm oxygen clearance also keeps H inside.
    waters = [w for w in waters if water_oxygen_clearance_nm < getattr(w,('ox','oy','oz')[axis]) < cell[axis]-water_oxygen_clearance_nm]
    if not waters:
        raise ValueError('No accessible water remains')
    ions = solvate.ion_counts(len(waters),solvate._count_dna_charge(dry),nacl_mM=salt_mM,mgcl2_mM=mg_mM,box_nm=cell,mg_hexahydrate=True)
    waters,na,mg,cl,mgh = solvate._place_ions_mixed(waters,ions.n_na,ions.n_mg,ions.n_cl,seed=seed,mg_hexahydrate=True,dna_pdb_text=dry)
    count = len(layout['positions_nm'])
    psf = solvate._extend_psf(dna_psf,waters,na,cl,mg_pos=mg,mgh_clusters=mgh,graphene_atoms=count)
    rows = psf.splitlines()
    start = next(i for i,row in enumerate(rows) if '!NATOM' in row)
    total = int(rows[start].split()[0])
    for i,q in enumerate(layout['charges']):
        parts = rows[start+dna_atoms+i+1].split(); parts[6]=f'{q:.6f}'; rows[start+dna_atoms+i+1]=' '.join(parts)
    psf = '\n'.join(rows)+'\n'
    charges = [float(row.split()[6]) for row in rows[start+1:start+1+total]]
    pdb = solvate._build_solvated_pdb(dry,waters,na,cl,cell,dna_atoms+count,mg_pos=mg,mgh_clusters=mgh)
    padded = list(cell); padded[axis] *= vacuum_factor
    shift = (padded[axis]-cell[axis])*5 # Å
    shifted, restraint = [], []
    for row in pdb.splitlines():
        if row.startswith('CRYST1'):
            row = f'CRYST1{padded[0]*10:9.3f}{padded[1]*10:9.3f}{padded[2]*10:9.3f}  90.00  90.00  90.00 P 1           1'
        if row.startswith(('ATOM  ','HETATM')):
            offset = 30+8*axis
            row = row[:offset]+f'{float(row[offset:offset+8])+shift:8.3f}'+row[offset+8:]
        shifted.append(row)
        if row.startswith(('ATOM  ','HETATM')):
            k = 10. if row[17:21].strip() == 'GRP' else 0.
            row = row[:60]+f'{k:6.2f}'+row[66:]
        restraint.append(row)
    slab = render_slab_tcl(charges,[10*v for v in padded],axis,mobile_ids=[*range(1,dna_atoms+1),*range(dna_atoms+count+1,total+1)],bounds=(shift,shift+cell[axis]*10))
    manifest = dict(schema='nadoc.two_electrode_qualification.v1',spec=spec,cell_nm=padded,normal_axis=axis,
                    vacuum_factor=vacuum_factor,electrostatics='PME + Yeh–Berkowitz EW3DC; fixed-volume',
                    dna_atoms=dna_count,solute_atoms=dna_atoms,mg_mM=mg_mM,salt_mM=salt_mM,temperature_K=temperature_K,seed=seed,n_atoms=total,n_waters=len(waters),
                    n_na=len(na),n_cl=len(cl),sites_per_electrode=layout['sites_per_electrode'],
                    working_charge_e=layout['working_charge_e'],realized_working_C_m2=layout['realized_working_C_m2'],
                    total_charge_e=math.fsum(charges),qualified=False,normal_bounds_A=[shift,shift+cell[axis]*10],water_oxygen_clearance_nm=water_oxygen_clearance_nm)
    dest.mkdir(parents=True)
    (dest/'forcefield').mkdir(); (dest/'output').mkdir()
    if peg_manifest:
        (dest/'forcefield'/'par_all35_ethers.prm').write_text(peg_manifest.pop('parameter_text'))
        manifest['peg']=peg_manifest
    for name in solvate._FF_FILES:
        shutil.copy2(solvate._FF_DIR/name,dest/'forcefield'/name)
    extrabonds=solvate._mgh_extrabonds(dna_atoms+count,len(waters),len(na),len(mg),len(mgh))
    if extrabonds:(dest/'mgh_extrabonds.txt').write_text(extrabonds)
    audit=solvate.audit_psf(psf,require_neutral=True,require_dna_hydrogens=bool(dna_count),require_dna_residue_charge=bool(dna_count))
    if not audit.passed:raise ValueError('Electrode topology audit failed: '+'; '.join(audit.errors))
    (dest/'charge_audit.json').write_text(json.dumps({'production_ready':True,'graphene_only':not bool(dna_count),'final_solvated':audit.to_dict()},indent=2))
    (dest/'system.psf').write_text(psf)
    (dest/'system.pdb').write_text('\n'.join(shifted)+'\n')
    (dest/'restraints.pdb').write_text('\n'.join(restraint)+'\n')
    (dest/'slab.tcl').write_text(slab)
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def qualification_config(manifest, *, resident=False, correction=True, steps=0, timestep_fs=2., minimize=0, prefix='probe'):
    """Native qualification only. Every stage explicitly retains slab/confinement."""
    if not correction:
        raise ValueError('Use correction-delta probes separately; never omit confinement from dynamics')
    if steps < 0 or minimize < 0 or timestep_fs not in (1.,2.,4.):
        raise ValueError('Invalid qualification integration parameters')
    cell = [v*10 for v in manifest['cell_nm']]
    return f'''structure system.psf
coordinates system.pdb
paraTypeCharmm on
parameters forcefield/par_all36_na.prm
parameters forcefield/par_all36m_prot.prm
parameters forcefield/par_np_thiol.prm
parameters forcefield/toppar_water_ions_cufix.str
parameters forcefield/par_stub_ions_nbfix.str
cellBasisVector1 {cell[0]} 0 0
cellBasisVector2 0 {cell[1]} 0
cellBasisVector3 0 0 {cell[2]}
cellOrigin {cell[0]/2} {cell[1]/2} {cell[2]/2}
wrapAll off
wrapWater off
PME on
PMEGridSpacing 1.0
PMETolerance 1e-6
cutoff 12
switching on
switchdist 10
pairlistdist 16
exclude scaled1-4
1-4scaling 1.0
dielectric 1.0
rigidBonds all
rigidTolerance 1e-8
constraints on
consref restraints.pdb
conskfile restraints.pdb
conskcol B
constraintScaling 1.0
tclForces on
tclForcesScript slab.tcl
GPUresident {'on' if resident else 'off'}
timestep {timestep_fs}
stepspercycle 20
nonbondedFreq 1
fullElectFrequency 1
langevin on
langevinTemp {manifest['temperature_K']}
langevinDamping 1
langevinHydrogen off
temperature {manifest['temperature_K']}
seed {manifest['seed']}
outputName output/{prefix}
outputEnergies 20
restartfreq 1000
dcdfreq 20
binaryoutput yes
{'minimize '+str(minimize) if minimize else ''}
run {steps}
output onlyforces output/{prefix}
'''
