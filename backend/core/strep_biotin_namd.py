"""Explicit gold-free streptavidin/biotin-TEG/DNA preparation for CHARMM/NAMD.

This path never promotes display geometry to a parameterized simulation. Ligand
RTF/PRM and its DNA boundary patch are mandatory for a full PSF build.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import numpy as np
from backend.core.atomistic import Atom, AtomisticModel, build_atomistic_model
from backend.core.biotin_atomistic import CATALOG
from backend.core.biotin_teg_chemistry import chemical_definition
from backend.core.namd_topology import (
    _write_segment_pdbs, _psfgen_script, _psfgen_pdb_record,
    _psfgen_atom_name, find_psfgen,
)
from backend.core.md_charge import parse_psf_atoms


def _ligand_pdb_record(atom, serial, segid):
    """Ligand names are chemical identities, not DNA aliases (C7 != C5M)."""
    line = _psfgen_pdb_record(atom, serial, segid)
    return line[:12] + f'{atom.name:>4s}' + line[16:]


def prepare_components(design):
    """Keep all design DNA and occupied tetramers; omit gold with explicit provenance."""
    d = design.without_reference_geometry().model_copy(deep=True)
    if d.protein_attachments or d.nanoparticle_conjugations:
        raise ValueError('This gold-free preparation supports strep/biotin DNA only')
    if not any(p.biotin_dna for p in d.nanoparticles):
        raise ValueError('No streptavidin-bound biotin DNA records')
    for p in d.nanoparticles:
        p.visible = True  # Visibility is not a molecular exclusion instruction.
    base = build_atomistic_model(d)

    ligand_atoms = [a for a in base.atoms if a.residue == 'BTE']
    main = [a for a in base.atoms if a.residue != 'BTE']
    known_strands = {s.id: s for s in d.strands}
    links, proteins, occupied, grafted_strands = [], [], set(), set()
    for p in d.nanoparticles:
        for r in p.biotin_dna:
            if not p.coating or r.tetramer_index >= len(p.coating.poses):
                raise ValueError('Missing streptavidin pocket owner')
            if r.strand_id not in known_strands:
                raise ValueError('Biotin requires an existing linear DNA strand with a 5′ terminus')
            key = (p.id, r.tetramer_index, r.chain)
            if key in occupied:
                raise ValueError('Duplicate biotin pocket occupancy')
            occupied.add(key)
            if r.strand_id in grafted_strands:
                raise ValueError('DNA 5′ terminus is assigned to multiple biotin pockets')
            grafted_strands.add(r.strand_id)
            lig = [a for a in ligand_atoms if a.strand_id == r.strand_id]
            dna = [a for a in main if a.strand_id == r.strand_id and a.seq_num == 1 and a.name == 'P']
            if len(lig) != 28 or len(dna) != 1 or len({a.name for a in lig}) != 28:
                raise ValueError('Incomplete biotin-TEG or missing native 5′ phosphate')
            oxygen = next(a for a in lig if a.name == 'O4T')
            if (oxygen.serial, dna[0].serial) not in base.bonds and (dna[0].serial, oxygen.serial) not in base.bonds:
                raise ValueError('Biotin-TEG geometry is unconnected; repair linker placement before NAMD')
            distance = np.linalg.norm(np.array([oxygen.x, oxygen.y, oxygen.z])-np.array([dna[0].x, dna[0].y, dna[0].z]))
            if not .14 <= distance <= .18:
                raise ValueError('Invalid biotin O4T–DNA P bond length')
            links.append(dict(particle_id=p.id, tetramer=r.tetramer_index, pocket=r.chain,
                              strand_id=r.strand_id, ligand=lig, dna=dna[0], bond_nm=float(distance)))
        if not p.coating:
            continue
        for ti in sorted({r.tetramer_index for r in p.biotin_dna}):
            matrix = p.pose.to_array() @ p.coating.poses[ti].to_array()
            for chain in 'ABCD':
                atoms = [a for a in p.coating.protein.atoms if a.chain_id == chain and a.res_name != 'BTN']
                residues = sorted({a.res_seq for a in atoms})
                if not residues or residues != list(range(residues[0], residues[-1]+1)):
                    raise ValueError('Protein chain has unresolved internal residues')
                owner = f'{p.id}:strep:{ti}:{chain}'
                chain_id = 'ST'+str(len(proteins))
                proteins.append(dict(particle_id=p.id, tetramer=ti, chain=chain, chain_id=chain_id,
                                     first_resid=residues[0], last_resid=residues[-1],
                                     termini='NTER/CTER on resolved construct; missing terminal tails not reconstructed'))
                for a in atoms:
                    pos = matrix[:3, :3] @ np.array([a.x, a.y, a.z]) + matrix[:3, 3]
                    main.append(Atom(serial=len(main), name=a.name, element=a.element,
                        residue=a.res_name, chain_id=chain_id, seq_num=a.res_seq,
                        x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
                        strand_id='__protein__'+owner, helix_id='__protein__'+owner,
                        bp_index=a.res_seq, direction='FORWARD'))
    # Export-only indices: source atom serials are not PSF indices.
    model = AtomisticModel([replace(a, serial=i) for i, a in enumerate(main)], [])
    return d, model, links, proteins


def write_preparation(design, output):
    """Write molecular inputs, persistent identity and a blocked psfgen recipe."""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    d, model, links, proteins = prepare_components(design)
    output.mkdir(parents=True)
    inputs = output/'inputs'; inputs.mkdir()
    segments, pdb = _write_segment_pdbs(d, inputs, model)
    complex_lines = [line for line in pdb.splitlines() if line.startswith(('REMARK', 'CRYST1'))]
    by_chain = {s['chain_id']: s for s in segments}
    identity = []
    for a in model.atoms:
        seg = by_chain[a.chain_id]['segid']
        complex_lines.append(_psfgen_pdb_record(a, a.serial+1, seg))
        identity.append(dict(segid=seg, resid=a.seq_num, atom_name=_psfgen_atom_name(a),
            component='protein' if a.helix_id.startswith('__protein__') else 'dna',
            strand_id=a.strand_id, helix_id=a.helix_id, bp_index=a.bp_index,
            direction=a.direction, residue=a.residue, copy_k=a.copy_k, extra_base_k=a.extra_base_k,
            extension_id=a.extension_id, source_atom_name=a.name))
    script = _psfgen_script(segments, output/'system', extra_topologies=[output/'biotin_teg.rtf'])
    additions, bond_map, conect = [], [], []
    for i, link in enumerate(links):
        segid = f'L{i:03X}'
        if len(segid) != 4: raise ValueError('Too many ligand segments')
        dna_seg = by_chain[link['dna'].chain_id]['segid']
        # 5TER deletes P/O1P/O2P: a biotin phosphate must retain those atoms.
        script = script.replace(f'segment {dna_seg} {{\n  first 5TER',f'segment {dna_seg} {{\n  first NONE')
        script = script.replace(f'patch DEO5 {dna_seg}:1',f'patch DEOX {dna_seg}:1')
        path = inputs/f'{segid}.pdb'
        lines = []
        for j, a in enumerate(link['ligand']):
            a = replace(a, seq_num=1)
            lines.append(_ligand_pdb_record(a, j+1, segid))
            complex_lines.append(_ligand_pdb_record(a, len(model.atoms)+i*28+j+1, segid))
            identity.append(dict(segid=segid, resid=1, atom_name=a.name, component='biotin_teg',
                particle_id=link['particle_id'], tetramer=link['tetramer'], pocket=link['pocket'],
                strand_id=link['strand_id'], source_atom_name=a.name))
        from backend.core.pdb_export import _h36
        names = {a.name: len(model.atoms)+i*28+j+1 for j,a in enumerate(link['ligand'])}
        for bond in chemical_definition()['bonds']:
            left,right = [names[n] for n in bond['atoms']]
            conect.append('CONECT'+_h36(left,5)+_h36(right,5))
        dna_serial = next(a.serial+1 for a in model.atoms if a.strand_id==link['strand_id'] and a.seq_num==1 and a.name=='P')
        conect.append('CONECT'+_h36(names['O4T'],5)+_h36(dna_serial,5))
        path.write_text('\n'.join(lines)+'\nEND\n')
        additions.extend([f'segment {segid} {{', '  first NONE', '  last NONE',
                          '  auto angles dihedrals', f'  pdb {path}', '}',
                          f'coordpdb {path} {segid}', f'patch BTE5 {segid}:1 {dna_seg}:1'])
        bond_map.append(dict(ligand=[segid, 1, 'O4T'], dna=[dna_seg, 1, 'P'],
                             strand_id=link['strand_id'], bond_nm=link['bond_nm']))
    script = script.replace('regenerate angles dihedrals','\n'.join(additions)+'\nregenerate angles dihedrals')
    (output/'build_psfgen.tcl').write_text('# Requires a chemically qualified BTE residue and BTE5 boundary patch.\n'+script)
    (output/'complex_heavy.pdb').write_text('\n'.join(complex_lines+conect)+'\nEND\n')
    (output/'chemical_definition.json').write_text(json.dumps(chemical_definition(),indent=2)+'\n')
    manifest = dict(schema='nadoc.strep-biotin-namd.v1', simulation_ready=False,
        scope='gold-free DNA plus occupied streptavidin tetramers and biotin-TEG',
        omitted_gold_ids=[p.id for p in d.nanoparticles], proteins=proteins,
        protein_biotin_binding='noncovalent; no protein-ligand bond or extra spring',
        covalent_links=bond_map, identity=identity,
        blocked_by=['Missing qualified all-hydrogen BTE topology, charges and parameters',
                    'Missing qualified BTE5 DNA phosphodiester boundary patch and cross terms'],
        source_catalog_sha256=hashlib.sha256(json.dumps(CATALOG,sort_keys=True).encode()).hexdigest())
    (output/'mapping.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def resolve_psf_identity(psf_text, identity):
    """Resolve final 1-based PSF IDs after hydrogen insertion; reject ambiguity."""
    atoms = parse_psf_atoms(psf_text)
    lookup = {}
    for a in atoms:
        key = (a.segid, int(a.resid), a.atomname)
        if key in lookup: raise ValueError(f'Duplicate PSF identity {key}')
        lookup[key] = a.serial
    result = []
    for record in identity:
        key = (record['segid'], record['resid'], record['atom_name'])
        if key not in lookup and record.get('component') == 'protein':
            aliases = {'O': 'OT1', 'OXT': 'OT2'}
            if record.get('residue') == 'ILE': aliases['CD1'] = 'CD'
            key = (key[0], key[1], aliases.get(key[2], key[2]))
        if key not in lookup: raise ValueError(f'Missing mapped atom {key}')
        result.append(dict(record, psf_index=lookup[key]))
    return result
