"""Author corrected Gerling Fig. S1 variants from the sequence-verified design.

The user explicitly requested the two scaffold forced ligations and the outer
overhangs. Internal single-T caps remain terminal inserts in the full version.
No production code, original design, or molecular geometry constants are edited.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / 'workspace/Gerling2018_FigS1_p7560_SEQUENCE_RECONSTRUCTED.nadoc'
EVIDENCE = ROOT / '.development-artifacts/gerling2018_trace_reconstruction_20261027'
DEFAULT_OUT = ROOT / '.development-artifacts/gerling2018_corrected_variants_20261028'
LOOP_ID = 'gerling_p7560_ss_loop'
LOOP_START = 39
LOOP_CUT = 33
SEQUENCE_START = 7494 + LOOP_CUT


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def add_scaffold_loop(source, scaffold):
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Domain, ForcedLigation, Helix, Vec3

    design = source.model_copy(deep=True)
    strand = design.scaffolds()[0]
    assert strand.sequence == scaffold[:7494]
    assert len(strand.domains) == 83
    first, last = strand.domains[0], strand.domains[-1]
    parent = design.find_helix(first.helix_id)
    assert parent.label == '41' and first.start_bp == 71 and last.end_bp == 72
    # A separate, unpaired carrier beside helix 41. Its pose is an editable
    # straight schematic placement, not a prediction of the ssDNA conformation.
    loop = Helix(
        id=LOOP_ID, label='42', bp_start=LOOP_START, length_bp=66,
        axis_start=Vec3(x=parent.axis_start.x, y=parent.axis_start.y + 5,
                        z=LOOP_START * BDNA_RISE_PER_BP),
        axis_end=Vec3(x=parent.axis_start.x, y=parent.axis_start.y + 5,
                      z=(LOOP_START + 65) * BDNA_RISE_PER_BP),
        direction='FORWARD', phase_offset=parent.phase_offset,
        twist_per_bp_rad=parent.twist_per_bp_rad,
    )
    design.helices.append(loop)
    # NADOC stores linear strands. Put its bookkeeping nick inside the loop,
    # retaining both loop-to-bundle connections and all original paired bases.
    head = Domain(helix_id=LOOP_ID, start_bp=LOOP_START + LOOP_CUT,
                  end_bp=LOOP_START + 65, direction='FORWARD')
    tail = Domain(helix_id=LOOP_ID, start_bp=LOOP_START,
                  end_bp=LOOP_START + LOOP_CUT - 1, direction='FORWARD')
    strand.domains = [head, *strand.domains, tail]
    strand.sequence = scaffold[SEQUENCE_START:] + scaffold[:SEQUENCE_START]
    strand.name = 'p7560 / 7494 paired + 66 ssDNA on helix 42'
    strand.notes = (
        'Unpaired scaffold indices 7494–7559 occupy helix 42 BP39–104. '
        'Forced ligations: helix 41 BP72 → helix 42 BP39; '
        'helix 42 BP104 → helix 41 BP71. NADOC sequence-start break is '
        'helix 42 BP71/72, corresponding to original p7560 indices 7526/7527. '
        'The stored scaffold is circularly rotated by 7527 bases; paired register '
        'is unchanged. This bookkeeping break does not infer a physical nick.'
    )
    design.extensions = [e for e in design.extensions if e.strand_id != strand.id]
    for label, a, b in [('loop_to_bundle', head, first), ('bundle_to_loop', last, tail)]:
        design.forced_ligations.append(ForcedLigation(
            id=f'p7560_{label}', three_prime_helix_id=a.helix_id,
            three_prime_bp=a.end_bp, three_prime_direction=a.direction,
            five_prime_helix_id=b.helix_id, five_prime_bp=b.start_bp,
            five_prime_direction=b.direction,
        ))
    return design


def add_outer_overhangs(design, records):
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Domain, OverhangSpec
    from backend.core.sequences import assign_staple_sequences

    helices = {h.id: h for h in design.helices}
    bounds = {h.id: (h.bp_start, h.bp_start + h.length_bp - 1) for h in design.helices}
    removed_extensions, counts = set(), Counter()
    for record in records:
        strand = design.find_strand(f'published_{record["published_id"]:03d}')
        for end, key in [('five_prime', 'terminal_T_5prime'), ('three_prime', 'terminal_T_3prime')]:
            five = end == 'five_prime'
            dom = strand.domains[0 if five else -1]
            bp = dom.start_bp if five else dom.end_bp
            lo, hi = bounds[dom.helix_id]
            length = record[key]
            if bp not in (lo, hi):
                assert length == 1
                counts['internal_single_T_caps'] += 1
                continue
            step = 1 if dom.direction.value == 'FORWARD' else -1
            start, stop = ((bp - step * length, bp - step) if five
                           else (bp + step, bp + step * length))
            assert all(p < lo or p > hi for p in range(min(start, stop), max(start, stop) + 1))
            suffix = '5p' if five else '3p'
            oid = f'ovhg_inline_{strand.id}_{suffix}'
            oh = Domain(helix_id=dom.helix_id, start_bp=start, end_bp=stop,
                        direction=dom.direction, overhang_id=oid)
            strand.domains = [oh, *strand.domains] if five else [*strand.domains, oh]
            helix = helices[dom.helix_id]
            design.overhangs.append(OverhangSpec(
                id=oid, helix_id=dom.helix_id, strand_id=strand.id, sequence='T' * length,
                label=f'Staple {record["published_id"]} {suffix} {length}T / helix {helix.label}',
                pivot=[helix.axis_start.x, helix.axis_start.y, bp * BDNA_RISE_PER_BP],
            ))
            removed_extensions.add(f'{strand.id}_{end}')
            counts[f'outer_{length}T_overhangs'] += 1
    design.extensions = [e for e in design.extensions if e.id not in removed_extensions]
    for helix in design.helices:
        bps = [p for s in design.strands for d in s.domains if d.helix_id == helix.id
               for p in (d.start_bp, d.end_bp)]
        lo, hi = min(bps), max(bps)
        helix.bp_start, helix.length_bp = lo, hi - lo + 1
        helix.axis_start.z, helix.axis_end.z = lo * BDNA_RISE_PER_BP, hi * BDNA_RISE_PER_BP
    assert counts == {'internal_single_T_caps': 342, 'outer_1T_overhangs': 3,
                      'outer_10T_overhangs': 81}
    return assign_staple_sequences(design)


def validate_variant(design, source, records, scaffold, keep_t):
    from backend.core.lattice import autodetect_all_overhangs
    from backend.core.scaffold_length import scaffold_length_checks
    from backend.core.sequences import build_scaffold_base_map, domain_bp_range
    from backend.core.topology_integrity import forced_edge, slot
    from backend.core.validator import validate_design
    from backend.physics.oxdna_interface import topology_rows

    report = validate_design(design)
    assert report.passed, [r.message for r in report.results if not r.ok]
    assert len(design.helices) == 43 and len(design.strands) == 214
    assert len(design.forced_ligations) == len(source.forced_ligations) + 2
    assert len(design.overhangs) == (84 if keep_t else 0)
    assert len(design.extensions) == (342 if keep_t else 0)
    assert all(e.sequence == 'T' and e.strand_id != 'p7560_scaffold' for e in design.extensions)
    assert all(x.extra_bases == ('TT' if keep_t else None)
               for x in [*design.crossovers, *design.forced_ligations]
               if x.id.startswith('published_'))
    base_map = build_scaffold_base_map(design)
    original_map = build_scaffold_base_map(source)
    assert {k: v for k, v in base_map.items() if k[0] != LOOP_ID} == original_map
    scaffold_keys = {(h, bp) for h, bp, _ in base_map}
    covered = Counter()
    for strand in design.strands:
        if strand.is_scaffold:
            continue
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                if domain.overhang_id:
                    assert (domain.helix_id, bp) not in scaffold_keys
                else:
                    covered[(domain.helix_id, bp)] += 1
    assert len(covered) == 7494 and set(covered.values()) == {1}
    assert set(covered) == {(h, bp) for h, bp, _ in original_map}
    loop_map = {bp: bases[0] for (h, bp, _), bases in base_map.items() if h == LOOP_ID}
    assert ''.join(loop_map[bp] for bp in sorted(loop_map)) == scaffold[7494:]
    scaf = design.scaffolds()[0]
    transitions = {(slot(a.helix_id, a.end_bp, a.direction), slot(b.helix_id, b.start_bp, b.direction))
                   for a, b in zip(scaf.domains, scaf.domains[1:])}
    assert all(forced_edge(fl) in transitions for fl in design.forced_ligations
               if fl.id in {'p7560_loop_to_bundle', 'p7560_bundle_to_loop'})
    rows, count = topology_rows(design)
    seqs = defaultdict(str)
    for i, (sid, base, n3, n5) in enumerate(rows):
        seqs[sid] += base
        if n3 >= 0:
            assert rows[n3][3] == i and rows[n3][0] == sid
        if n5 >= 0:
            assert rows[n5][2] == i and rows[n5][0] == sid
    assert count == 214 and seqs[1] == scaffold[SEQUENCE_START:] + scaffold[:SEQUENCE_START]
    assert sum(row[2] == -1 for row in rows) == sum(row[3] == -1 for row in rows) == 214
    for i, r in enumerate(records, 2):
        expected = r['sequence'] if keep_t else ''.join(r['paired_sequences'])
        assert seqs[i] == expected, r['published_id']
    # Real load normalization must retain the authored outer-overhang metadata.
    normalized = autodetect_all_overhangs(design.model_copy(deep=True))
    assert topology_rows(normalized) == (rows, count)
    assert {o.id: o.sequence for o in normalized.overhangs} == {o.id: o.sequence for o in design.overhangs}
    assert [s.domains for s in normalized.strands] == [s.domains for s in design.strands]
    lengths = scaffold_length_checks(design)
    assert lengths[0]['actual_nt'] == 7560 and lengths[0]['complete']
    return {'passed': True, 'validator_checks': len(report.results), 'helices': 43,
            'strands': count, 'nucleotides': len(rows), 'scaffold_nt': 7560,
            'paired_bases': 7494, 'unpaired_scaffold_bases': 66,
            'staple_nt': sum(len(seqs[i]) for i in range(2, 215)),
            'matching_staples': 213, 'matches': 'full published oligos' if keep_t else 'published paired subsequences',
            'scaffold_loop_helix_label': '42', 'scaffold_loop_forced_ligations': 2,
            'total_forced_ligations': len(design.forced_ligations),
            'outer_overhangs': len(design.overhangs), 'outer_overhang_nt': 813 if keep_t else 0,
            'internal_single_T_caps': len(design.extensions), 'junction_T_nt': 906 if keep_t else 0,
            'paired_scaffold_register_unchanged': True, 'reciprocal_backbone_links': True,
            'load_normalization_preserves_topology_and_overhangs': True,
            'scaffold_sequence_start_original_index_0based': SEQUENCE_START}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--save-workspace', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    assert os.path.ismount('/media/jojo/Archive') and out.is_relative_to('/media/jojo/Archive')
    out.mkdir(parents=True, exist_ok=True)
    from backend.core.models import Design
    from backend.physics.oxdna_interface import topology_rows

    source_sha = digest(SOURCE)
    source = Design.model_validate_json(SOURCE.read_text())
    records = json.loads((EVIDENCE / 'matched_staples.json').read_text())
    scaffold = (ROOT / 'backend/core/p7560.txt').read_text().strip()
    base = add_scaffold_loop(source, scaffold)
    results = {}
    for keep_t in (True, False):
        label = 'WITH_EXTRA_T' if keep_t else 'WITHOUT_EXTRA_T'
        name = f'Gerling2018_FigS1_p7560_LOOP_OVERHANGS_{label}'
        design = base.model_copy(deep=True)
        if keep_t:
            design = add_outer_overhangs(design, records)
        else:
            design.extensions = []
            for crossover in [*design.crossovers, *design.forced_ligations]:
                crossover.extra_bases = None
        design.id = f'gerling2018-figs1-loop-overhangs-{label.lower()}'
        design.metadata.name = name
        design.metadata.modified_at = datetime.now(timezone.utc).isoformat()
        design.metadata.identity_last_known_path = ''
        design.metadata.identity_confirmed_at = ''
        design.metadata.tags = [*source.metadata.tags, 'ssDNA-scaffold-loop', label.lower()]
        design.metadata.description = (
            'Gerling2018 Fig.S1 / 42hb (1)-(3), corrected domain representation. '
            'p7560: 7494 paired bases, 66 unpaired scaffold bases on helix 42, '
            'with explicit forced ligations to helix 41 BP72 and BP71. '
            'Bookkeeping nick moved into helix 42; circular p7560 register preserved. '
            + ('All 213 full published sequences retained. Outer tails are 84 inline overhangs '
               '(81×10T and 3×1T); 342 internal single-T caps remain terminal inserts; '
               '453 crossover TT inserts retained. ' if keep_t else
               'All 2061 annotated unpaired staple T bases removed: terminal T/10T and '
               'crossover TT. Paired Ts and all 7560 scaffold bases retained. '
               '213 staples match the published paired subsequences. ')
            + 'Helix 42 is an editable schematic placement, not a relaxed loop conformation. '
            + 'Evidence: ' + str(out)
        )
        for s, r in zip(design.strands[1:], records):
            s.notes = (f'Published staple {r["published_id"]}; '
                       + ('full published sequence retained: ' + r['sequence'] if keep_t else
                          'annotated unpaired Ts removed; paired sequence: ' + ''.join(r['paired_sequences'])))
        result = validate_variant(design, source, records, scaffold, keep_t)
        path = out / (name + '.nadoc')
        path.write_text(design.model_dump_json(indent=2) + '\n')
        loaded = Design.model_validate_json(path.read_text())
        assert topology_rows(loaded) == topology_rows(design)
        result.update(design=str(path), sha256=digest(path), save_reload_topology_identical=True)
        if args.save_workspace:
            destination = ROOT / 'workspace' / path.name
            # Never replace an existing authored design on a re-run.
            with destination.open('xb') as stream:
                stream.write(path.read_bytes())
            assert digest(destination) == result['sha256']
            result['workspace_design'] = str(destination)
        results[label] = result
    assert results['WITH_EXTRA_T']['nucleotides'] - results['WITHOUT_EXTRA_T']['nucleotides'] == 2061
    assert digest(SOURCE) == source_sha
    write_json(out / 'validation.json', {'source': str(SOURCE), 'source_sha256': source_sha,
        'source_unchanged': True, 'variants': results})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
