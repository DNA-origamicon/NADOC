"""Assign the published Pointer scaffold through the real recorded operation."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from backend.api import state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.routes_assign_sequences import _ScaffoldSeqBody, assign_scaffold_sequence_endpoint
from backend.core.models import Design
from backend.core.sequences import M13MP18_SEQUENCE, domain_bp_range
from scripts.agent_structure_guard import audit, publish
from scripts.reconstruct_dietz_pointer import FIXTURE, compare_reference

PUBLISHED = FIXTURE.parent / 'dietz_pointer_2017_staples.json'


def compare_published_sequences(design):
    """Independent base-pair projection against the published uppercase cores.

    No candidate molecule is created: the source's nonhybridized staple sites
    are compared with the published thymidine passivation, not assigned here.
    """
    source = json.loads(PUBLISHED.read_text())
    raw_rows = source['sequences']
    assert all(s.startswith('ag') and s.endswith('acgttga')
               and set(s[2:-7]) <= set('ACGT') for s in raw_rows)
    expected = Counter(s[2:-7] for s in raw_rows)
    scaffolds = [s for s in design.strands if s.is_scaffold]
    assert len(scaffolds) == 1
    scaffold, = scaffolds
    assert scaffold.sequence == M13MP18_SEQUENCE
    skips = {(h.id, ls.bp_index) for h in design.helices for ls in h.loop_skips if ls.delta == -1}
    assert all(ls.delta == -1 for h in design.helices for ls in h.loop_skips)

    def sites(strand):
        return [(dom.helix_id, bp, dom.direction.value) for dom in strand.domains
                for bp in domain_bp_range(dom) if (dom.helix_id, bp) not in skips]

    scaffold_sites = sites(scaffold)
    assert len(scaffold_sites) == len(scaffold.sequence) == 7249
    bases = dict(zip(scaffold_sites, scaffold.sequence, strict=True))
    complement = str.maketrans('ATGC', 'TACG')
    actual, paired, passivation = Counter(), 0, 0
    for strand in design.strands:
        if strand.is_scaffold:
            continue
        sequence = []
        for h, bp, direction in sites(strand):
            partner = bases.get((h, bp, 'REVERSE' if direction == 'FORWARD' else 'FORWARD'))
            sequence.append(partner.translate(complement) if partner else 'T')
            paired += partner is not None
            passivation += partner is None
        actual[''.join(sequence)] += 1
    assert actual == expected, 'Published staple core sequences do not match this scaffold/routing'
    return {'publication': source['publication'], 'source_url': source['source_url'],
            'source_sha256': source['source_sha256'], 'matched_staple_cores': sum(actual.values()),
            'scaffold': 'M13mp18', 'scaffold_nt': len(scaffold.sequence), 'offset': 0,
            'scaffold_sha256': hashlib.sha256(scaffold.sequence.encode()).hexdigest(),
            'paired_staple_bases': paired, 'published_thymidine_passivation_bases': passivation,
            'scope': 'Scaffold assigned; staple sequences are independently checked against published '
                     'uppercase cores with T at unpaired sites, but are not assigned by this operation.'}


def assign_recorded(design):
    compare_reference(design, gzip.decompress(FIXTURE.read_bytes()))
    history = [row.model_dump(mode='json') for row in design.feature_log]
    scaffold, = [s for s in design.strands if s.is_scaffold]
    token = set_current_doc('__agent__dietz-pointer-sequence')
    try:
        state.load_design(design)
        response = assign_scaffold_sequence_endpoint(_ScaffoldSeqBody(
            scaffold_name='M13mp18', strand_id=scaffold.id))
        assert response['padded_nt'] == 0
        updated = state.get_or_404()
        assert [row.model_dump(mode='json') for row in updated.feature_log[:-1]] == history
        comparison = compare_published_sequences(updated)
        compare_reference(updated, gzip.decompress(FIXTURE.read_bytes()))
        if updated.loadouts:
            from backend.core.design_loadouts import save_active_snapshot
            updated = updated.copy_with(loadouts=save_active_snapshot(
                updated, updated.loadouts, updated.active_loadout_id))
        return updated, comparison
    finally:
        reset_current_doc(token)
        state.drop_doc('__agent__dietz-pointer-sequence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    raw = args.file.read_bytes()
    original = Design.model_validate_json(raw)
    updated, comparison = assign_recorded(original)
    if updated.loadouts:
        from backend.core.project_revisions import refresh_active_revision
        assert args.file.read_bytes() == raw, 'Pointer changed during sequence preparation'
        updated = refresh_active_revision(args.file.resolve().parent, updated)
    result = publish(updated, args.file, expected_existing_sha256=hashlib.sha256(raw).hexdigest())
    reopened = Design.model_validate_json(args.file.read_bytes())
    result['reopened_audit'] = audit(reopened)
    result['published_sequence_comparison'] = compare_published_sequences(reopened)
    result['previous_file_sha256'] = hashlib.sha256(raw).hexdigest()
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(comparison, indent=2))


if __name__ == '__main__':
    main()
