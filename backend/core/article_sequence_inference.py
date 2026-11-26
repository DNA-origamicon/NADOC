"""Deterministic orientation/register hypotheses over observed routing evidence.

Indices refer to an observed scaffold walk, never molecular coordinates. Missing
partners remain unknown; sequence matching does not fill missing geometry.
"""
from collections import defaultdict
import re

COMPLEMENT = str.maketrans('ACGT', 'TGCA')


def sequence_variants(raw):
    """Keep the supplied oligo and explicitly test uppercase-core annotations."""
    raw = re.sub(r'\s+', '', raw)
    if not re.fullmatch('[ACGTacgt]{12,}', raw):
        return []
    variants = [(raw.upper(), 'full oligo')]
    core = re.fullmatch(r'[acgt]*([ACGT]{12,})[acgt]*', raw)
    if core and core[1] != raw.upper():
        variants.append((core[1], 'uppercase core; lowercase flanks excluded'))
    return variants


def contiguous_anchor(indices):
    best, start = [], 0
    for i in range(len(indices) + 1):
        if i == len(indices) or indices[i] is None or (i > start and indices[i] != indices[i-1] + 1 and indices[i] != indices[i-1] - 1):
            if len(indices[start:i]) > len(best):
                best, best_start = indices[start:i], start
            start = i if i < len(indices) and indices[i] is not None else i + 1
    return (best_start, best) if best else (0, [])


def rank_directions(templates, raw_sequences, scaffold, *, max_hypotheses=8):
    """Enumerate both scaffold/staple senses and sequence-seeded registers.

    A few diverse staples nominate registers, then every route/list row validates
    each nomination. No presumed orientation wins a tie. Scores measure evidence
    agreement, not a calibrated probability of a correct molecular structure.
    """
    scaffold = scaffold.upper()
    if not scaffold or set(scaffold) - set('ACGT'):
        raise ValueError('Provide an A/C/G/T scaffold sequence.')
    n = len(scaffold)
    if any(i is not None and (not isinstance(i, int) or not 0 <= i < n) for t in templates for i in t):
        raise ValueError('Observed scaffold index is outside the sequence.')
    rows = [sequence_variants(s) for s in raw_sequences]
    rows = [v for v in rows if v]
    by_length = defaultdict(list)
    for row, variants in enumerate(rows):
        for sequence, mode in variants:
            by_length[len(sequence)].append((row, sequence, mode))
    complement = scaffold.translate(COMPLEMENT)
    doubled = complement * 2
    hypotheses = []
    for scaffold_reverse in (False, True):
        for staple_reverse in (False, True):
            oriented = [[None if i is None else n-1-i if scaffold_reverse else i
                         for i in (reversed(t) if staple_reverse else t)] for t in templates]
            offsets = {0}
            # Prefer well observed long routes; deterministic sample, no random seed.
            samples = sorted(oriented, key=lambda t: sum(i is not None for i in t), reverse=True)[:12]
            for template in samples:
                start, anchor = contiguous_anchor(template)
                if len(anchor) < 8:
                    continue
                for _, sequence, _ in by_length[len(template)]:
                    query = sequence[start:start+len(anchor)]
                    if len(set(query)) < 3:
                        continue
                    descending = anchor[-1] < anchor[0]
                    query = query[::-1] if descending else query
                    pos = doubled.find(query)
                    while 0 <= pos < n:
                        offsets.add((pos - min(anchor)) % n)
                        pos = doubled.find(query, pos + 1)
            for offset in sorted(offsets):
                matches, used_rows = [], set()
                ambiguous = 0
                for path, template in enumerate(oriented):
                    known = sum(i is not None for i in template)
                    if known < 12:
                        continue
                    predicted = ''.join('?' if i is None else complement[(i+offset) % n] for i in template)
                    compatible = [(row, mode) for row, sequence, mode in by_length[len(template)]
                                  if row not in used_rows and all(a == '?' or a == b for a, b in zip(predicted, sequence))]
                    # Different sequence variants of the same row are not separate evidence.
                    compatible = list(dict(compatible).items())
                    if len(compatible) != 1:
                        ambiguous += bool(compatible)
                        continue
                    row, mode = compatible[0]
                    used_rows.add(row)
                    matches.append({'path': path, 'staple_row': row, 'variant': mode,
                                    'paired_bases': known, 'unknown_bases': len(template)-known})
                if matches:
                    observed = sum(m['paired_bases'] for m in matches)
                    possible = sum(len(t) for t in templates)
                    hypotheses.append({'scaffold_direction': 'reversed' if scaffold_reverse else 'drawn',
                                       'staple_direction': 'reversed' if staple_reverse else 'drawn',
                                       'scaffold_offset': offset, 'matched_staples': len(matches),
                                       'total_paths': len(templates), 'list_rows': len(rows),
                                       'paired_bases_verified': observed,
                                       'unknown_bases': sum(m['unknown_bases'] for m in matches),
                                       'ambiguous_paths': ambiguous, 'matches': matches,
                                       'evidence_score': round(100 * observed / max(1, possible) * len(matches) / max(1, len(rows)), 1)})
    hypotheses.sort(key=lambda h: (-h['matched_staples'], -h['paired_bases_verified'], h['unknown_bases'],
                                  h['scaffold_direction'], h['staple_direction'], h['scaffold_offset']))
    best = hypotheses[0] if hypotheses else None
    tied = [h for h in hypotheses if best and (h['matched_staples'], h['paired_bases_verified']) ==
            (best['matched_staples'], best['paired_bases_verified'])]
    return {'hypotheses': hypotheses[:max_hypotheses], 'hypotheses_found': len(hypotheses),
            'direction_resolved': bool(best and best['matched_staples'] >= 3 and len(tied) == 1),
            'best_ties': len(tied), 'confidence_kind': 'sequence evidence score, not a calibrated probability',
            'register_search': 'Registers nominated by contiguous matches from up to 12 observed paths; all paths checked afterward.'}
