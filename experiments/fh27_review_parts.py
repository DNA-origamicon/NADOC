"""Rebuild FH-27 parts with executed, independently replayed construction logs.

The 2HB is explicitly reconstructed from helix/strand authoring inputs; its lost
original history is not invented. Molecular candidates remain isolated steps.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import gzip
from pathlib import Path
from uuid import UUID, uuid5

import numpy as np

from backend.core import models as m
from backend.core.atomistic import build_atomistic_model
from backend.core.part_history_proof import command_rows
from experiments.recorded_review_process import Process, sha
from scripts.agent_structure_guard import publish


NAMESPACE = UUID('e85d19b3-fcf7-4556-9c83-43eed53541dd')


def identity(name):
    return str(uuid5(NAMESPACE, name))


def terminal():
    from tests.periodic_assembly_fixture import periodic_assembly
    source, _ = periodic_assembly()
    process = Process('smallO')
    labels = ['Six-cell honeycomb bundle, 42 bp', 'Seamed scaffold routing',
              'Full Autostaple', 'Route for Polymerization: cap-tip periodic staples',
              'Assign M13mp18 scaffold sequence', 'Assign complementary staple sequences']
    for (_, kind, params), label in zip(command_rows(source, 100), labels, strict=True):
        process.append(kind, params, label)
    process.diagnostic('assembly-add', {'assembly_id':identity('assembly'),
        'instance_id':identity('seed-instance'), 'name':'smallO'}, 'Add the completely logged smallO source to an assembly')
    process.diagnostic('assembly-polymerize', {'identity_seed':identity('polymer-ids'),
        'count':3, 'direction':'forward'}, 'Polymerize Origami: three repeats, forward, derived periodic transform')
    process.diagnostic('assembly-flatten', {},
        'Materialize the assembly for NAMD: internal seams plus full terminal staple halves; no simulation')
    return process


def two_hb():
    source = m.Design.from_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    process = Process('2HB explicit reconstruction')
    for helix in source.helices:
        process.diagnostic('author-helix', helix.model_dump(mode='json'),
            f'Reconstruct {helix.id}: bp {helix.bp_start}–{helix.bp_start+helix.length_bp-1}; exact source helix inputs')
    for strand in source.strands:
        path = ' → '.join(f'{d.helix_id}:{d.start_bp}→{d.end_bp} ({d.direction.value})' for d in strand.domains)
        process.diagnostic('author-strand', strand.model_dump(mode='json'),
            f'Reconstruct {strand.id}, 5′→3′: {path}; explicit sequence retained')
    process.diagnostic('derive-connectivity', {}, 'Derive crossover and ligation records from the authored strand traversals')
    actual = build_atomistic_model(process.design)
    original = build_atomistic_model(source)
    assert [asdict(a) for a in actual.atoms] == [asdict(a) for a in original.atoms]
    assert actual.bonds == original.bonds
    return process


def adverse():
    process = two_hb()
    for index in (0, 2):
        strand = process.design.strands[index]
        for end in ('five_prime', 'three_prime'):
            ext = m.StrandExtension(id=f'audit-tail-{index}-{end}', strand_id=strand.id,
                                   end=end, sequence='GATGGTGGTTCCGAAA')
            process.append('extension-upsert', {'_proof_version':2,
                'entries':[{'create':True, 'extension':ext.model_dump(mode='json')}]},
                f'Add 16-base {"5′" if end == "five_prime" else "3′"} extension to {strand.id}: GATGGTGGTTCCGAAA')
    process.diagnostic('phase-control', {'degrees':210, 'namespace':'review-phase210'},
        'Diagnostic phase control: rotate both resolved helix frames +210°; preserve strand traversal')
    return process


def description(kind, side):
    return (f'FH-27 {kind} / {side}. Full executed construction is in the Feature log. '
        'Independent replay ignores recovery snapshots. The 2HB source, where used, is explicitly '
        'reconstructed helix by helix and strand by strand; its original history was absent. '
        'Diagnostic Molecular Placement Audit steps are isolated and have no ordinary native parameter editor. '
        'Use the feature-log slider or Construction process animation to inspect when the ends appear. '
        'No dynamics or molecular promotion. Verify using scripts/agent_structure_guard.py.')


def attachment_cameras(design, terminal_assembly):
    """Matched root views; presentation only, with every atom retained."""
    from backend.core.ring_piercing import residue_key
    model = design.atomistic_reference
    atoms = model.atoms
    coords = np.array([[a.x,a.y,a.z] for a in atoms])
    residues = {}
    for a in atoms:
        residues.setdefault(residue_key(a), {})[a.name] = a.serial
    targets = [('AN','five_prime'),('AR','three_prime')] if terminal_assembly else [('A','five_prime'),('A','three_prime')]
    poses = []
    for index, (chain, end) in enumerate(targets):
        extension = next(e for e in design.extensions if e.end == end and
            any(a.chain_id == chain and a.extension_id == e.id for a in atoms))
        pair = next((atoms[i],atoms[j]) for i,j in model.bonds
            if bool(atoms[i].extension_id) != bool(atoms[j].extension_id)
            and extension.id in (atoms[i].extension_id,atoms[j].extension_id))
        source, destination = pair if pair[0].name == "O3'" else pair[::-1]
        s,t = residues[residue_key(source)],residues[residue_key(destination)]
        c3 = coords[s["C3'"]]
        normal = np.cross(coords[s["C2'"]]-c3, coords[s["C4'"]]-c3)
        normal /= np.linalg.norm(normal)
        across = coords[t["C5'"]]-c3
        across /= np.linalg.norm(across)
        center = coords[[s["C3'"],s["O3'"],t['P'],t["O5'"],t["C5'"]]].mean(axis=0)
        direction = normal + .45*across
        direction /= np.linalg.norm(direction)
        poses.append(m.CameraPose(name=f'{index+5:02} {"5′" if index == 0 else "3′"} attachment root - chain {chain}',
            target=center.tolist(), position=(center+1.6*direction).tolist(), up=across.tolist()))
    return poses


def main(output, manifest, case=None):
    output.mkdir(parents=True, exist_ok=True)
    rows = (json.loads(manifest.read_text())['files'] if case and manifest.exists() else [])
    if case:
        rows = [row for row in rows if f'FH-27 - {case:02d} ' not in row['path']]
    for number, title, builder in ((1,'Terminal linker',terminal), (2,'Adverse contact',adverse),
                                    (3,'mrDNA zero-step',two_hb)):
        if case and case != number:
            continue
        base = builder()
        if number == 3:
            base.diagnostic('phase-control', {'degrees':0, 'namespace':'review-mrdna0'},
                'Resolve native helix frames explicitly for the zero-degree Fine-file control')
        evidence_root = Path('.development-artifacts/feature-history-focus/remaining-failures/implemented-features')
        evidence_path = evidence_root / ({1:'terminal-fixed-exit-review/smallO.json.gz',
            2:'terminal-fixed-exit-review/2hb-phase-210.json.gz',
            3:'mrdna-transport-review/phase-000-zero_pdb.json.gz'}[number])
        evidence = json.loads(gzip.decompress(evidence_path.read_bytes()))
        for side in ('Current', 'Candidate'):
            process = deepcopy(base)
            name = f'FH-27 - {number:02d} {title} - {side}'
            path = output / f'{name}.nadoc'
            old_sha = sha(path) if path.exists() else None
            process.design.id = identity(name + ':recorded-process')
            if number == 3:
                process.diagnostic('mrdna-zero', {'side':side.lower()},
                    f'Zero-step Fine PSF/PDB: {"production reconstruction" if side == "Current" else "isolated native-atom transport"}; no dynamics')
            else:
                process.diagnostic('native-atoms', {}, 'Current native all-atom placement; approved 14.625° template convention')
                if side == 'Candidate':
                    process.diagnostic('terminal-candidate', {},
                        'Isolated candidate: retry internal own-sugar piercing; native C3′ exit, four fixed bond lengths, fit three angles')
            process.diagnostic('document-name', {'name':name, 'description':description(title,side)}, 'Name this process-complete review part')
            design = process.design
            before = np.array([[a[k] for k in 'xyz'] for a in evidence[side.lower()]['atoms']])
            after = np.array([[getattr(a,k) for k in 'xyz'] for a in design.atomistic_reference.atoms])
            assert before.shape == after.shape, (name,before.shape,after.shape)
            delta = float(np.max(np.abs(before-after)))
            assert delta < 1e-9, (name,'geometry differs from retained review evidence',delta)
            assert [list(b) for b in design.atomistic_reference.bonds] == evidence[side.lower()]['bonds']
            if number < 3:
                from experiments.terminal_extension_review_nadoc import cameras
                design.camera_poses = cameras(evidence, number == 1)
                design.camera_poses += attachment_cameras(design, number == 1)
            else:
                previous = m.Design.from_json((Path('workspace/Geometry Review') / 'FH-27 - 03 mrDNA zero-step - Current.nadoc').read_text())
                design.camera_poses = previous.camera_poses
            design.animations = [m.DesignAnimation(name='Geometry review - camera tour (Ball and Stick)',
                keyframes=[m.AnimationKeyframe(name=p.name, camera_pose_id=p.id,
                    hold_duration_s=8, transition_duration_s=1, text=f'{name}: {p.name}',
                    text_font_size_px=20) for p in design.camera_poses])]
            frames = [m.AnimationKeyframe(name=f'F{index+1}: {row.label}', feature_log_index=index,
                hold_duration_s=5, transition_duration_s=0.5, text=f'F{index+1}: {row.label}', text_font_size_px=18)
                for index,row in enumerate(design.feature_log)]
            design.animations.append(m.DesignAnimation(name='Construction process - recorded feature steps', keyframes=frames))
            print('VERIFY',name,'features',len(design.feature_log),flush=True)
            result = publish(design,path,expected_existing_sha256=old_sha)
            result.update(features=len(design.feature_log), atoms=len(design.atomistic_reference.atoms),
                          old_sha256=old_sha, retained_evidence=str(evidence_path),
                          evidence_sha256=sha(evidence_path), max_coordinate_delta_nm=delta)
            rows.append(result)
            manifest.parent.mkdir(parents=True,exist_ok=True)
            manifest.write_text(json.dumps({'files':rows,'geometry_approved':False},indent=2)+'\n')
            print('PUBLISHED',name,flush=True)
    return rows


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('workspace/Geometry Review/Process Complete'))
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--case',type=int,choices=(1,2,3))
    main(**vars(parser.parse_args()))
