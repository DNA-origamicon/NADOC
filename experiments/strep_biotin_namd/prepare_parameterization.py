"""Build isolated CGenFF inputs and reference reuse ledger; never launch MD.

Requires RDKit in addition to the project environment (see README).
Coordinates generated here are research inputs, never application geometry.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def molecule():
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from backend.core.biotin_atomistic import _unconnected_teg
    from backend.core.biotin_teg_chemistry import chemical_definition

    definition = chemical_definition()
    names, elements, xyz, _ = _unconnected_teg()
    editable = Chem.RWMol()
    for name, element in zip(names, elements):
        atom = Chem.Atom(element)
        atom.SetProp('name', name)
        editable.AddAtom(atom)
    index = {n: i for i, n in enumerate(names)}
    for bond in definition['bonds']:
        a, b = bond['atoms']
        editable.AddBond(index[a], index[b],
                         Chem.BondType.DOUBLE if bond['order'] == 2 else Chem.BondType.SINGLE)
    # Assign the three biotin stereocenters from the existing crystallographic
    # graph before replacing research coordinates by an embedded conformer.
    initial = editable.GetMol()
    Chem.SanitizeMol(initial)
    conf = Chem.Conformer(len(names))
    for i, point in enumerate(xyz):
        conf.SetAtomPosition(i, tuple(float(x) * 10 for x in point))
    initial.AddConformer(conf)
    Chem.AssignAtomChiralTagsFromStructure(initial)
    Chem.AssignStereochemistry(initial, cleanIt=True, force=True)
    stereo = {a.GetProp('name'): a.GetProp('_CIPCode') for a in initial.GetAtoms()
              if a.HasProp('_CIPCode')}
    if set(stereo) != set(definition['ring_centers']):
        raise ValueError(f'Unexpected biotin stereocenters: {stereo}')
    editable = Chem.RWMol(initial)
    # Methyl replaces DNA beyond O5': a charge -1 phosphodiester model,
    # not a terminal phosphate monoester or a proposed DNA topology.
    for name, element, charge in [('P', 'P', 0), ('OP1', 'O', 0),
                                  ('OP2', 'O', -1), ('O5C', 'O', 0), ('C5C', 'C', 0)]:
        a = Chem.Atom(element)
        a.SetFormalCharge(charge)
        a.SetProp('name', name)
        index[name] = editable.AddAtom(a)
    for a, b, order in [('O4T', 'P', 1), ('P', 'OP1', 2), ('P', 'OP2', 1),
                        ('P', 'O5C', 1), ('O5C', 'C5C', 1)]:
        editable.AddBond(index[a], index[b],
                         Chem.BondType.DOUBLE if order == 2 else Chem.BondType.SINGLE)
    mol = editable.GetMol()
    mol.RemoveAllConformers()
    Chem.SanitizeMol(mol)
    mol = Chem.AddHs(mol)
    for i, atom in enumerate(mol.GetAtoms()):
        if not atom.HasProp('name'):
            atom.SetProp('name', f'H{i:03d}')
    params = AllChem.ETKDGv3()
    params.randomSeed = 20260916
    params.enforceChirality = True
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise ValueError('Failed to embed parameterization model')
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    actual = {a.GetProp('name'): a.GetProp('_CIPCode') for a in mol.GetAtoms()
              if a.HasProp('_CIPCode')}
    if actual != stereo:
        raise ValueError('Biotin stereochemistry changed')
    for atom in definition['atoms']:
        heavy = mol.GetAtomWithIdx(index[atom['name']])
        if sum(n.GetAtomicNum() == 1 for n in heavy.GetNeighbors()) != atom['hydrogen_count']:
            raise ValueError(f"Wrong H count at {atom['name']}")
    if Chem.GetFormalCharge(mol) != -1:
        raise ValueError('Phosphodiester model must have charge -1')
    return mol, stereo


def mol2(mol):
    """Tripos chemical types and formal charge placeholders, never FF charges."""
    from rdkit import Chem

    def tripos(a):
        symbol = a.GetSymbol()
        if symbol == 'C':
            return 'C.2' if any(b.GetBondType() == Chem.BondType.DOUBLE for b in a.GetBonds()) else 'C.3'
        if symbol == 'N':
            return 'N.am'
        if symbol == 'O':
            return 'O.2' if any(b.GetBondType() == Chem.BondType.DOUBLE for b in a.GetBonds()) else 'O.3'
        return {'P': 'P.3', 'S': 'S.3', 'H': 'H'}[symbol]

    out = ['@<TRIPOS>MOLECULE', 'BTMP', f'{mol.GetNumAtoms()} {mol.GetNumBonds()} 1 0 0',
           'SMALL', 'USER_CHARGES', '', '@<TRIPOS>ATOM']
    for i, atom in enumerate(mol.GetAtoms()):
        x, y, z = mol.GetConformer().GetAtomPosition(i)
        out.append(f'{i+1:5d} {atom.GetProp("name"):<4} {x:12.6f} {y:12.6f} {z:12.6f} '
                   f'{tripos(atom):<5} 1 BTMP {atom.GetFormalCharge():.6f}')
    out.append('@<TRIPOS>BOND')
    for i, bond in enumerate(mol.GetBonds()):
        out.append(f'{i+1:5d} {bond.GetBeginAtomIdx()+1:5d} {bond.GetEndAtomIdx()+1:5d} '
                   f'{int(bond.GetBondTypeAsDouble())}')
    out += ['@<TRIPOS>SUBSTRUCTURE', '1 BTMP 1 RESIDUE 1 A BTMP 0 ROOT']
    return '\n'.join(out) + '\n'


def crossing_terms(mol):
    """All bond/angle/proper-dihedral paths crossing the ligand–P boundary."""
    atoms = {a.GetProp('name'): a.GetIdx() for a in mol.GetAtoms()}
    edge = frozenset((atoms['O4T'], atoms['P']))
    found = {2: set(), 3: set(), 4: set()}

    def visit(path):
        if len(path) in found and any(frozenset(p) == edge for p in zip(path, path[1:])):
            found[len(path)].add(min(tuple(path), tuple(reversed(path))))
        if len(path) < 4:
            for a in mol.GetAtomWithIdx(path[-1]).GetNeighbors():
                if a.GetIdx() not in path:
                    visit(path + [a.GetIdx()])

    for a in mol.GetAtoms():
        visit([a.GetIdx()])
    return {label: [[mol.GetAtomWithIdx(i).GetProp('name') for i in path]
                    for path in sorted(found[n])]
            for n, label in [(2, 'bonds'), (3, 'angles'), (4, 'proper_dihedrals')]}


def build(output, references):
    from rdkit import Chem, rdBase
    from rdkit.Chem import rdMolDescriptors
    from backend.core.biotin_teg_chemistry import chemical_definition

    mol, stereo = molecule()
    files = [ROOT / 'backend/data/forcefield' / name for name in
             ['top_all36_prot.rtf', 'par_all36m_prot.prm', 'top_all36_na.rtf', 'par_all36_na.prm']]
    files += [references / name for name in ['top_all36_cgenff.rtf', 'par_all36_cgenff.prm']]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'reference_forcefield').mkdir()
    ledger = []
    for source in files:
        destination = output / 'reference_forcefield' / source.name
        shutil.copyfile(source, destination)
        ledger.append(dict(file=str(destination.relative_to(output)), sha256=digest(destination),
                           source=str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
                           provenance='https://mackerell.umaryland.edu/charmm_ff.shtml',
                           role='assignment_reference' if 'cgenff' in source.name else 'reuse_unchanged'))
    (output / 'BTMP.mol2').write_text(mol2(mol))
    writer = Chem.SDWriter(str(output / 'BTMP.sdf'))
    mol.SetProp('_Name', 'Biotin-TEG methyl-capped phosphodiester research model')
    writer.write(mol)
    writer.close()
    Chem.MolToPDBFile(mol, str(output / 'BTMP.review.pdb'))
    dump(output / 'chemical_definition.json', chemical_definition())
    dump(output / 'reference_forcefield.json', ledger)
    dump(output / 'atom_mapping.json', [dict(index_1based=a.GetIdx()+1, name=a.GetProp('name'),
         element=a.GetSymbol(), formal_charge=a.GetFormalCharge(),
         role='cap_only' if a.GetProp('name') in ('O5C', 'C5C') or
              (a.GetAtomicNum() == 1 and a.GetNeighbors()[0].GetProp('name') == 'C5C') else
              ('dna_phosphate' if a.GetProp('name') in ('P', 'OP1', 'OP2') else 'ligand'),
         parent=a.GetNeighbors()[0].GetProp('name') if a.GetAtomicNum() == 1 else None)
         for a in mol.GetAtoms()])
    tasks = dict(boundary_terms=crossing_terms(mol),
                 unresolved=['biotin fused-ring charges/types/impropers', 'biotin–TEG amide',
                             'ether-to-phosphodiester charge/type transition',
                             'CGenFF-to-CHARMM-DNA boundary terms and charge redistribution'],
                 reference_analogues={'NMA': 'amide', 'DME': 'ether', 'DMEP': 'phosphodiester',
                                      'UREA': 'ureido carbonyl; fused ring remains unmatched'},
                 rules=['Do not transplant whole-fragment charges by atom-name similarity.',
                        'Retain all torsion multiplicities and explicit improper ordering.',
                        'Cap atoms never enter the final BTE/BTE5 patch.',
                        'Add sugar-context validation before accepting O5–C5/C4 boundary terms.',
                        'QM refinement uses CGenFF-compatible targets, not arbitrary ESP substitution.',
                        'All RunPod simulation attempts require verified GPU execution; budget $5 cumulative.'])
    dump(output / 'parameterization_tasks.json', tasks)
    indices = {a.GetProp('name'): a.GetIdx()+1 for a in mol.GetAtoms()}
    scans = [(['C10', 'C11', 'NT', 'C1T'], 'amide planarity'),
             (['C11', 'NT', 'C1T', 'C2T'], 'amide-to-spacer'),
             (['O1T', 'C3T', 'C4T', 'O2T'], 'ether reference control'),
             (['C7T', 'C8T', 'O4T', 'P'], 'ether-to-phosphate'),
             (['C8T', 'O4T', 'P', 'O5C'], 'ligand phosphate torsion'),
             (['O4T', 'P', 'O5C', 'C5C'], 'phosphate cap control')]
    dump(output / 'qm_targets.json', dict(
        status='target_definition_only_no_qm_results', charge=-1, multiplicity=1,
        coordinates='BTMP.sdf', coordinate_units='angstrom',
        scan_convention='relaxed constrained dihedral; retain all other molecular degrees of freedom',
        torsions=[dict(atoms=names, indices_1based=[indices[n] for n in names], purpose=purpose,
                       target_degrees=list(range(-180, 180, 15))) for names, purpose in scans],
        other_targets=['optimized geometry and vibrational/bond-angle targets',
                       'CGenFF-compatible solute-water interactions for uncertain charges',
                       'actual deoxyribose context for final DNA-boundary qualification'],
        execution_gate='Select a CGenFF-compatible QM protocol and verify GPU support before submitting. No CPU RunPod fallback.',
        fit_scope='Only refine assignments flagged by chemistry/penalty/target mismatch; preserve accepted reference terms.',
        limitations='Methyl cap cannot validate DNA sugar torsions. No fitted parameters or completed QM jobs are implied.'))
    # Preserve complete reference-residue definitions, not a misleading ligand RTF.
    text = (references / 'top_all36_cgenff.rtf').read_text()
    blocks = []
    for name in tasks['reference_analogues']:
        lines = text.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.split()[:2] == ['RESI', name])
        end = next((i for i in range(start+1, len(lines)) if lines[i].split()[:1] in (['RESI'], ['PRES'])), len(lines))
        blocks.append(''.join(lines[start:end]))
    (output / 'reference_residues.txt').write_text(''.join(blocks))
    manifest = dict(schema='nadoc.biotin-parameterization.v1', simulation_ready=False,
                    literature_ligand_assignments_recovered=False,
                    status='inputs_ready_assignment_pending', rdkit_version=rdBase.rdkitVersion,
                    formula=rdMolDescriptors.CalcMolFormula(mol), total_atoms=mol.GetNumAtoms(),
                    formal_charge=Chem.GetFormalCharge(mol), stereo=stereo,
                    smiles=Chem.MolToSmiles(Chem.RemoveHs(mol)),
                    coordinate_method='ETKDGv3; research-only, not minimized or approved application geometry',
                    cgenff_command=['cgenff', 'BTMP.mol2', '-a'],
                    cgenff_notes='Redirect stdout to BTMP.str and stderr to BTMP.log. Never pass -z: MOL2 charges are formal placeholders.',
                    acceptance=['match CGenFF library and assignment-program versions',
                                'review all warnings and charge/parameter penalties',
                                'validate stereo/charge/complete PSF parameter coverage',
                                'qualify BTE/BTE5 boundary in actual nucleotide context',
                                'GPU NAMD stability and throughput checks before production'])
    dump(output / 'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--references', type=Path,
                        default=ROOT / 'experiments/strep_biotin_namd/ws/references')
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), args.references.resolve()), indent=2))
