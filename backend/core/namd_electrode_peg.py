"""Existing CHARMM ether chain builder adapted to a fixed electrode compartment."""
import math
import os
from pathlib import Path
import shutil
import tempfile
import numpy as np
from scipy.spatial import cKDTree
from experiments.peg_wall.build import ASSET_HASHES, chain_script, sha256, vmd
from backend.core.namd_peg_wall import RepulsiveSlit


def append_peg(psf, pdb, spec, layout):
    if spec.get('representation','atomistic')!='atomistic':raise ValueError('Electrode protocol requires explicit atomistic PEG.')
    if spec.get('shape','square')!='square':raise ValueError('Electrode PEG currently requires a square patch.')
    if spec.get('end_groups') or spec.get('topology_reference') or spec.get('parameter_reference'):
        raise ValueError('Electrode PEG uses the validated methyl-capped CHARMM ether model; custom chemistry/references are not implemented.')
    size=float(spec['size_nm']);density=float(spec['density_per_nm2']);repeat=int(spec['repeat_units'])
    if not math.isfinite(size) or not math.isfinite(density) or size<=0 or density<=0:raise ValueError('Invalid PEG patch size/density')
    count=int(math.floor(size*size*density+.5));grid=math.ceil(math.sqrt(count))
    if not 1<=count<=64:raise ValueError('Initial electrode PEG builder supports 1–64 chains per patch.')
    axis=layout['axis'];lateral=[i for i in range(3) if i!=axis]
    if size>min(layout['cell_nm'][i] for i in lateral):raise ValueError('PEG patch exceeds electrode dimensions.')
    assets=Path(os.environ.get('NADOC_PEG_ETHER_ASSETS','workspace/peg_wall_validation/assets/toppar_ether')).resolve()
    for name,digest in ASSET_HASHES.items():
        if not (assets/name).is_file() or sha256(assets/name)!=digest:raise ValueError(f'Missing pinned CHARMM ether asset {name}; set NADOC_PEG_ETHER_ASSETS.')
    with tempfile.TemporaryDirectory(prefix='nadoc_electrode_peg_') as temp:
        folder=Path(temp)
        for name in ASSET_HASHES:shutil.copy2(assets/name,folder/name)
        slit=RepulsiveSlit((size,size,layout['cell_nm'][axis]),inset_nm=.2)
        script=chain_script(repeat,grid,slit,.2)
        # Remove unused grid sites before writing topology; preserve whole chains.
        removal='\n'.join(f'delatom P{i:03d}' for i in range(count,grid*grid))
        script=script.replace('regenerate angles dihedrals',removal+'\nregenerate angles dihedrals')
        vmd(script,folder,'peg')
        rows=[r for r in (folder/'dry.pdb').read_text().splitlines() if r.startswith(('ATOM  ','HETATM'))]
        transformed=[];positions=[]
        for row in rows:
            p=[float(row[i:i+8]) for i in (30,38,46)];q=[0.,0.,0.]
            q[axis]=p[2]
            for j,k in enumerate(lateral):q[k]=p[j]+5*(layout['cell_nm'][k]-size)
            positions.append(q);transformed.append(row[:30]+''.join(f'{v:8.3f}' for v in q)+row[54:])
        dna_rows=[r for r in pdb.splitlines() if r.startswith(('ATOM  ','HETATM'))]
        if dna_rows:
            dna=np.array([[float(r[i:i+8]) for i in (30,38,46)] for r in dna_rows])
            if np.min(cKDTree(dna).query(positions)[0])<2.:
                raise ValueError('Initial PEG overlaps DNA; increase electrode gap or reduce PEG length/density before preparing.')
        (folder/'peg.pdb').write_text('\n'.join(transformed)+'\nEND\n')
        (folder/'dna.psf').write_text(psf);(folder/'dna.pdb').write_text(pdb+'\nEND\n')
        merge='package require psfgen\nresetpsf\n'
        if dna_rows:merge+='readpsf dna.psf\ncoordpdb dna.pdb\n'
        merge+='readpsf dry.psf\ncoordpdb peg.pdb\nwritepsf combined.psf\nwritepdb combined.pdb\n'
        vmd(merge,folder,'merge')
        return (folder/'combined.psf').read_text(),(folder/'combined.pdb').read_text(),{
            'chains':count,'repeat_units':repeat,'graft_k_kcal_mol_A2':5.,'chemistry':'methyl-capped CHARMM PEGM',
            'asset_hashes':ASSET_HASHES,'parameter_text':(assets/'par_all35_ethers.prm').read_text()}
