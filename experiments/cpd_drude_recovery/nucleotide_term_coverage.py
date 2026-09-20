"""Graph-derived bonded-term coverage for the isolated anti nucleotide candidate."""
import json
from pathlib import Path
import sys
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms


def interactions(edges):
    neighbors = {}
    for a,b in edges:
        neighbors.setdefault(a,set()).add(b)
        neighbors.setdefault(b,set()).add(a)
    canon = lambda t: min(tuple(t), tuple(reversed(t)))
    bonds={canon(e) for e in edges}
    angles={canon((a,b,c)) for b,adj in neighbors.items() for a,c in combinations(sorted(adj),2)}
    torsions={canon((a,b,c,d)) for b,c in bonds for a in neighbors[b]-{c} for d in neighbors[c]-{b} if len({a,b,c,d})==4}
    return {'bond':bonds,'angle':angles,'proper_torsion':torsions}


def main():
    from rdkit import Chem
    seedroot=Path('.development-artifacts/cpd-repaired-anti-fragments-v1').resolve()
    root=Path('.development-artifacts/cpd-anti-nucleotide-term-coverage-v2').resolve()
    root.mkdir(exist_ok=False)
    boundary_path=seedroot/'boundary/candidate_manifest.json'
    boundary=json.loads(boundary_path.read_text())
    names=json.loads(checked(boundary['outputs']['atom_map']).read_text())
    mol=Chem.SDMolSupplier(str(checked(boundary['outputs']['sdf'])),removeHs=False)[0]
    edges={tuple(sorted((names[b.GetBeginAtomIdx()],names[b.GetEndAtomIdx()]))) for b in mol.GetBonds()}
    all_terms=interactions(edges)
    psf_path=Path('.development-artifacts/cpd-drude-nucleotide-preflight-v4/reactant.psf').resolve()
    _,atoms,sections=atoms_and_terms(psf_path.read_text())
    keep={i for i,a in atoms.items() if a[5]!='DRUD' and float(a[7])>0}
    def key(i):
        row=atoms[i]
        return row[2]+':'+{'O1P':'OP1','O2P':'OP2','C5M':'C7','H5T':"HO5'",'H3T':"HO3'"}.get(row[4],row[4])
    assert {key(i) for i in keep}==set(names)
    native_edges={tuple(sorted((key(a),key(b)))) for a,b in sections['NBOND'][3] if a in keep and b in keep}
    assert edges-native_edges=={('1:C5','2:C6'),('1:C6','2:C5')}
    assert not native_edges-edges
    native_terms=interactions(native_edges)
    fragment_terms={}
    records=[]
    sources=[boundary_path,psf_path,Path(__file__)]
    for endpoint in (1,2):
        path=seedroot/f'endpoint-{endpoint}/model_manifest.json'
        m=json.loads(path.read_text())
        graph=json.loads(checked(m['outputs']['model_graph']).read_text())
        fe={tuple(sorted(b['atoms'])) for b in graph['bonds'] if set(b['atoms']).issubset(names)}
        fragment_terms[endpoint]=interactions(fe)
        sources.extend([path,checked(m['outputs']['model_graph'])])
    core={f'{e}:{n}' for e in (1,2) for n in ['N1','C2','O2','N3','C4','O4','C5','C6','C7','H3','H6','H51','H52','H53']}
    for kind,terms in all_terms.items():
        for term in sorted(terms):
            changed=bool(set(term)&core)
            available=[e for e in (1,2) if term in fragment_terms[e][kind]]
            records.append({'kind':kind,'atoms':term,'new_due_to_crosslinks':term not in native_terms[kind],'touches_modified_base':changed,'contained_in_sugar_fragments':available,'scope':'core' if set(term)<=core else 'sugar_interface' if changed else 'native_backbone'})
    summary={kind:{'total':len(terms),'new_crosslink_terms':sum(r['kind']==kind and r['new_due_to_crosslinks'] for r in records),'modified_base_terms_without_fragment_coverage':sum(r['kind']==kind and r['touches_modified_base'] and not r['contained_in_sugar_fragments'] for r in records)} for kind,terms in all_terms.items()}
    write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Graph-only bond/angle/proper enumeration and fragment coverage. Existing terms touching CPD atoms require parameter review even when their graph is unchanged. No fitted coefficient or QM acceptance implied. Improper, anisotropy, Drude screening, exclusions and charge/LJ transfer require separate audits.','summary':summary,'records':records,'sources':[source(p) for p in sources]})
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
