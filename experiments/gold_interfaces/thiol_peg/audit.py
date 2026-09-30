"""Audit the existing components before composing a PEG–thiolate–gold model.

This writes evidence, not an executable simulation package. No Au–S parameters
are inferred from an organic S–C bond or a mechanical sulfur restraint.
"""
import argparse
import hashlib
import json
from pathlib import Path

from backend.core import gold_model
from experiments.peg_wall.build import ASSET_HASHES

ROOT = Path(__file__).resolve().parents[3]


def label(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section_rows(text, section):
    """Read CHARMM parameter records, dropping comments and section headers."""
    headers = {'BONDS', 'ANGLES', 'DIHEDRALS', 'IMPROPERS', 'NONBONDED',
               'NBFIX', 'CMAP', 'HBOND', 'END'}
    active = False
    for line in text.splitlines():
        fields = line.split('!', 1)[0].split()
        if not fields or fields[0].startswith('*'):
            continue
        if fields[0].upper() in headers:
            active = fields[0].upper() == section
        elif active:
            yield fields


def audit(assets):
    ff = ROOT / 'backend/data/forcefield'
    inputs = [ff / 'top_np_thiol.rtf', ff / 'par_np_thiol.prm',
              ff / 'par_all36m_prot.prm', ff / 'toppar_water_ions_cufix.str',
              ROOT / 'backend/core/nanoparticle_atomistic.py',
              ROOT / 'backend/core/namd_electrode_peg.py',
              ROOT / 'backend/core/gold_model.py']
    asset_checks = {}
    for name, expected in ASSET_HASHES.items():
        path = assets / name
        actual = digest(path) if path.is_file() else None
        asset_checks[name] = {'expected_sha256': expected, 'actual_sha256': actual,
                              'matches': actual == expected}
        if actual is not None:
            inputs.append(path)
    bond_rows = []
    for path in inputs:
        if path.suffix in {'.prm', '.str'}:
            for row in section_rows(path.read_text(), 'BONDS'):
                if len(row) >= 4:
                    bond_rows.append({'types': row[:2], 'values': row[2:4],
                                      'source': label(path)})
    gold_type = gold_model.MODEL['atom_type']
    gold_bonds = [row for row in bond_rows if gold_type in row['types']]
    organic_s_c = [row for row in bond_rows if set(row['types']) == {'S', 'CT2'}]
    return {
        'schema': 'nadoc.gold_peg_thiol_basis_audit.v1',
        'ready_for_explicit_peg_thiolate_gold_simulation': False,
        'gold_basis': gold_model.specification(),
        'ether_assets': asset_checks,
        'parameter_observations': {
            'explicit_gold_bonds': gold_bonds,
            'organic_sulfur_carbon_bonds': organic_s_c,
            'note': 'S-CT2 is organic S-C; it cannot be reused as an Au-S bond.'},
        'existing_paths': {
            'nanoparticle_direct_thiol': {
                'organic_graph': 'DNA-O-P(O2)-O-(CH2)3-S',
                'gold_representation': 'implicit_fixed_sphere',
                'attachment': 'positional sulfur restraint',
                'contains_peg': False, 'contains_explicit_gold': False},
            'electrode_peg': {
                'organic_graph': 'CH3-O-(CH2-CH2-O)n-CH3',
                'attachment': 'mechanical graft', 'contains_sulfur': False},
            'explicit_gold': {
                'geometries': ['slab', 'nanoparticle'],
                'shared_model_id': gold_model.MODEL_ID,
                'gold_sulfur_bonds': gold_model.MODEL['capabilities']['gold_sulfur_bonds']}},
        'required_shared_contract': {
            'geometry_independent': ['ligand_atom_graph', 'repeat_count_convention',
                'end_groups', 'precursor_and_bound_charge_models', 'au_s_model_id',
                'parameter_hashes', 'nonbonded_exclusions'],
            'geometry_specific': ['binding_motif', 'surface_atom_ids', 'facet_or_local_coordination',
                                 'coverage', 'surface_normal', 'boundary_conditions'],
            'electrical_condition': 'no imposed voltage or excess electrode charge; '
                'interfacial partial charges must come from the selected model',
        },
        'missing_before_native_run': [
            'Exact PEG-thiol precursor and bound product atom graphs, including end groups/spacers.',
            'Source-backed Au-S interface model compatible with the chosen gold basis and motif.',
            'Complete junction charges and bonded/nonbonded parameters with provenance.',
            'Final bonded graph, exclusions, complete-cell charge balance and parameter coverage.',
            'Native reference-energy/force and short integration/restart checks.',
            'Physical interface validation: binding geometry, hydration and PEG conformations.'],
        'source_sha256': {label(path): digest(path) for path in inputs},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path,
                        default=ROOT / '.development-artifacts/peg_wall_validation/assets/toppar_ether')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.assets.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps({'report': str(args.output), 'simulation_ready': False,
                      'missing_requirements': len(result['missing_before_native_run'])}))


if __name__ == '__main__':
    main()
