"""Read-only RDKit re-audit of existing TT-CPD candidates and recent probe inputs.
No stereoisomer enumeration, coordinate construction, optimization or promotion.
"""
from pathlib import Path
import sys,json,hashlib
from datetime import datetime,timezone
import numpy as np
from rdkit import Chem,rdBase
from rdkit.Chem import rdCIPLabeler
REPO=Path('/home/jojo/Work/NADOC');sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked,read,BOHR
BASE=Path('/media/jojo/Archive/NADOC_archive/runtime/development-artifacts')
OLD=BASE/'cpd-anti-definition-correction-v1/constructed'
PROBE=BASE/'cpd-cis-anti-i-bounded-sensitivity-v1/directional-energy-v1'
OUT=BASE/'cpd-rdkit-identity-review-20261017'
def pin(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def perceive(m):
    m=Chem.Mol(m)
    Chem.RemoveStereochemistry(m)
    Chem.AssignStereochemistryFrom3D(m,replaceExistingTags=True)
    rdCIPLabeler.AssignCIPLabels(m)
    return m

def compare(m,keys,definition):
    m=perceive(m);x=np.asarray(m.GetConformer().GetPositions());centers=[]
    for rec in definition['product_stereocenters']:
        k=rec['atom'];ids=[keys.index(n) for n in rec['signed_volume_reference_atoms']];i=keys.index(k)
        value=float(np.linalg.det(x[ids]-x[i]));sign='positive' if value>0 else 'negative'
        atom=m.GetAtomWithIdx(i)
        centers.append(dict(atom=k,signed_volume=value,expected_sign=rec['expected_signed_volume'],
            coordinate_CIP=atom.GetProp('_CIPCode') if atom.HasProp('_CIPCode') else None,
            passed=sign==rec['expected_signed_volume'] and abs(value)>1e-4))
    # Stored parity and newly perceived parity use identical atom/neighbor ordering.
    links=[['1:C5','2:C6'],['1:C6','2:C5']] if '-anti-' in definition['id'] else [['1:C5','2:C5'],['1:C6','2:C6']]
    forbidden=[['1:C5','2:C5'],['1:C6','2:C6']] if '-anti-' in definition['id'] else [['1:C5','2:C6'],['1:C6','2:C5']]
    connectivity=all(m.GetBondBetweenAtoms(keys.index(a),keys.index(b)) is not None for a,b in links) and all(m.GetBondBetweenAtoms(keys.index(a),keys.index(b)) is None for a,b in forbidden)
    return dict(centers=centers,connectivity_passed=connectivity,passed=connectivity and all(c['passed'] for c in centers))

def main():
    assert Path('/media/jojo/Archive').is_mount();OUT.mkdir(exist_ok=True)
    historical=read(OLD/'audit.json');records=[]
    for rec in historical['records']:
        product=rec['product_id'];dpath=REPO/'backend/data/forcefield/photoproducts'/product/'chemical_definition.json';d=read(dpath)
        sdf=checked(rec['sdf']);keys=read(checked(rec['atom_map']));m=Chem.MolFromMolFile(str(sdf),removeHs=False)
        actual=perceive(m);ring=[keys.index(k) for k in ['1:C5','1:C6','2:C5','2:C6']]
        parity=all(actual.GetAtomWithIdx(i).GetChiralTag()==m.GetAtomWithIdx(i).GetChiralTag() for i in ring)
        row=compare(m,keys,d)
        permutation=list(reversed(range(len(keys))));reordered=Chem.RenumberAtoms(m,permutation)
        order=compare(reordered,[keys[i] for i in permutation],d)
        assert row==order
        reflected=Chem.Mol(m);x=np.asarray(m.GetConformer().GetPositions());x[:,0]*=-1
        for i,xyz in enumerate(x):reflected.GetConformer().SetAtomPosition(i,tuple(xyz))
        negative=compare(reflected,keys,d)
        assert not negative['passed']
        records.append(dict(product=product,sdf=pin(sdf),definition=pin(dpath),atom_map=rec['atom_map'],coordinate_check=row,
            stored_tag_agreement=parity,atom_reordering_invariant=True,reflection_negative_control_rejected=True,
            limitation='Existing capped-core coordinates, not a full DNA fixture; capped-graph CIP labels need not equal DNA-attached labels. No formation claim.'))
    p=read(PROBE/'plan.json');model=read(checked(p['model']));template=Chem.MolFromMolFile(str(checked(model['sdf'])),removeHs=False);keys=model['atom_keys'];d=read(REPO/'backend/data/forcefield/photoproducts/tt-cpd-cis-anti-i/chemical_definition.json');probe=[]
    # Expected sugar parity comes from the canonical model graph, independent of newly read positions.
    sugar=[keys.index('1:'+k) for k in ["C1'","C3'","C4'"]]
    for pt in p['points']:
        m=Chem.Mol(template);x=np.load(checked(pt['geometry']))*BOHR
        for i,xyz in enumerate(x):m.GetConformer().SetAtomPosition(i,tuple(xyz))
        actual=perceive(m);sugar_rows=[]
        for i in sugar:
            a=actual.GetAtomWithIdx(i)
            sugar_rows.append(dict(atom=keys[i],CIP=a.GetProp('_CIPCode') if a.HasProp('_CIPCode') else None,
                expected_tag=str(template.GetAtomWithIdx(i).GetChiralTag()),observed_tag=str(a.GetChiralTag()),passed=a.GetChiralTag()==template.GetAtomWithIdx(i).GetChiralTag()))
        probe.append(dict(point=pt['name'],geometry=pt['geometry'],core=compare(m,keys,d),sugar=sugar_rows,passed=compare(m,keys,d)['passed'] and all(s['passed'] for s in sugar_rows)))
    passed=all(r['coordinate_check']['passed'] and r['stored_tag_agreement'] for r in records) and all(r['passed'] for r in probe)
    result=dict(at=datetime.now(timezone.utc).isoformat(),rdkit_version=rdBase.rdkitVersion,source=pin(Path(__file__)),passed=passed,
        method='Remove all stereo annotations; AssignStereochemistryFrom3D; recursive rdCIPLabeler.AssignCIPLabels; atom-mapped signed-volume/connectivity checks against current definitions. Reordering and reflected-coordinate controls on eight cores.',
        existing_core_candidates=records,recent_canonical_fragment_points=probe,
        scope='Identity only. This audit does not establish experimental formation of every registry entry, force-field accuracy, or validity of historical full-DNA sugar geometry.',
        user_scope='Only previously established products of thymine-thymine photoreactions. No new-isomer discovery or enumeration. Experimental formation provenance is required separately from a possible stereochemical classification before admitting another isomer campaign.',
        production_modified=False,native_jobs=0)
    for dest in [OUT/'audit.json',REPO/'docs/audits/cpd_rdkit_identity_20261017.json']:
        dest.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,core_candidates=len(records),probe_points=len(probe),sugar=[r['sugar'] for r in probe if 'center' in r['point']]),indent=2))
if __name__=='__main__':main()
