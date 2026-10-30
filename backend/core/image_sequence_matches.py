"""Read-only exact local sequence evidence; no topology or register inference."""
import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from backend.core.models import StrandType
from backend.core.sequences import _build_loop_skip_map, domain_bp_range, strand_sequence_segments


@lru_cache(maxsize=1)
def brick_reference():
    return json.loads((Path(__file__).parents[1] / 'data/gerling2018_brick.json').read_text())


@lru_cache(maxsize=3)
def sequence_reference(key):
    if key not in ('brick', '42hb13', '42hb14'):
        raise ValueError('Unknown reference list.')
    return json.loads((Path(__file__).parents[1] / f'data/gerling2018_{key}.json').read_text())


def preview_matches(design, minimum, reference_key, register):
    """Reassign only a detached copy; a register preview never edits the document."""
    from backend.core.sequences import P7560_SEQUENCE, assign_custom_scaffold_sequence, assign_staple_sequences
    snapshot = design.model_copy(deep=True)
    if register is not None:
        scaffolds = [s for s in snapshot.strands if s.is_scaffold and not s.is_reference]
        if len(scaffolds) != 1:
            raise ValueError('A p7560 register preview requires exactly one scaffold.')
        if not 0 <= register < len(P7560_SEQUENCE):
            raise ValueError('p7560 offset must be between 0 and 7559.')
        if sum(abs(d.end_bp - d.start_bp) + 1 for d in scaffolds[0].domains) > 7560:
            raise ValueError('The routed scaffold exceeds 7560 bases.')
        snapshot, _, padded = assign_custom_scaffold_sequence(snapshot, P7560_SEQUENCE[register:] + P7560_SEQUENCE[:register])
        if padded:
            raise ValueError('The routed scaffold exceeds the p7560 sequence.')
        snapshot = assign_staple_sequences(snapshot)
    result = match_design_domains(snapshot, minimum, sequence_reference(reference_key))
    result['preview'] = {'register': register, 'source_sha256': hashlib.sha256(design.model_dump_json().encode()).hexdigest(),
                         'notice': 'Current saved sequences.' if register is None else f'p7560 offset {register}: hypothetical sequence reassignment on unchanged routing; local nick corrections are not applied. Full routing and scaffold break remain unverified. Active design unchanged.'}
    return result


def _reference_index(references, minimum):
    index = defaultdict(list)
    for ref in references:
        text = ref['sequence']
        for j in range(len(text) - minimum + 1):
            index[text[j:j + minimum]].append((ref['index'], text, j))
    return index


def exact_spans(sequence, references, minimum, *, index=None):
    """Maximal exact matches in the same 5′→3′ orientation, including repeats."""
    if index is None:
        index = _reference_index(references, minimum)
    for i in range(len(sequence) - minimum + 1):
        seed = sequence[i:i + minimum]
        if any(b not in 'ACGT' for b in seed):
            continue
        for number, text, j in index.get(seed, []):
            if i and j and sequence[i - 1] == text[j - 1]:
                continue  # Already emitted from the leftmost matching position.
            length = minimum
            while i + length < len(sequence) and j + length < len(text) and sequence[i + length] in 'ACGT' and sequence[i + length] == text[j + length]:
                length += 1
            yield {'offset': i, 'length': length, 'published_index': number,
                   'published_offset': j, 'sequence': sequence[i:i + length]}


def match_design_domains(design, minimum=12, reference=None):
    reference = reference if reference is not None else brick_reference()
    index = _reference_index(reference['sequences'], minimum)
    matches, skipped, domains = [], [], 0
    ls = _build_loop_skip_map(design)
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or strand.is_reference:
            continue
        spans = strand_sequence_segments(design, strand)
        sequence = (strand.sequence or '').upper()
        if not sequence or len(sequence) != sum(s['length'] for s in spans):
            skipped.append(strand.id)
            continue
        for i, (domain, span) in enumerate(zip(strand.domains, spans)):
            if span['kind'] != 'duplex':
                continue
            domains += 1
            seq = sequence[span['start']:span['start'] + span['length']]
            positions = [bp for bp in domain_bp_range(domain)
                         for _ in range(max(0, 1 + ls.get((domain.helix_id, bp), 0)))]
            for hit in exact_spans(seq, reference['sequences'], minimum, index=index):
                start, end = hit['offset'], hit['offset'] + hit['length'] - 1
                matches.append({**hit, 'strand_id': strand.id, 'strand_name': strand.name or strand.id,
                                'domain_index': i, 'helix_id': domain.helix_id,
                                'start_bp': positions[start], 'end_bp': positions[end],
                                'domain_length': len(seq), 'full_domain': hit['length'] == len(seq)})
                if len(matches) >= 20000:
                    raise ValueError('Too many matches; increase the minimum match length.')
    return {'reference': {k: v for k, v in reference.items() if k != 'sequences'},
            'design_id': design.id, 'design_name': design.metadata.name,
            'snapshot_sha256': hashlib.sha256(design.model_dump_json().encode()).hexdigest(),
            'minimum': minimum, 'domains_checked': domains, 'skipped_strands': skipped,
            'helices': [{'id': h.id, 'label': str(h.label if h.label is not None else i)} for i, h in enumerate(design.helices)],
            'matches': matches}
