"""Fresh corrected anti endpoint graphs and finite, screened QM starting seeds.

The verified TTD graph supplies D-deoxyribose stereochemistry, not anti coordinates.
No phosphodiester or legacy anti boundary geometry is used. UFF only prepares seeds.
"""
from __future__ import annotations

from pathlib import Path
import sys
import shutil
import traceback

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR, checked, geometry_audit as core_audit, now, pin, read, save, xyz,
)

ROOT = (REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
CENTERS = ('C1\'', 'C3\'', 'C4\'')
SUGAR_CCD = {
    1: {"C1'":"C1'", "C2'":"C2'", "C3'":"C3R", "C4'":"C4R",
        "C5'":"C5'", "O3'":"O3R", "O4'":"O4'", "O5'":"O5'"},
    2: {"C1'":"C1R", "C2'":"C2R", "C3'":"C3'", "C4'":"C4'",
        "C5'":"C5R", "O3'":"O3'", "O4'":"O4R", "O5'":"O5R"},
}
H_NAMES = {'N3':['H3'], 'C6':['H6'], 'C7':['H51','H52','H53'],
           'CM':['HCM1','HCM2','HCM3'], "C1'":["H1'"],
           "C2'":["H2'","H2''"], "C3'":["H3'"], "C4'":["H4'"],
           "C5'":["H5'","H5''"], "O3'":["HO3'"], "O5'":["HO5'"]}


def build_graph(full, definition, endpoint):
    from rdkit import Chem
    other = 3-endpoint
    mapping = {v:f"{e['index']}:{k}" for e in definition['ordered_endpoints']
               for k,v in e['ccd_atom_aliases'].items() if not k.startswith('H')}
    mapping.update({v:f'{endpoint}:{k}' for k,v in SUGAR_CCD[endpoint].items()})
    mapping[SUGAR_CCD[other]["C1'"]] = f'{other}:CM'
    # RemoveHs and RemoveAtom preserve tag parity. Coordinates are discarded.
    heavy = Chem.RemoveHs(Chem.Mol(full)); edit = Chem.RWMol(heavy)
    for i in reversed(range(heavy.GetNumAtoms())):
        if heavy.GetAtomWithIdx(i).GetProp('ccd_atom_id') not in mapping:
            edit.RemoveAtom(i)
    fragment = edit.GetMol()
    for atom in fragment.GetAtoms():
        atom.SetProp('stable_key', mapping[atom.GetProp('ccd_atom_id')])
        if atom.GetProp('stable_key') == f'{other}:CM':
            atom.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
    Chem.SanitizeMol(fragment)
    Chem.AssignStereochemistry(fragment, cleanIt=True, force=True)
    fragment.RemoveAllConformers()
    fragment = Chem.AddHs(fragment)
    counts = {}
    for atom in fragment.GetAtoms():
        if atom.GetSymbol() != 'H':
            continue
        parent = atom.GetNeighbors()[0].GetProp('stable_key')
        ep,name = parent.split(':'); count=counts.get(parent,0)
        atom.SetProp('stable_key', ep+':'+H_NAMES[name][count]);counts[parent]=count+1
    keys = [a.GetProp('stable_key') for a in fragment.GetAtoms()]
    assert len(keys)==49 and len(set(keys))==49 and fragment.GetNumBonds()==52
    assert Chem.GetFormalCharge(fragment)==0
    assert not any(a.GetSymbol()=='P' for a in fragment.GetAtoms())
    assert all(a.GetTotalValence()=={'C':4,'N':3,'O':2,'H':1}[a.GetSymbol()]
               for a in fragment.GetAtoms())
    return fragment,keys


def audit_endpoint(x_bohr, plan):
    from rdkit import Chem
    report = core_audit(x_bohr, plan)
    molecule = Chem.MolFromMolFile(str(checked(plan['sdf'])), removeHs=False)
    keys = plan['atom_keys']; ep=plan['endpoint']
    ids = [keys.index(f'{ep}:{name}') for name in CENTERS]
    expected = [molecule.GetAtomWithIdx(i).GetChiralTag() for i in ids]
    for i,pos in enumerate(np.asarray(x_bohr)*BOHR):
        molecule.GetConformer().SetAtomPosition(i,tuple(pos))
    Chem.AssignAtomChiralTagsFromStructure(molecule, replaceExistingTags=True)
    actual = [molecule.GetAtomWithIdx(i).GetChiralTag() for i in ids]
    report['sugar_centers'] = [dict(atom=keys[i],expected_tag=str(e),actual_tag=str(a),
                                  preserved=e==a and e!=Chem.ChiralType.CHI_UNSPECIFIED)
                              for i,e,a in zip(ids,expected,actual)]
    report['passed'] = bool(report['passed'] and all(v['preserved'] for v in report['sugar_centers']))
    return report


def prepare():
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdCIPLabeler
    from backend.parameterization.photoproduct_models import _ccd_atom_rows
    from backend.parameterization.photoproduct_fragments import _model_graph
    from backend.parameterization.photoproduct_stereo_candidates import _candidate_full_molecule, _cip_codes
    minimum = read(ROOT/'core_local_minimum_assessment.json')
    assert minimum['minimum_certified']
    base = read(ROOT/'optimization/plan.json')
    sources = {Path(v['path']).name:v for v in base['sources']}
    source = Chem.MolFromMolFile(str(checked(sources['TTD_ideal.sdf'])), removeHs=False)
    for atom,row in zip(source.GetAtoms(),_ccd_atom_rows(checked(sources['TTD.cif'])),strict=True):
        atom.SetProp('ccd_atom_id', row['_chem_comp_atom.atom_id'])
    full = _candidate_full_molecule(source,'cis-anti-I')
    cip = _cip_codes(full)
    assert cip==dict(zip(('C5','C6','C5T','C6T'),('S','R','S','R')))
    canonical = read(REPO/'backend/data/forcefield/photoproducts/tt-cpd-cis-syn/chemical_definition.json')
    core_x = np.load(checked(minimum['geometry']))*BOHR
    core_coords = dict(zip(base['atom_keys'],core_x))
    root = ROOT/'endpoint-seeds-v2';root.mkdir(exist_ok=False)
    shutil.copy2(Path(__file__),root/'executed_source.py')
    records=[]
    for endpoint in (1,2):
        folder=root/f'endpoint-{endpoint}';folder.mkdir()
        molecule,keys=build_graph(full,canonical,endpoint)
        elements=[a.GetSymbol() for a in molecule.GetAtoms()]
        fixed={i:core_coords[k] for i,k in enumerate(keys) if k in core_coords}
        assert len(fixed)==32
        expected_tags={i:a.GetChiralTag() for i,a in enumerate(molecule.GetAtoms())
                       if a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED}
        assert len(expected_tags)==7
        attempts=[];selected=None
        for attempt in range(3):
            out=folder/f'seed-{attempt+1}';out.mkdir()
            try:
                mol=Chem.Mol(molecule)
                params=AllChem.ETKDGv3();params.randomSeed=76130+endpoint*10+attempt
                params.useRandomCoords=True;params.enforceChirality=True;params.numThreads=1
                params.maxIterations=1000
                status=AllChem.EmbedMolecule(mol,params)
                if status!=0:raise RuntimeError(f'Embedding failed: {status}')
                # Embed the explicit stereochemical graph freely before grafting
                # the certified core; tight H-containing distance bounds failed v1.
                AllChem.UFFOptimizeMolecule(mol,maxIters=1000)
                x=np.asarray(mol.GetConformer().GetPositions());ids=list(fixed)
                align_ids=[i for i in ids if elements[i]!='H']
                target=np.array([fixed[i] for i in align_ids]);p=x[align_ids].mean(0);q=target.mean(0)
                u,_,vt=np.linalg.svd((x[align_ids]-p).T@(target-q))
                rot=u@np.diag([1,1,np.linalg.det(u@vt)])@vt
                x=(x-p)@rot+q
                for i,v in fixed.items():x[i]=v
                for i,v in enumerate(x):mol.GetConformer().SetAtomPosition(i,tuple(v))
                before=x.copy()
                ff=AllChem.UFFGetMoleculeForceField(mol)
                for i in fixed:ff.AddFixedPoint(i)
                ff.Initialize();energy_before=ff.CalcEnergy();uff=ff.Minimize(maxIts=1500)
                x=np.asarray(mol.GetConformer().GetPositions())
                np.save(out/'geometry_angstrom.npy',x)
                (out/'seed.xyz').write_text(xyz(elements,x/BOHR,'Fresh corrected endpoint; UFF seed only'))
                observed=Chem.Mol(mol);Chem.AssignAtomChiralTagsFromStructure(observed,replaceExistingTags=True)
                if any(observed.GetAtomWithIdx(i).GetChiralTag()!=tag for i,tag in expected_tags.items()):
                    raise ValueError('Coordinate stereochemistry differs from corrected source graph')
                writer=Chem.SDWriter(str(out/'seed.sdf'));writer.write(mol);writer.close()
                model=dict(endpoint=endpoint,atom_keys=keys,elements=elements,
                           definition=base['definition'],sdf=pin(out/'seed.sdf'))
                audit=audit_endpoint(x/BOHR,model)
                if not audit['passed']:raise ValueError(f'Geometry screening failed: {audit}')
                if np.max(abs(x[ids]-before[ids]))>1e-12:raise ValueError('Frozen core changed')
                rdCIPLabeler.AssignCIPLabels(observed)
                graph=_model_graph(mol,keys);save(out/'model_graph.json',graph)
                save(out/'atom_map.json',keys)
                save(out/'audit.json',dict(at=now(),passed=True,geometry=audit,uff_status=uff,
                    uff_energy_before=energy_before,uff_energy_after=ff.CalcEnergy(),
                    fixed_core_atoms=32,fixed_core_max_displacement_angstrom=float(np.max(abs(x[ids]-before[ids]))),
                    full_source_graph_cip=cip,coordinate_cip={keys[i]:observed.GetAtomWithIdx(i).GetProp('_CIPCode') for i in expected_tags},
                    formal_charge=0,multiplicity=1,valences_checked=True,atoms=49,bonds=52,
                    minimum_certified=False,scope='Graph and seed screen only; UFF energy is not QM evidence.'))
                selected=dict(**model,geometry=pin(out/'geometry_angstrom.npy'),xyz=pin(out/'seed.xyz'),
                              graph=pin(out/'model_graph.json'),audit=pin(out/'audit.json'))
                attempts.append(dict(attempt=attempt+1,passed=True,audit=selected['audit']))
                break
            except Exception as exc:
                save(out/'failure.json',dict(at=now(),error=repr(exc),traceback=traceback.format_exc()))
                attempts.append(dict(attempt=attempt+1,passed=False,failure=pin(out/'failure.json')))
        save(folder/'attempts.json',attempts)
        if selected is None:raise RuntimeError(f'No screened endpoint {endpoint} seed in three finite attempts')
        save(folder/'model_manifest.json',dict(**selected,at=now(),status='quantitatively_screened_seed',
            product_id='tt-cpd-cis-anti-i',cap_review=dict(retained_endpoint=endpoint,
            five_prime='O5\'-H',three_prime='O3\'-H',other_endpoint='neutral N1-methyl',
            protonation='neutral canonical lactam; no phosphate',formal_charge=0),
            coverage='Both complete CPD bases plus one full D-deoxyribose and opposite N1-methyl; contains local glycosidic/sugar coupling, excludes phosphodiester and two-sugar coupling.',
            source_policy='Fresh graph from parity-corrected TTD; all source conformers discarded. Only certified corrected core coordinates reused.',
            minimum_certified=False,simulation_ready=False,registry_gate_effect='none',human_chemical_review='pending'))
        records.append(pin(folder/'model_manifest.json'))
    save(root/'assessment.json',dict(at=now(),passed=True,models=records,core_minimum=pin(ROOT/'core_local_minimum_assessment.json'),
        sources=[sources['TTD_ideal.sdf'],sources['TTD.cif'],base['definition'],pin(root/'executed_source.py'),
                 pin(REPO/'backend/parameterization/photoproduct_stereo_candidates.py'),
                 pin(REPO/'backend/parameterization/photoproduct_fragments.py'),
                 pin(REPO/'backend/parameterization/photoproduct_models.py')],
        new_qm_evaluations=0,human_review_record=None,registry_gate_effect='none',simulation_ready=False))
    print(root)


if __name__=='__main__':
    prepare()
