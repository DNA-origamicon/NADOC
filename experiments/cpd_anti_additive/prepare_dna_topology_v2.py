"""Transfer lesion/attachment terms onto parent DNA; topology-only isolated audit."""

import json
from pathlib import Path
import shutil
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app
import parmed as pmd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_published_comparator.reconstruct import BASE, FF
from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import resolve_base_keys
from backend.core.namd_topology import _write_segment_pdbs, _psfgen_script, photoproduct_patch_plan
from backend.parameterization.photoproduct_candidate_context import _run_psfgen

ART = REPO/'.development-artifacts'
CAPS = {'CM', 'HCM1', 'HCM2', 'HCM3'}


def transfer_key(key, aliases):
    """Only lesion-containing terms transfer; pure parent sugar terms stay native."""
    roles = [aliases[t]['role'].split(':')[1] for t in key if t in aliases]
    if any(role in CAPS for role in roles):
        return None
    if not any("'" not in role for role in roles):
        return None
    return tuple(aliases[t]['original_type'] if t in aliases and "'" in aliases[t]['role'] else t for t in key)


def export_parameters(parent, aliases, root):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        parameters = pmd.charmm.CharmmParameterSet(str(parent/'comparator_last.prm'))
    base_types = {a for a, r in aliases.items() if "'" not in r['role'] and r['role'].split(':')[1] not in CAPS}
    assert len(base_types)==28
    lines = ['* Isolated anti DNA transfer: parent sugar/phosphate retained', '*', 'ATOMS']
    for t in sorted(base_types):
        lines.append(f'MASS -1 {t} {parameters.atom_types_str[t].mass:.15g}')
    mapping = []
    for kind, section in [('bond_types', 'BONDS'), ('angle_types', 'ANGLES'),
                          ('dihedral_types', 'DIHEDRALS'), ('improper_types', 'IMPROPER')]:
        lines.extend(['', section])
        emitted = {}
        for key, value in getattr(parameters, kind).items():
            newkey = transfer_key(key, aliases)
            if newkey is None:
                continue
            if kind!='improper_types' and key>key[::-1]:
                continue
            prefix = ' '.join(newkey)
            if kind=='bond_types':
                rows = [f'{prefix} {value.k:.15g} {value.req:.15g}']
            elif kind=='angle_types':
                line = f'{prefix} {value.k:.15g} {value.theteq:.15g}'
                ub = parameters.urey_bradley_types.get(key)
                if ub is not None and ub.k:
                    line += f' {ub.k:.15g} {ub.req:.15g}'
                rows = [line]
            elif kind=='dihedral_types':
                rows = [f'{prefix} {v.phi_k:.15g} {v.per:d} {v.phase:.15g}' for v in value]
            else:
                rows = [f'{prefix} {value.psi_k:.15g} 0 {value.psi_eq:.15g}']
            canonical = newkey if kind=='improper_types' else min(newkey, newkey[::-1])
            if canonical in emitted:
                assert emitted[canonical]==rows, ('Conflicting transfer', kind, newkey)
                continue
            emitted[canonical] = rows
            lines.extend(rows)
            mapping.append(dict(kind=kind, source_types=key, destination_types=newkey, records=rows))
    lines.extend(['', 'NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -',
                  'cutnb 16.0 ctofnb 12.0 ctonnb 10.0 eps 1.0 e14fac 1.0 wmin 1.5'])
    for t in sorted(base_types):
        a = parameters.atom_types_str[t]
        lines.append(f'{t} 0.0 {-abs(a.epsilon):.15g} {a.rmin:.15g} 0.0 {-abs(a.epsilon_14):.15g} {a.rmin_14:.15g}')
    lines.extend(['', 'NBFIX'])
    for key, values in parameters.nbfix_types.items():
        newkey = transfer_key(key, aliases)
        if newkey is None:
            continue
        # Sugar aliases never survive. Existing native parent corrections are
        # supplied by the parent files; retain lesion/native corrections here.
        lines.append(' '.join(newkey)+f' {-abs(values[0]):.15g} {values[1]:.15g}')
    lines.append('END')
    output = root/'anti_dna_overlay.prm'
    output.write_text('\n'.join(lines)+'\n')
    save(root/'parameter_transfer.json', dict(mapping=mapping, base_types=sorted(base_types),
        rule='Copy lesion and mixed attachment coefficients; replace sugar aliases by native types; omit pure sugar/cap terms',
        source=source(parent/'comparator_last.prm'), output=source(output)))
    return base_types


def main():
    _, receipt = require('engine')
    candidate = Path(receipt['candidate'])
    root = ART/'cpd-anti-dna-topology-v2b'
    root.mkdir(exist_ok=False)
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    sitepath = ART/'cpd-anti-additive-2hb-site-v1/site_manifest.json'
    site = read(sitepath)
    snapshot = checked(site['snapshot'])
    original = snapshot.read_bytes()
    aliaspath = ART/'cpd-anti-ordered-types-v1/assessment.json'
    aliases = {r['alias']:r for r in read(aliaspath)['aliases']}
    psfgen = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/psfgen')
    parents = [BASE/'top_all36_na.rtf', BASE/'par_all36_na.prm',
               FF/'top_all36_cgenff.rtf', FF/'par_all36_cgenff.prm']
    save(root/'plan.json', dict(stage='Isolated full-DNA topology and parameter coverage; no geometry fit or dynamics',
        candidate=source(candidate/'assessment.json'), parameter_source=source(candidate/'comparator_last.prm'),
        aliases=source(aliaspath), site=source(sitepath), snapshot=site['snapshot'],
        parent_forcefields=[source(p) for p in parents], psfgen=source(psfgen),
        charge_rule='Transfer fitted base charges only; keep all parent DNA sugar/phosphate charges',
        bonded_rule='Transfer lesion/attachment terms only; retain native DNA sugar/phosphate bonded terms',
        fixed_criteria=['Exact source site mapping', 'Only two declared anti bonds added',
                        'Only two reactant C5 planar impropers removed', 'All nonlesion atoms unchanged',
                        'Preserved total charge', 'No missing parameters'],
        geometry_authorized_for_dynamics=False, simulation_ready=False))
    base_types = export_parameters(candidate, aliases, root)
    compound = app.CharmmPsfFile(str(candidate/'two-nucleosides/fragment.psf'))
    names = read(candidate/'two-nucleosides/atom_map.json')
    assignments = {n:(a.attype, a.charge) for n,a in zip(names, compound.atom_list) if a.attype in base_types}
    assert len(assignments)==28 and abs(sum(q for _,q in assignments.values()))<1e-8
    topology = ['* Isolated cis-anti base patch; native DNA backbone retained', '*', '36 1']
    for t in sorted(base_types):
        atom = next(a for a in compound.atom_list if a.attype==t)
        topology.append(f'MASS -1 {t} {atom.mass.value_in_unit(mm.unit.dalton):.15g}')
    topology.append('PRES CAV2 0.0')
    for name, (typ, charge) in sorted(assignments.items()):
        endpoint, atomname = name.split(':')
        atomname = 'C5M' if atomname=='C7' else atomname
        topology.append(f'ATOM {endpoint}{atomname} {typ} {charge:.12f}')
    topology.extend(['DELETE IMPR 1C5 1C4 1C6 1C5M', 'DELETE IMPR 2C5 2C4 2C6 2C5M',
                     'BOND 1C5 2C6 1C6 2C5', 'END'])
    topfile = root/'anti_dna.rtf'
    topfile.write_text('\n'.join(topology)+'\n')
    design = Design.from_json(original.decode())
    assert len(design.photoproduct_junctions)==1
    lesion = design.photoproduct_junctions[0]
    assert lesion.patch_order=='base-key-1-first'
    assert [lesion.base_key_1,lesion.base_key_2]==site['ordered_base_keys']
    model = build_atomistic_model(design)
    endpoints, errors = resolve_base_keys(design, site['ordered_base_keys'], atomistic_model=model, require_atoms=True)
    assert not errors
    bykey = {e.key:e for e in endpoints}
    for key, expected in zip(site['ordered_base_keys'], site['source_world_coordinates_angstrom']):
        for name, xyz in expected.items():
            assert np.max(abs(10*np.array(bykey[key].atom_positions_nm[name])-xyz))<1e-8
    # Clone identity in memory solely for the isolated anti topology. Coordinates
    # remain the explicitly unsafe frozen source geometry, never published as anti.
    design = design.model_copy(deep=True)
    design.photoproduct_junctions[0].stereochemistry='cis-anti'
    segment_folder = root/'segments'
    segment_folder.mkdir()
    segments, pdb = _write_segment_pdbs(design, segment_folder, model)
    (root/'source_heavy_atoms.pdb').write_text(pdb)
    registry = {'products':[dict(id='tt-cpd-cis-anti-i', product='TT-CPD', stereochemistry='cis-anti',
        assets={'topology':dict(path=topfile.name, sha256=source(topfile)['sha256'], patch_name='CAV2')})]}
    patch = photoproduct_patch_plan(design, model, segments, registry=registry, registry_root=root)
    selected = patch['patches'][0]['endpoints']
    assert [e['base_key'] for e in selected]==site['ordered_base_keys']
    assert selected[0]['segid']!=selected[1]['segid']
    for e in selected:
        seg = next(s for s in segments if s['segid']==e['segid'])
        assert seg['first_resid']<e['resid']<seg['last_resid']
    for label in ('reactant', 'anti'):
        script = _psfgen_script(segments, (root/label).resolve(),
            extra_topologies=[topfile.resolve()] if label=='anti' else [],
            photoproduct_patches=patch['patches'] if label=='anti' else [])
        (root/f'{label}.tcl').write_text(script)
        _run_psfgen(psfgen, script, root.resolve(), root/f'{label}.log')
    reactant = app.CharmmPsfFile(str(root/'reactant.psf'))
    product = app.CharmmPsfFile(str(root/'anti.psf'))
    def identity(atom):
        return atom.system, atom.residue.idx, atom.name
    assert [identity(a) for a in reactant.atom_list]==[identity(a) for a in product.atom_list]
    locations = {(e['segid'], e['resid']):i+1 for i,e in enumerate(selected)}
    targets = {}
    for a, b in zip(reactant.atom_list, product.atom_list):
        position = (b.system, b.residue.idx)
        role = 'C7' if b.name=='C5M' else b.name
        key = f'{locations[position]}:{role}' if position in locations else None
        if key in assignments:
            typ, charge = assignments[key]
            assert b.attype==typ and abs(b.charge-charge)<=5.00001e-7
            targets[b.idx]=charge
        else:
            assert a.attype==b.attype and a.charge==b.charge and a.mass==b.mass
    assert len(targets)==28
    shutil.copyfile(root/'anti.psf', root/'anti_psfgen_raw.psf')
    lines = (root/'anti.psf').read_text().splitlines()
    offset = next(i for i,l in enumerate(lines) if '!NATOM' in l)+1
    for i, charge in targets.items():
        fields = lines[offset+i].split()
        assert int(fields[0])==i+1
        fields[6]=f'{charge:.12f}'
        lines[offset+i]=' '.join(fields)
    (root/'anti.psf').write_text('\n'.join(lines)+'\n')
    product = app.CharmmPsfFile(str(root/'anti.psf'))
    def bonds(psf):
        return {tuple(sorted((b.atom1.idx, b.atom2.idx))) for b in psf.bond_list}
    def impropers(psf):
        return {tuple(getattr(i, f'atom{j}').idx for j in range(1,5)) for i in psf.improper_list}
    index = {identity(a):a.idx for a in product.atom_list}
    def at(e, n):
        return index[(selected[e-1]['segid'],selected[e-1]['resid'],n)]
    expected_bonds = {tuple(sorted((at(1,'C5'),at(2,'C6')))), tuple(sorted((at(1,'C6'),at(2,'C5'))))}
    # OpenMM normalizes CHARMM C5M to the PDB-standard name C7 on parsing.
    expected_impropers = {tuple(at(e,n) for n in ('C5','C4','C6','C7')) for e in (1,2)}
    assert bonds(product)-bonds(reactant)==expected_bonds and not bonds(reactant)-bonds(product)
    assert impropers(reactant)-impropers(product)==expected_impropers and not impropers(product)-impropers(reactant)
    q0, q1 = [sum(a.charge for a in s.atom_list) for s in (reactant, product)]
    assert abs(q0-q1)<1e-8
    coverage_error = None
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        merged = app.CharmmParameterSet(*(str(p) for p in parents+[root/'anti_dna_overlay.prm']))
    try:
        system = product.createSystem(merged, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
        (root/'coverage_system.xml').write_text(mm.XmlSerializer.serialize(system))
    except Exception as exc:
        coverage_error = repr(exc)
    save(root/'assessment.json', dict(topology_passed=True, parameter_coverage_passed=coverage_error is None,
        parameter_coverage_error=coverage_error, atoms=len(product.atom_list), residues=len(product.residue_list),
        segments=len(segments), endpoints=selected, net_charge=q1, original_net_charge=q0,
        changed_base_atoms=len(targets), added_bonds=[[identity(product.atom_list[i]) for i in b] for b in sorted(expected_bonds)],
        removed_planar_impropers=len(expected_impropers), all_other_atoms_and_bonds_unchanged=True,
        parent_sugar_and_phosphate_retained=True, parameters_refitted=False, coordinates_relaxed=False,
        geometry_safe_for_dynamics=False, native_NAMD_tested=False, preliminary_research_qualified=False,
        simulation_ready=False, plan=source(root/'plan.json'), transfer=source(root/'parameter_transfer.json'),
        outputs={name:source(root/name) for name in ('anti.psf','reactant.psf','anti.pdb','anti_dna.rtf','anti_dna_overlay.prm')}))
    assert snapshot.read_bytes()==original
    print(json.dumps(read(root/'assessment.json'), indent=2))
    if coverage_error:
        raise RuntimeError('Missing DNA terms; preserve audit before further work')


if __name__=='__main__':
    main()
