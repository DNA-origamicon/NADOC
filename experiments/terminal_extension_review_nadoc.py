"""Write explicitly requested native review captures, never production geometry.

Consumes the already-reviewed atoms; it does not rerun a candidate solver. The
embedded atomistic reference is for Ball and Stick / Stick viewing. Full is the
coarse-grained design and cannot show an atom-only linker difference.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import numpy as np

from backend.core.atomistic import atomistic_reference_topology_hash, build_atomistic_model
from backend.core.deformation import effective_helix_for_geometry
from backend.core.models import (
    AnimationKeyframe, AtomisticReference, CameraPose, Design, DesignAnimation,
    DesignMetadata, StrandExtension,
)
from backend.core.part_history_proof import import_root


def read_bundle(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def phase_design(source):
    original = Design.model_validate_json(source.read_text())
    design = original.model_copy(deep=True)
    for index in (0, 2):
        for end in ('five_prime', 'three_prime'):
            design.extensions.append(StrandExtension(
                id=f'audit-tail-{index}-{end}', strand_id=design.strands[index].id,
                end=end, sequence='GATGGTGGTTCCGAAA'))
    design.helices = [effective_helix_for_geometry(h, original).model_copy(update={
        'grid_pos': None,
        'phase_offset': effective_helix_for_geometry(h, original).phase_offset + np.deg2rad(210),
    }) for h in original.helices]
    return design


def portable_phase_capture(design, bundle):
    # h_XY_* legacy IDs recreate grid_pos on load, which would erase the
    # diagnostic phase. Namespace these two opaque IDs consistently in graph
    # and atom records; preserve every coordinate and chemical identity.
    mapping = {h.id: f'review-phase210::{h.id}' for h in design.helices}

    def remap(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value

    payload = design.model_dump(mode='json')
    payload.update(feature_log=[], feature_log_cursor=-1, recipe_root=None, input_sources={})
    return Design.model_validate(remap(payload)), remap(bundle)


def cameras(bundle, assembly):
    xyz = np.array([[a[k] for k in ('x', 'y', 'z')] for a in bundle['current']['atoms']])
    center = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    span = np.ptp(xyz, axis=0).max()
    poses = [CameraPose(name='01 Whole structure', target=center.tolist(),
                       position=(center + span * np.array([1.1, .8, 1.2])).tolist())]
    if assembly:
        ring = xyz[[48264, 48263, 48261, 48259, 48260]]
        focus = ring.mean(axis=0)
        _, _, basis = np.linalg.svd(ring - focus)
        normal, along = basis[-1], basis[0]
        up = np.cross(normal, along)
        views = [('02 Terminal overhang', normal, 5.0),
                 ('03 Sugar ring face', normal + .25 * along, 1.25),
                 ('04 Sugar ring edge', along + .2 * normal, 1.25)]
    else:
        after = np.array([[a[k] for k in ('x', 'y', 'z')] for a in bundle['candidate']['atoms']])
        focus = np.mean([xyz[3243], xyz[3246], after[3243]], axis=0)
        # Choose shared viewing directions with minimal atom occlusion. This
        # changes cameras only; no filtering, hidden atoms or coordinate edits.
        views_ranked = []
        keep = np.ones(len(xyz), dtype=bool)
        keep[[3243, 3246]] = False
        for i in range(400):
            z = 1 - 2 * (i + .5) / 400
            angle = i * np.pi * (3 - np.sqrt(5))
            direction = np.array([np.sqrt(1 - z*z) * np.cos(angle),
                                  np.sqrt(1 - z*z) * np.sin(angle), z])
            score = 0.
            for positions in (xyz, after):
                for serial in (3243, 3246):
                    delta = positions[keep] - positions[serial]
                    depth = delta @ direction
                    radial_sq = np.sum(delta * delta, axis=1) - depth * depth
                    score += np.sum(np.exp(-radial_sq / .08**2)
                                    * np.where((depth > 0) & (depth < 1.5), 10.,
                                               np.where((depth > -1) & (depth <= 0), 1., 0.)))
            views_ranked.append((float(score), direction))
        views_ranked.sort(key=lambda item: item[0])
        normal = views_ranked[0][1]
        alternate = next(v for _, v in views_ranked if np.dot(v, normal) < .5)
        up = np.array([0., 0., 1.])
        views = [('02 Terminal overhang', normal, 4.0),
                 ('03 OP2 C4 contact', normal, 1.4),
                 ('04 OP2 C4 alternate', alternate, 1.4)]
    for name, direction, distance in views:
        direction = direction / np.linalg.norm(direction)
        poses.append(CameraPose(name=name, target=focus.tolist(), up=up.tolist(),
                                position=(focus + direction * distance).tolist()))
    return poses


def write_pair(design, bundle, output, stem, assembly, source_path):
    # Establish that the saved all-atom specimen belongs to this exact graph and
    # placement, before adding review metadata / capturing its topology root.
    current = build_atomistic_model(design, frame_sink={})
    assert [asdict(a) for a in current.atoms] == bundle['current']['atoms']
    assert [list(b) for b in current.bonds] == bundle['current']['bonds']
    assert bundle['current']['bonds'] == bundle['candidate']['bonds']
    for a, b in zip(bundle['current']['atoms'], bundle['candidate']['atoms'], strict=True):
        assert {k: v for k, v in a.items() if k not in ('x', 'y', 'z')} == {
            k: v for k, v in b.items() if k not in ('x', 'y', 'z')}
    poses = cameras(bundle, assembly)
    construction = (
        'Create Bundle (smallO), Auto Scaffold, Full Autostaple, Route for Polymerization, '
        'Assign Scaffold Sequence, Assign Staple Sequences; add to assembly; Polymerize Origami '
        'to three repeats; flatten for NAMD preparation. Complete assembly: 18 helices, 2394 nt.'
        if assembly else
        'Diagnostic copy of Examples/2hb_xover_val.nadoc; add GATGGTGGTTCCGAAA at both ends '
        'of its two scaffold strands; resolve helix frames and add 210 degrees to both phases. '
        'Helix IDs use the review-phase210:: prefix to retain these resolved frames on reopen. '
        'This is a phase stress control, not the failing polymerized assembly.'
    )
    focus = (
        "AN14 DA ext2 O3' serial 48262 to AN15 DA ext1 P serial 48233 crosses the ext2 sugar ring. "
        'Ring serials: 48264,48263,48261,48259,48260. This is an internal 5-prime tail link, '
        'not its attachment root. Candidate moves only 48233,48234,48235,48236,48262; '
        'all 12 attachment roots, sugar rings and bases stay exact.'
        if assembly else
        "A57 DT ext5 OP2 serial 3243 and C4' serial 3246 on audit-tail-0-three_prime. "
        'Current separation 0.305647 nm; Candidate 0.075238 nm. This new overlap remains '
        'despite fewer total contacts (9 to 8) and no remaining piercings (4 to 0).'
    )
    rows = []
    for side in ('current', 'candidate'):
        name = f'{stem} - {side.title()}'
        path = output / f'{name}.nadoc'
        notes = (
            'Current: exact Export atoms from the failing-test investigation, using the approved '
            '14.625 degree template convention.' if side == 'current' else
            'Candidate: isolated retry of already self-piercing internal tail links. Fix native '
            'C3-O3 direction and all four canonical bridge bond lengths; fit remaining angles. '
            'Unapproved diagnostic, not a relaxed model or approved simulation seed.'
        )
        copy = design.model_copy(deep=True)
        copy.id = str(uuid4())
        copy.feature_log = []
        copy.feature_log_cursor = -1
        copy.feature_log_sub_cursor = None
        copy.recipe_root = None
        copy.repair_draft = None
        copy.input_sources = {}
        copy.atomistic_reference = None
        copy.camera_poses = poses
        copy.animations = [DesignAnimation(name='Geometry review - camera tour (Ball and Stick)',
            keyframes=[AnimationKeyframe(name=p.name, camera_pose_id=p.id,
                hold_duration_s=5 if i < 2 else 10, transition_duration_s=1,
                text=[f'{name}\nCaptured atomistic review - use Ball and Stick',
                      'Internal tail link; attachment roots unchanged' if assembly else
                      '210 degree phase stress control; not the failing assembly',
                      ('Current: O3-P passes through its own sugar' if side == 'current' else
                       'Candidate: piercing removed; linker angles change') if assembly else
                      f'OP2 (3243) / C4\u2032 (3246): {"0.305647" if side == "current" else "0.075238"} nm',
                      'Same saved camera in Current and Candidate; orbit to inspect the link'][i],
                text_font_size_px=20) for i, p in enumerate(poses)])]
        now = datetime.now(timezone.utc).isoformat()
        copy.metadata = DesignMetadata(name=name, description=(
            notes + '\nConstruction: ' + construction + '\nFocus: ' + focus +
            '\nViewing: View > Representation > Ball and Stick (or Stick). Animations > Camera Poses: '
            '01 whole, 02 tail, 03 defect, 04 alternate angle. Animation is a camera tour only. '
            'Full is coarse-grained and cannot show this atom-only difference. '
            'Topology is an explicit captured import root; no candidate construction history is invented. '
            'Atoms are embedded, not MD-derived. Editing topology/placement invalidates the reference '
            'and regenerates ordinary geometry. These are inspection copies, not approved simulation inputs.'),
            tags=['geometry-review', 'atomistic-capture', side, 'not-simulation-qualified'],
            created_at=now, modified_at=now,
            identity_last_known_path=f'Geometry Review/{name}.nadoc', identity_confirmed_at=now)
        # The small import root captures topology; the large exact reference is
        # the separate physical/display field, not a fabricated feature command.
        copy.recipe_root = import_root(copy)
        model = bundle[side]
        copy.atomistic_reference = AtomisticReference(
            source=f'isolated diagnostic capture: {source_path.name} / {side}',
            notes=notes + ' Not MD-derived. ' + focus,
            topology_hash=atomistic_reference_topology_hash(copy),
            atoms=model['atoms'], bonds=model['bonds'])
        raw = copy.model_dump_json()
        reopened = Design.model_validate_json(raw)
        for fast in (False, True):
            displayed = build_atomistic_model(reopened, fast_bridges=fast)
            assert [asdict(a) for a in displayed.atoms] == model['atoms'], {
                'reference_hash': reopened.atomistic_reference.topology_hash,
                'reopened_hash': atomistic_reference_topology_hash(reopened),
                'first_difference': next(((asdict(a), b) for a, b in zip(displayed.atoms, model['atoms'])
                                          if asdict(a) != b), None),
            }
            assert [list(b) for b in displayed.bonds] == model['bonds']
        with path.open('x') as stream:
            stream.write(raw)
        rows.append({'path': str(path), 'id': copy.id, 'bytes': path.stat().st_size,
                     'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                     'review_bundle_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                     'atoms': len(model['atoms']), 'bonds': len(model['bonds']),
                     'helices': len(copy.helices), 'strands': len(copy.strands),
                     'roundtrip_exact': True, 'display_and_export_reference_exact': True})
    return rows


def main(source, review, two_hb, output, manifest):
    names = ['Polymerized assembly', 'Tail phase 210']
    output.mkdir(parents=True, exist_ok=True)
    for name in names:
        for side in ('Current', 'Candidate'):
            if (output / f'{name} - {side}.nadoc').exists():
                raise FileExistsError(f'Refusing to overwrite {name} - {side}.nadoc')
    rows = []
    for design, label, stem, assembly in (
        (Design.model_validate_json(gzip.decompress(source.read_bytes())), 'smallO', names[0], True),
        (phase_design(two_hb), '2hb-phase-210', names[1], False),
    ):
        bundle_path = review / f'{label}.json.gz'
        bundle = read_bundle(bundle_path)
        if not assembly:
            design, bundle = portable_phase_capture(design, bundle)
        rows.extend(write_pair(design, bundle, output, stem, assembly, bundle_path))
    manifest.write_text(json.dumps({'files': rows, 'production_changed': False,
        'geometry_approved': False, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--two-hb', type=Path, default=Path('Examples/2hb_xover_val.nadoc'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    main(**vars(parser.parse_args()))
