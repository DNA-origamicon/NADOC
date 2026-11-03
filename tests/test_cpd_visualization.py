"""Formed CPDs retain geometry views without admitting legacy simulation output."""
from pathlib import Path
import pytest
from backend.core.models import Design
from backend.core.cpd_conversion import convert_thymine_pair
from backend.core.atomistic_cache import build_atomistic_model_cached
from backend.core.pdb_export import export_coordinate_pdb, export_pdb, export_psf
from backend.core.cpd_forcefield import CpdCapabilityError
from backend.core.md_box_preview import preview_box
from backend.core.md_vram import estimate_profile_from_design
from backend.api.routes_md import CreateJobRequest
from backend.core.cpd_metrics import designed_weld_pairs

@pytest.fixture(params=['cis-syn','trans-syn-I','trans-syn-II','cis-anti-I'])
def product(request):
    design=Design.from_json(Path('tests/fixtures/cpd_six_residue_1xt.nadoc').read_text())
    keys=[f'__xb__:{x.id}:0' for x in design.crossovers if x.extra_bases=='T']
    return convert_thymine_pair(design,keys,request.param)[0]

def test_coordinate_views_and_sizing_preserve_formed_product(product):
    model=build_atomistic_model_cached(product)
    pdb=export_coordinate_pdb(product,model=model)
    assert 'CPD coordinate visualization only' in pdb
    assert sum(l.startswith('ATOM') for l in pdb.splitlines()) == len(model.atoms)
    from backend.core.base_keys import atom_base_key
    from backend.core.photoproduct_chemistry import load_chemical_definition
    lesion=product.photoproduct_junctions[0]
    serials={(atom_base_key(a),a.name):a.serial+1 for a in model.atoms}
    keys={'1':lesion.base_key_1,'2':lesion.base_key_2}
    conect=set()
    for line in pdb.splitlines():
        if line.startswith('CONECT'):
            ids=[int(line[i:i+5]) for i in range(6,len(line),5) if line[i:i+5].strip()]
            conect.update(tuple(sorted((ids[0],b))) for b in ids[1:])
    for bond in load_chemical_definition(lesion.product,lesion.stereochemistry)['graph_delta']['bonds_added']:
        edge=[]
        for ref in (bond['atom_1'],bond['atom_2']):
            endpoint,name=ref.split(':');edge.append(serials[keys[endpoint],name])
        assert tuple(sorted(edge)) in conect
    result=preview_box(product,CreateJobRequest(padding_nm=6))
    assert all(v>12 for v in result['calculated_nm'])
    assert result['solute_bounds_nm']
    profile=estimate_profile_from_design(product,atomistic_model=model)
    assert profile is not None
    pairs=designed_weld_pairs(product)
    assert len(pairs)==1 and pairs[0]['formed']
    assert pairs[0]['stereochemistry']==product.photoproduct_junctions[0].stereochemistry
    from types import SimpleNamespace
    from backend.core.kimmdy_analysis import topology_thymine_sites
    # These still carry THY names in CHARMM; residue names alone cannot tell
    # an unreacted thymine from a saturated photoproduct.
    residues=[SimpleNamespace(resname='THY',segid=pairs[0][f'segid_{side}'],
                              resid=pairs[0][f'resid_{side}']) for side in ('a','b')]
    assert topology_thymine_sites(SimpleNamespace(residues=residues),product)==[]
    for export in (export_pdb,export_psf):
        with pytest.raises(CpdCapabilityError): export(product,model=model)

def test_formed_pair_identity_includes_same_strand_ordinary_bases():
    from backend.core.base_keys import atom_base_key
    from backend.core.models import PhotoproductJunction
    design=Design.from_json(Path('tests/fixtures/cpd_six_residue_1xt.nadoc').read_text())
    atoms=build_atomistic_model_cached(design).atoms
    by_chain={}
    for a in atoms:
        if a.name=='C5' and a.residue=='DT' and not a.crossover_id:
            by_chain.setdefault(a.chain_id,[]).append(atom_base_key(a))
    keys=next(keys[:2] for keys in by_chain.values() if len(keys)>=2)
    design.photoproduct_junctions=[PhotoproductJunction(base_key_1=keys[0],base_key_2=keys[1])]
    formed=[p for p in designed_weld_pairs(design) if p.get('formed')]
    assert len(formed)==1
    assert formed[0]['segid_a']==formed[0]['segid_b']
    assert formed[0]['resid_a']!=formed[0]['resid_b']
