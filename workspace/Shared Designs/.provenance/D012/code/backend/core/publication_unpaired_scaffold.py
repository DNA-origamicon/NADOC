"""Locate scaffold loop candidates without inventing routes or spatial placement.

The supplied staple list is the scope of the negative sequence evidence. Matches
already accounted for by an exact, endpoint-supported staple route are reported
as repeats, not used to move that staple to an unpaired region.
"""
import hashlib
import re


def terminal_scaffold_sites(classified, lattice, unpaired):
    """Keep drawn scaffold outside each helix's staple band as native domains.

    This admits terminal scaffold labels without filling them with inferred
    staples. Interior gaps and path-only tracks retain their separate guards.
    Sequence-supported routing and a resolved lattice remain prerequisites.
    """
    from collections import defaultdict
    paired = defaultdict(set)
    for path in classified['stap']:
        for h, bp in path['sites']:
            paired[h].add(bp)
    missing = set(lattice.get('missing_helices', []))
    return {(h, bp) for run in unpaired['runs'] if run['supported'] and run['placement_resolved']
            for h, bp in run['sites'] if h not in missing and paired[h]
            and (bp < min(paired[h]) or bp > max(paired[h]))}


def _dna(value):
    return re.sub(r'\s+', '', value).upper()


def _row_key(row):
    return (tuple(row['start']), tuple(row['end']), _dna(row['sequence']))


def _longest_match(sequence, targets):
    """Longest contiguous reverse-complement match, with deterministic witness."""
    reverse_complement = sequence.translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    best = {'length': 0, 'table_row': None, 'staple_offset': None, 'sequence': ''}
    def hit(size):
        windows = {}
        for row, target in targets:
            for offset in range(len(target) - size + 1):
                windows.setdefault(target[offset:offset + size], (row, offset))
        for start in range(len(reverse_complement) - size + 1):
            fragment = reverse_complement[start:start + size]
            if fragment in windows:
                row, offset = windows[fragment]
                return {'length': size, 'table_row': row, 'staple_offset': offset,
                        'sequence': fragment}
        return None
    lo, hi = 1, min(len(sequence), max((len(t) for _, t in targets), default=0))
    while lo <= hi:
        size = (lo + hi) // 2
        found = hit(size)
        if found:
            best = found; lo = size + 1
        else:
            hi = size - 1
    return best


def locate_unpaired_scaffold(classified, insertions, table, alignment, sequence, lattice,
                             *, minimum_match=7):
    """Locate routed, unpaired runs; test competing unassigned staple evidence.

    Seven bases is an explicit search threshold, not a thermodynamic assertion.
    Shorter runs are tested in full. Fully explained staple repeats do not veto
    a loop. Missing/unclassified routing prevents automatic acceptance, even if
    there is no sequence hit. No physical coordinates or new bases are inferred.
    """
    if type(minimum_match) is not int or minimum_match < 1:
        raise ValueError('minimum_match must be a positive integer')
    sequence = _dna(sequence)
    if (not alignment.get('alignment_resolved', alignment.get('resolved', False))
            or alignment.get('length_discrepancy')
            or alignment.get('best', {}).get('reverse') or insertions['unresolved']
            or len(classified['scaf']) != 1):
        return {'resolved': False, 'reason': 'A complete directed sequence alignment is required.',
                'runs': [], 'auxiliary_tracks': []}
    if (set(sequence) - set('ACGT') or not sequence
            or hashlib.sha256(sequence.encode()).hexdigest() != alignment['scaffold_sha256']):
        raise ValueError('Loop search sequence differs from the aligned scaffold')
    sites = [tuple(s) for s in classified['scaf'][0]['sites']]
    paired = {tuple(s) for p in classified['stap'] for s in p['sites']}
    counts = {(h, b): n for h, b, n in insertions['counts']}
    if sum(1 + counts.get(s, 0) for s in sites) != len(sequence):
        raise ValueError('Loop search scaffold length differs from alignment')
    offset = alignment['best']['offset']
    sequence = sequence[offset:] + sequence[:offset]
    blocks = []; cursor = 0
    for site in sites:
        size = 1 + counts.get(site, 0)
        blocks.append(sequence[cursor:cursor + size]); cursor += size
    matched = {_row_key(p['table_row']) for p in classified['stap']}
    all_targets = [(i, _dna(row['sequence'])) for i, row in enumerate(table['rows'])]
    unexplained = [(i, seq) for i, seq in all_targets if _row_key(table['rows'][i]) not in matched]
    missing = set(lattice.get('missing_helices', []))
    auxiliary = []
    # A path-only row is an auxiliary excursion only when its route leaves and
    # returns to adjacent sites on the same inset helix. Retain both anchors.
    i = 0
    while i < len(sites):
        start = i; helix = sites[i][0]
        while i + 1 < len(sites) and sites[i + 1][0] == helix:
            i += 1
        end = i
        if helix in missing:
            before = sites[start - 1] if start else None
            after = sites[end + 1] if end + 1 < len(sites) else None
            excursion = (before is not None and after is not None
                         and before[0] == after[0] and before[0] not in missing
                         and abs(before[1] - after[1]) == 1)
            auxiliary.append({'helix': helix, 'start': sites[start], 'end': sites[end],
                              'attachment_before': before, 'attachment_after': after,
                              'paired_bases': sum(len(blocks[j]) for j in range(start, end + 1)
                                                  if sites[j] in paired),
                              'unpaired_bases': sum(len(blocks[j]) for j in range(start, end + 1)
                                                    if sites[j] not in paired),
                              'supported_excursion': excursion,
                              'placement_resolved': False})
        i += 1
    runs = []; i = 0
    while i < len(sites):
        if sites[i] in paired:
            i += 1; continue
        start = i
        while i + 1 < len(sites) and sites[i + 1] not in paired:
            i += 1
        end = i; raw = ''.join(blocks[start:end + 1])
        hit = _longest_match(raw, unexplained)
        threshold = min(minimum_match, len(raw))
        supported = not classified['unresolved'] and hit['length'] < threshold
        runs.append({'sites': sites[start:end + 1], 'sequence': raw, 'length': len(raw),
                     'attachment_before': sites[start - 1] if start else None,
                     'attachment_after': sites[end + 1] if end + 1 < len(sites) else None,
                     'path_only_helices': sorted({h for h, _ in sites[start:end + 1]} & missing),
                     'longest_match_any_staple': _longest_match(raw, all_targets),
                     'longest_match_unassigned_staple': hit, 'match_threshold': threshold,
                     'supported': supported,
                     'classification': 'supported_unpaired_scaffold' if supported else 'unresolved',
                     'basis': 'Drawn scaffold route; no unexplained staple reverse-complement match',
                     'placement_resolved': not bool({h for h, _ in sites[start:end + 1]} & missing)})
        i += 1
    return {'resolved': all(r['supported'] for r in runs), 'runs': runs,
            'unpaired_bases': sum(r['length'] for r in runs), 'auxiliary_tracks': auxiliary,
            'insertion_sites': sorted(counts),
            'minimum_match': minimum_match, 'unassigned_table_rows': [i for i, _ in unexplained],
            'assumption': 'Unpaired routed scaffold is a deliberate loop when the supplied staples do not explain pairing.',
            'limitation': 'Conditional on the supplied staple list; no 3D pose or missing oligos inferred.'}


def aligned_unpaired_scaffold(classified, insertions, table, alignment, lattice, custom_sequence=None):
    from backend.core.sequences import PUBLICATION_SCAFFOLDS
    sequence = custom_sequence or PUBLICATION_SCAFFOLDS.get(alignment.get('scaffold_name'), '')
    return locate_unpaired_scaffold(classified, insertions, table, alignment, sequence, lattice)
