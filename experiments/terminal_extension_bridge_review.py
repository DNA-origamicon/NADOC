"""Read-only terminal-tail A/B evidence, including a complete 2HB phase sweep."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import html
import json
from pathlib import Path

import numpy as np

from backend.core.atomistic import Atom, AtomisticModel, build_atomistic_model
from backend.core.deformation import effective_helix_for_geometry
from backend.core.models import Design, StrandExtension
from backend.core.molecular_placement_audit import _affected_serials, _model_diagnostics
from backend.core.ring_piercing import residue_key
from experiments.mrdna_frame_review_figure import render_plate
from experiments.terminal_extension_bridge_candidate import build_candidate


def xyz(model):
    return np.array([[a.x, a.y, a.z] for a in model.atoms])


def load_model(data):
    return AtomisticModel(atoms=[Atom(**a) for a in data['atoms']],
                          bonds=[tuple(b) for b in data['bonds']])


def evaluate(design, current, candidate, label, output):
    models = {'current': current, 'candidate': candidate}
    positions = {s: xyz(m) for s, m in models.items()}
    assert current.bonds == candidate.bonds
    for before, after in zip(current.atoms, candidate.atoms, strict=True):
        assert {k: v for k, v in asdict(before).items() if k not in ('x', 'y', 'z')} == {
            k: v for k, v in asdict(after).items() if k not in ('x', 'y', 'z')}
    root_bonds = [(i, j) for i, j in current.bonds
                  if bool(current.atoms[i].extension_id) != bool(current.atoms[j].extension_id)]
    fixed = {a.serial for a in current.atoms if not a.extension_id
             or a.name not in ("O3'", 'P', "O5'", 'OP1', 'OP2')}
    fixed.update(i for pair in root_bonds for i in pair)
    fixed = sorted(fixed)
    np.testing.assert_array_equal(positions['current'][fixed], positions['candidate'][fixed])
    diagnostics = {s: _model_diagnostics(design, m) for s, m in models.items()}
    affected, displacement = _affected_serials(current, candidate,
        diagnostics['current'], diagnostics['candidate'])
    by_residue = {}
    residue_names = {}
    for a in current.atoms:
        by_residue.setdefault(residue_key(a), set()).add(a.serial)
        residue_names.setdefault(residue_key(a), {})[a.name] = a.serial

    def bridge_geometry(side, source, destination):
        p = positions[side]
        c2, c3, c4, o3 = [p[source[n]] for n in ("C2'", "C3'", "C4'", "O3'")]
        phosphate, o5, c5 = [p[destination[n]] for n in ('P', "O5'", "C5'")]
        def angle(a, b, c):
            u, v = a - b, c - b
            return float(np.rad2deg(np.arccos(np.clip(np.dot(u, v) / np.linalg.norm(u)
                                                     / np.linalg.norm(v), -1, 1))))
        return {'lengths_nm': dict(zip(('C3-O3', 'O3-P', 'P-O5', 'O5-C5'),
                   [float(np.linalg.norm(a - b)) for a, b in
                    ((c3, o3), (o3, phosphate), (phosphate, o5), (o5, c5))])),
                'angles_deg': dict(zip(('C3-O3-P', 'O3-P-O5', 'P-O5-C5'),
                   [angle(*pts) for pts in ((c3, o3, phosphate), (o3, phosphate, o5), (phosphate, o5, c5))])),
                'C3_signed_volume_nm3': float(np.dot(np.cross(c2 - c3, c4 - c3), o3 - c3))}

    def defects(side, residues):
        d = diagnostics[side]
        return {
            'clashes': [h for h in d['clashes'] if residues.intersection(h['serials'])],
            'piercings': [h for h in d['piercing']['pierced']
                         if residues.intersection([*h['bond_serials'], *h['ring_serials']])],
        }

    junctions = []
    for i, j in current.bonds:
        a, b = current.atoms[i], current.atoms[j]
        if {a.name, b.name} != {"O3'", 'P'} or not (a.extension_id or b.extension_id):
            continue
        residues = by_residue[residue_key(a)] | by_residue[residue_key(b)]
        source, destination = (a, b) if a.name == "O3'" else (b, a)
        geometry = {s: bridge_geometry(s, residue_names[residue_key(source)],
                                      residue_names[residue_key(destination)]) for s in models}
        if not np.array_equal(positions['current'][source.serial], positions['candidate'][source.serial]):
            # The rigid native sugar template and its proper rotation have
            # negative C2/C4/O3 oriented volume about C3. No epimer is accepted.
            assert geometry['candidate']['C3_signed_volume_nm3'] < 0
        junctions.append({
            'serials': [i, j], 'root': bool(a.extension_id) != bool(b.extension_id),
            'identity': [asdict(a), asdict(b)],
            'length_nm': {s: float(np.linalg.norm(p[i] - p[j])) for s, p in positions.items()},
            'max_endpoint_displacement_nm': float(max(np.linalg.norm(
                positions['candidate'][k] - positions['current'][k]) for k in (i, j))),
            'defects': {s: defects(s, residues) for s in models},
            'bridge_geometry': geometry,
        })
    bundle = {'phase_deg': label, 'read_only': True,
              'figure_title': f'Terminal-extension bridge initialization: {label}\n'
                  'Current: existing solver. Candidate: native C3 exit, exact bond lengths. Roots and sugars fixed.',
              'affected_atom_serials': affected, 'displacement': displacement,
              'junctions': junctions,
              **{s: {'atoms': [asdict(a) for a in m.atoms], 'bonds': m.bonds,
                     'diagnostics': diagnostics[s]} for s, m in models.items()}}
    artifact = f'{label}.json.gz'
    with gzip.open(output / artifact, 'wt') as stream:
        json.dump(bundle, stream, separators=(',', ':'))

    def keys(d, kind):
        if kind == 'piercings':
            return {(tuple(h['bond_serials']), tuple(h['ring_serials']))
                    for h in d['piercing']['pierced']}
        hits = d['clashes'] if kind == 'clashes' else d['bonds']['overstretched']
        return {tuple(h['serials']) for h in hits}

    row = {'label': label, 'artifact': artifact, 'root_bonds_exact': len(root_bonds),
           'fixed_atoms_exact': len(fixed),
           'max_atom_displacement_nm': float(np.max(np.linalg.norm(
               positions['candidate'] - positions['current'], axis=1))),
           'diagnostics': diagnostics, 'junctions': junctions,
           'introduced': {k: len(keys(diagnostics['candidate'], k) - keys(diagnostics['current'], k))
                          for k in ('clashes', 'piercings', 'bond_flags')}}
    print(json.dumps({k: v for k, v in row.items() if k not in ('diagnostics', 'junctions')}), flush=True)
    return row


def build_review(output, report):
    rows = report['rows']
    chosen = rows[:2]
    for kind in ('clashes', 'piercings', 'bond_flags'):
        row = max(rows, key=lambda r: r['introduced'][kind])
        if row not in chosen:
            chosen.append(row)
    sections = []
    for row in chosen:
        with gzip.open(output / row['artifact'], 'rt') as stream:
            bundle = json.load(stream)
        png = f"{row['label']}.png"
        render_plate(bundle, output / png)
        table = []
        chemical = []
        for j in row['junctions']:
            values = [j['serials'], 'root (unchanged)' if j['root'] else 'internal tail',
                      *(f"{j['length_nm'][s]:.7f}" for s in ('current', 'candidate')),
                      f"{j['length_nm']['candidate'] - j['length_nm']['current']:+.7f}",
                      f"{j['max_endpoint_displacement_nm']:.7f}",
                      *(f"{len(j['defects']['current'][k])} → {len(j['defects']['candidate'][k])}"
                        for k in ('clashes', 'piercings'))]
            table.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in values) + '</tr>')
            if j['max_endpoint_displacement_nm']:
                chemical.append(f"<p>Changed junction {j['serials']} — C3 oriented volumes (nm³): "
                    + ' → '.join(f"{j['bridge_geometry'][s]['C3_signed_volume_nm3']:.9f}" for s in ('current','candidate'))
                    + '</p><pre>' + html.escape(json.dumps(j['bridge_geometry'], indent=2)) + '</pre>')
        sections.append(f"<h2>{row['label']}</h2><img src='{png}' alt='Current, Candidate, overlay and exact defect'>"
                        f"<p><a href='{row['artifact']}'>All atoms, bonds and detector hits</a>. "
                        f"Introduced hits: {html.escape(str(row['introduced']))}.</p>"
                        '<details><summary>Every terminal covalent junction</summary><table><tr>'
                        '<th>Atoms</th><th>Kind</th><th>Current nm</th><th>Candidate nm</th><th>Δ length nm</th>'
                        '<th>Max endpoint move nm</th><th>Clashes</th><th>Piercings</th></tr>'
                        + ''.join(table) + '</table></details>'
                        + '<details><summary>Changed-link bond lengths, angles and C3 stereochemistry</summary>'
                        + ''.join(chemical) + '</details>')
    page = ("<!doctype html><meta charset='utf-8'><title>Terminal-extension linker review</title>"
            '<style>body{font:16px system-ui;max-width:1500px;margin:2rem auto;padding:1rem}'
            'img{width:100%}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.3rem}</style>'
            '<h1>Terminal-extension linker initialization</h1><p><strong>Isolated diagnostic; no production change.</strong></p>'
            '<p>Current is the approved 14.625° convention and existing linker solver. Candidate retries only '
            'an internal terminal-tail O3′–P bond that already crosses its own source sugar ring. It restarts '
            'with the native C3′–O3′ direction fixed, all four bridge bond lengths constrained to the existing '
            'canonical values, and the three bridge angles fitted. This preserves C3′ stereochemistry. '
            'A failed solve or remaining self-piercing retains the current linker. Already clear links remain '
            'byte-for-byte unchanged. Angle changes are displayed explicitly below. '
            'Sugar/base atoms, host atoms, attachment-root endpoints, topology, phase constants and detectors stay fixed.</p>'
            '<h2>Construction and the difference to inspect</h2><ol>'
            '<li>Failing specimen: regenerate smallO using Create Bundle, Auto Scaffold, Full Autostaple, '
            'Route for Polymerization and sequence assignment; add it to an assembly and Polymerize Origami to three copies. '
            'Flatten the same assembly for NAMD preparation. This reproduces the original failing test.</li>'
            '<li>Current O3′(ext2)–P(ext1), serials 48262/48233, crosses the ext2 sugar ring although its length is 0.16 nm. '
            'Inspect the highlighted bond and ring in the same-frame close-up.</li>'
            '<li>Candidate is an offline solver diagnostic on that identical covalent graph, not an authored feature history. '
            'It changes no attachment root and does not close strained Direct connections.</li>'
            '<li>Representative 2HB control: copy Examples/2hb_xover_val.nadoc; add independent 5′ and 3′ extensions '
            'GATGGTGGTTCCGAAA on each of its two scaffold strands. Sweep both resolved helix phases through '
            '0–350° in 10° steps in diagnostic copies. No design or simulation input is saved.</li></ol>'
            '<p>Counts below include unchanged defects elsewhere in each design. New contacts and piercings are '
            'reported explicitly; a lower total does not establish physical validity.</p>'
            + ''.join(sections) + "<p><a href='qualification.json'>All 36 phases, every junction, exact hits and source hashes</a></p>")
    (output / 'review.html').write_text(page)


def main(output, probe):
    output.mkdir(parents=True, exist_ok=True)
    design = Design.model_validate_json(gzip.decompress((probe / 'source.json.gz').read_bytes()))
    assembly_snapshot = design.model_dump_json()
    with gzip.open(probe / 'current.json.gz', 'rt') as stream:
        source_model = load_model(json.load(stream))
    assembly_candidate = build_candidate(design)
    assert design.model_dump_json() == assembly_snapshot
    rows = [evaluate(design, source_model, assembly_candidate, 'smallO', output)]
    original = Design.model_validate_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    original_snapshot = original.model_dump_json()
    with_tails = original.model_copy(deep=True)
    for index in (0, 2):
        for end in ('five_prime', 'three_prime'):
            with_tails.extensions.append(StrandExtension(id=f'audit-tail-{index}-{end}',
                strand_id=with_tails.strands[index].id, end=end, sequence='GATGGTGGTTCCGAAA'))
    # Root construction moves host linker atoms, so compare against the native
    # design WITH these tails, not against its bare-duplex coordinates.
    baseline = xyz(build_atomistic_model(with_tails, frame_sink={}))
    for phase in range(0, 360, 10):
        design = with_tails.model_copy(deep=True)
        if phase:
            design.helices = [effective_helix_for_geometry(h, original).model_copy(update={
                'grid_pos': None, 'phase_offset': effective_helix_for_geometry(h, original).phase_offset
                    + np.deg2rad(phase)}) for h in original.helices]
        snapshot = design.model_dump_json()
        current = build_atomistic_model(design, frame_sink={})
        if phase == 0:
            np.testing.assert_array_equal(xyz(current), baseline)
        elif np.max(np.linalg.norm(xyz(current) - baseline, axis=1)) < 0.01:
            raise AssertionError('Phase change was erased')
        candidate = build_candidate(design)
        rows.append(evaluate(design, current, candidate, f'2hb-phase-{phase:03d}', output))
        assert design.model_dump_json() == snapshot
    assert original.model_dump_json() == original_snapshot
    report = {'rows': rows, 'production_changed': False, 'physical_dynamics': False,
              'source_sha256': hashlib.sha256((probe / 'source.json.gz').read_bytes()).hexdigest(),
              'code_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                  Path(__file__), Path('experiments/terminal_extension_bridge_candidate.py'),
                  Path('backend/core/atomistic.py'), Path('backend/core/atomistic_minimisers.py'))}}
    (output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    build_review(output, report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('probe', type=Path)
    args = parser.parse_args()
    main(args.output, args.probe)
