"""Isolated psfgen reconstruction and chemically mapped sugar reference audit.

No parameter fitting, energy optimization, source design mutation or promotion.
Only four coordinates per case can be replaced by native guesscoord output.
"""
from pathlib import Path
import sys
import re
import shutil

import numpy as np
from openmm import app, unit as u

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary
from experiments.cpd_anti_additive.review_source_conditioning_v1 import signed_volume
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry
from backend.parameterization.photoproduct_candidate_context import _run_psfgen
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-source-stereo-repair-v1b'
PRIOR=ART/'cpd-anti-solvated-construction-v1c'
TOPO=ART/'cpd-anti-dna-topology-v2b'
PSFGEN=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/psfgen')
ORDER={"C1'":["O4'","C2'",'GLY',"H1'"],
       "C3'":["C2'","C4'","O3'","H3'"],
       "C4'":["C3'","C5'","O4'","H4'"]}


def main():
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__),ROOT/'executed_source.py')
    paths=[PRIOR/'independent_review.json',PRIOR/'inputs_lock.json',
        TOPO/'reactant.tcl',TOPO/'anti.tcl',TOPO/'reactant.pdb',TOPO/'anti_dna.rtf',
        REPO/'backend/data/forcefield/top_all36_na.rtf',PSFGEN,ROOT/'executed_source.py',
        ART/'cpd-anti-source-stereo-repair-v1/preparation_failure.json']
    qm=[]
    for ep in (1,2):
        folder=ART/f'cpd-anti-conformational-fit-v2-r1/candidate/endpoint-{ep}'
        paths.extend([folder/'starting_A.txt',folder/'atom_map.json'])
        names=read(folder/'atom_map.json');x=np.loadtxt(folder/'starting_A.txt');rows={}
        for center,ns in ORDER.items():
            ids=[names.index(f'{ep}:'+('N1' if n=='GLY' else n)) for n in ns]
            rows[center]=dict(canonical_names=ns,volume_A3=signed_volume(x[ids]),dihedral_deg=_dihedral(*x[ids]))
        qm.append(dict(endpoint=ep,reference=source(folder/'starting_A.txt'),centers=rows))
    for center in ORDER:
        assert qm[0]['centers'][center]['volume_A3']*qm[1]['centers'][center]['volume_A3']>0
    save(ROOT/'chemical_references.json',dict(method='Same ordered four-neighbor geometry as original QM deoxyriboses; GLY=N1 for pyrimidine and N9 for purine. Geometric chirality signs, not uncomputed CIP labels.',references=qm))
    for label in ['anti','control']:
        for name in ['start.coor','solute.psf','geometry_reference.json','source_A.txt']:
            paths.append(PRIOR/label/name)
    save(ROOT/'plan.json',dict(created_at=now(),scope='Four-coordinate psfgen seed reconstruction and chemistry-reference repair only; no MM/QM calculation',
        sources=[source(p) for p in paths],sites=['D000:7','D002:26'],atoms=["O3'","H3'"],
        algorithm='Omit exactly four atoms from the coordinate input, retain original segment/patch Tcl, call native psfgen guesscoord using CHARMM internal-coordinate hints, merge only the four regenerated coordinates into original double-precision seed.',
        reference_correction='All sugar neighbor signs follow the two original QM deoxyriboses, rather than copying a potentially incorrect source sign. Source-relative historical reports remain unchanged.',
        limits=dict(native_guesscoord_calls=2,parameter_changes=0,other_coordinate_changes=0,new_energy_evaluations=0),
        acceptance=['Exact solute atom identity and bonded topology', 'All 288 chemically mapped sugar signs and ten anti QM references correct',
                    'No unchanged atom coordinate drift; full bond/contact/junction failures explicitly reported'],
        gate_scope='Seed/reference pass is not a construction, stationarity, engine, product placement or research-qualification pass.',
        documentation='https://www.ks.uiuc.edu/Research/vmd/plugins/psfgen/ug.pdf',simulation_ready=False))
    pdb_template=[l for l in (TOPO/'reactant.pdb').read_text().splitlines() if l.startswith(('ATOM  ','HETATM'))]
    assert len(pdb_template)==3043
    reports=[]
    for label in ['anti','control']:
        folder=ROOT/label;folder.mkdir();segments=folder/'segments';segments.mkdir()
        psf=app.CharmmPsfFile(str(PRIOR/label/'solute.psf'));atoms=psf.atom_list
        raw=(PRIOR/label/'solute.psf').read_text().splitlines()
        offset=next(i for i,line in enumerate(raw) if '!NATOM' in line)+1
        raw_names=[line.split()[4] for line in raw[offset:offset+3043]]
        x=read_binary(PRIOR/label/'start.coor',30867).copy()
        targets=[a.idx for a in atoms if (a.system,a.residue.idx) in [('D000',7),('D002',26)] and a.name in ("O3'","H3'")]
        assert len(targets)==4
        for segment in sorted({a.system for a in atoms}):
            lines=[]
            for atom,line in zip(atoms,pdb_template):
                if atom.system!=segment or atom.idx in targets:continue
                assert line[12:16].strip()==raw_names[atom.idx]
                lines.append(line[:30]+''.join(f'{v:8.3f}' for v in x[atom.idx])+line[54:])
            (segments/f'{segment}.pdb').write_text('\n'.join(lines)+'\nEND\n')
        script=(TOPO/('anti.tcl' if label=='anti' else 'reactant.tcl')).read_text()
        for segment in sorted({a.system for a in atoms}):
            script=re.sub(r'\S+/segments/'+segment+r'\.pdb',str((segments/f'{segment}.pdb').resolve()),script)
        script=re.sub(r'^writepsf .*$',f'writepsf {(folder/"regenerated.psf").resolve()}',script,flags=re.M)
        script=re.sub(r'^writepdb .*$',f'writepdb {(folder/"regenerated.pdb").resolve()}',script,flags=re.M)
        (folder/'build.tcl').write_text(script)
        _run_psfgen(PSFGEN,script,folder.resolve(),folder/'psfgen.log')
        generated=app.CharmmPsfFile(str(folder/'regenerated.psf'))
        assert [(a.system,a.residue.idx,a.name,a.attype) for a in generated.atom_list]==[(a.system,a.residue.idx,a.name,a.attype) for a in atoms]
        for attr,n in [('bond_list',2),('angle_list',3),('dihedral_list',4),('improper_list',4)]:
            def records(p):
                return [tuple(getattr(r,f'atom{i}').idx for i in range(1,n+1)) for r in getattr(p,attr)]
            assert records(generated)==records(psf),attr
        coords=np.array(app.PDBFile(str(folder/'regenerated.pdb')).positions.value_in_unit(u.angstrom))
        y=x.copy();y[targets]=coords[targets]
        assert np.array_equal(x[np.setdiff1d(np.arange(len(x)),targets)],y[np.setdiff1d(np.arange(len(x)),targets)])
        binary(folder/'candidate.coor',y);np.savetxt(folder/'candidate_solute_A.txt',y[:3043])
        np.savetxt(folder/'seed_solute_A.txt',x[:3043]);shutil.copyfile(PRIOR/label/'source_A.txt',folder/'source_A.txt')
        spec=read(PRIOR/label/'geometry_reference.json');old_centers=spec['centers'];centers=[]
        for residue in psf.residue_list:
            ids={a.name:a.idx for a in residue.atoms};gly='N9' if 'N9' in ids else 'N1'
            for center,ns in ORDER.items():
                mapped=[ids[gly if n=='GLY' else n] for n in ns]
                reference=qm[0]['centers'][center]
                centers.append(dict(label=f'{residue.system}:{residue.idx}:{center}',indices=mapped,
                    reference_A3=reference['volume_A3'],source_volume_A3=signed_volume(x[mapped]),
                    candidate_volume_A3=signed_volume(y[mapped]),reference_kind='Original QM canonical sugar neighbors'))
        assert len(centers)==288
        centers.extend(r for r in old_centers if r['label'].startswith('QM:'))
        spec['centers']=centers;save(folder/'geometry_reference.json',spec)
        old=geometry(folder,x);new=geometry(folder,y)
        edits=[dict(atom=f'{atoms[i].system}:{atoms[i].residue.idx}:{atoms[i].name}',index=i,before_A=x[i].tolist(),after_A=y[i].tolist(),displacement_A=float(np.linalg.norm(y[i]-x[i]))) for i in targets]
        report=dict(case=label,seed_reference_failed_centers=old['inverted_centers'],chemically_mapped_stereo_passed=new['stereo_passed'],
            geometry=new,edits=edits,only_four_atoms_changed=True,solute_topology_unchanged=True,
            original_high_precision_PSF_is_authoritative=True,regenerated_PSF_is_comparison_only=True,
            optimization_performed=False,minimum_certified=False,simulation_ready=False)
        save(folder/'assessment.json',report);reports.append(report)
        print(label,'chemical stereo',new['stereo_passed'],'wrong',new['inverted_centers'],'bonds',new['bond_ratio_range'],'clashes',new['contacts']['severe_clash_count'],flush=True)
    save(ROOT/'assessment.json',dict(created_at=now(),plan=source(ROOT/'plan.json'),cases=[source(ROOT/r['case']/'assessment.json') for r in reports],
        stereo_seed_repair_passed=all(r['chemically_mapped_stereo_passed'] for r in reports),
        construction_passed=False,new_energy_evaluations=0,minimum_certified=False,simulation_ready=False))


if __name__=='__main__':main()
