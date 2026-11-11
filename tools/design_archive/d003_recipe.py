"""Compile Fig. S71 and Tables S2/S4 into ordinary, replayable editor actions.

No native reference is read. The pointer graph is the vector tracer's intermediate
evidence, never an import root. Row/column names provide ordering; every placement
is independently checked against the circular M13 sequence and all table bases.
"""

from collections import Counter, defaultdict
import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from experiments.recorded_review_process import ProcessRequired


def require(condition, message):
    if not condition:
        raise ProcessRequired(message)


def identity(label):
    return str(uuid5(NAMESPACE_URL, 'nadoc:all-origami:D003:' + label))


def trace_walks(graph, kind):
    helices = {h['num']: h for h in graph['vstrands']}
    occupied = {(h['num'], b) for h in helices.values()
                for b, edge in enumerate(h[kind]) if edge != [-1] * 4}
    starts = sorted(a for a in occupied if helices[a[0]][kind][a[1]][:2] == [-1, -1])
    seen, walks = set(), []
    for start in starts:
        walk, a, previous = [], start, (-1, -1)
        while a != (-1, -1):
            require(a in occupied and a not in seen, 'Broken or cyclic figure route')
            edge = helices[a[0]][kind][a[1]]
            require(tuple(edge[:2]) == previous, 'Nonreciprocal figure route')
            seen.add(a)
            walk.append(a)
            previous, a = a, tuple(edge[2:])
        walks.append(walk)
    require(seen == occupied, 'Untraced circular or disconnected figure material')
    return walks


def domains(walk):
    result = []
    for a in walk:
        if not result or result[-1][-1][0] != a[0]:
            result.append([])
        else:
            require(abs(result[-1][-1][1] - a[1]) == 1, 'Noncontiguous helical route')
        result[-1].append(a)
    return result


def sequence_mapping(graph, rows, scaffold_sequence):
    """Unique scaffold offset; exact bound domains; table gaps at drawn seams."""
    helices = {h['num']: h for h in graph['vstrands']}
    active = lambda walk: [a for a in walk if helices[a[0]]['skip'][a[1]] != -1]
    scaffolds = trace_walks(graph, 'scaf')
    require(len(scaffolds) == 1, 'D003 must have one traced scaffold')
    scaffold = scaffolds[0]
    sites = active(scaffold)
    require(len(sites) == len(scaffold_sequence) == 7249, 'D003 scaffold length mismatch')
    index = {a: i for i, a in enumerate(sites)}
    by_helix, by_row = defaultdict(list), defaultdict(list)
    for walk in trace_walks(graph, 'stap'):
        by_helix[walk[0][0]].append(walk)
    for row in rows:
        match = re.fullmatch(r'(?:Bri|Reg|Edg)-T([1-4])R(\d+)C(\d+)', row['name'])
        require(match is not None, 'Unrecognized D003 table name')
        t, r, c = map(int, match.groups())
        by_row[(t - 1) * 22 + r].append((c, row))
    require(len(rows) == 210 and len({r['name'] for r in rows}) == 210,
            'Require 166 Table S2 staples and 44 unextended Table S4 edge staples')
    pairs = []
    require(by_helix.keys() == by_row.keys(), 'Table/figure start-row mismatch')
    for h in sorted(by_helix):
        require(len(by_helix[h]) == len(by_row[h]), 'Table/figure start-count mismatch')
        pairs.extend((r, w) for (_, r), w in zip(sorted(by_row[h]),
                     sorted(by_helix[h], key=lambda w: w[0][1])))
    complement = str.maketrans('ACGT', 'TGCA')
    m13 = scaffold_sequence
    votes = Counter()
    # Enumerate exact sequence anchors, not guessed scaffold start indices.
    for row, walk in pairs:
        if not row['name'].startswith('Reg-'):
            continue
        first = active(domains(walk)[0])
        anchor = row['sequence'][:len(first)].translate(complement)[::-1]
        at = (m13 + m13).find(anchor)
        while 0 <= at < len(m13):
            votes[(at - index[first[-1]]) % len(m13)] += 1
            at = (m13 + m13).find(anchor, at + 1)
    require(votes and votes.most_common(2)[0][1] > votes.most_common(2)[1][1],
            'Scaffold sequence register is ambiguous')
    offset = votes.most_common(1)[0][0]
    base = lambda a: m13[(index[a] + offset) % len(m13)].translate(complement)
    mapped = []
    for row, walk in pairs:
        ds = domains(walk)
        # Long-range figure joins cross triangle boundaries; ordinary joins
        # stay in the same 22-row triangle. Only those joins admit table gaps.
        seams = [i for i in range(len(ds) - 1) if ds[i][-1][0] // 22 != ds[i+1][0][0] // 22]
        chunks, pending = [], ''
        for i, domain in enumerate(ds):
            pending += ''.join(base(a) for a in active(domain))
            if i in seams or i == len(ds) - 1:
                chunks.append(pending)
                pending = ''
        seq = row['sequence']
        solutions = []

        def match_chunks(i, pos, gaps):
            if not seq.startswith(chunks[i], pos):
                return
            end = pos + len(chunks[i])
            if i == len(chunks) - 1:
                if end == len(seq):
                    solutions.append(gaps)
                return
            for count in range(len(seq) - end + 1):
                match_chunks(i + 1, end + count, [*gaps, seq[end:end + count]])

        match_chunks(0, 0, [])
        require(len(solutions) == 1, f"Sequence does not uniquely match figure: {row['name']}")
        mapped.append({'name': row['name'], 'sequence': seq, 'domain_sequence': ''.join(chunks), 'walk': walk,
                       'extra_bases': dict(zip(seams, solutions[0]))})
    return scaffold, mapped, {'scaffold_offset_0based': offset,
        'scaffold_length': len(sites), 'sequence_rows_matched': len(mapped),
        'bridge_junctions': sum(len(p['extra_bases']) for p in mapped),
        'bridge_bases': sum(sum(map(len, p['extra_bases'].values())) for p in mapped),
        'non_poly_t_bridges': [{'name': p['name'], 'junction': i, 'sequence': s}
            for p in mapped for i, s in p['extra_bases'].items() if set(s) != {'T'}],
        'register_anchor_votes': votes.most_common(5),
        'sequence_mapping_validated': True}


def compile_recipe(graph, rows, scaffold_sequence, sources):
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.models import LatticeType
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.lattice import _lattice_direction, _lattice_phase_offset

    scaffold, mapped, report = sequence_mapping(graph, rows, scaffold_sequence)
    helices = sorted(graph['vstrands'], key=lambda h: h['num'])
    hid = {h['num']: identity(f"helix-{h['num']}") for h in helices}
    operations = []

    def add(kind, label, params, evidence):
        operations.append(dict(kind=kind, label=label, params=params, evidence=evidence))

    for h in helices:
        add('helix-add-at-cell', f"Figure S71: helix {h['num']}",
            dict(row=h['row'], col=h['col'], length_bp=len(h['scaf']),
                 populate_strands=False, _helix_id=hid[h['num']]), ['Fig.S71 slice'])
    # The routing grid is logical. The publication explicitly uses 3 nm axes
    # (2 nm DNA + 1 nm gap, supplement p7), not NADOC's default 2.25 nm.
    for h in helices:
        y = h['num'] * 3.0
        add('helix-update', f"Published 3 nm spacing: helix {h['num']}",
            dict(helix_id=hid[h['num']], axis_start=dict(x=0, y=y, z=0),
                 axis_end=dict(x=0, y=y, z=len(h['scaf']) * BDNA_RISE_PER_BP),
                 length_bp=len(h['scaf']), phase_offset=_lattice_phase_offset(
                     _lattice_direction(h['row'], h['col'], LatticeType.SQUARE), LatticeType.SQUARE)),
            ['Supplement p7: 1 nm gap between 2 nm helices; native helix phase unchanged'])
    for h in helices:
        for bp, delta in enumerate(h['skip']):
            if delta:
                require(delta == -1, 'Unsupported figure indel')
                add('loop-skip-insert', f"Figure deletion h{h['num']}[{bp}]",
                    dict(helix_id=hid[h['num']], bp_index=bp, delta=delta), ['Fig.S71 red cross'])
        require(not any(h['loop']), 'D003 profile expects no drawn insertion glyphs')
    offset = report['scaffold_offset_0based']
    strands = [dict(name='M13mp18', walk=scaffold, extra_bases={},
                    sequence=scaffold_sequence[offset:] + scaffold_sequence[:offset]), *mapped]
    counts = Counter()
    for strand in strands:
        ds = domains(strand['walk'])
        sid = [identity(f"{strand['name']}-domain-{i}") for i in range(len(ds))]
        stype = 'scaffold' if strand['name'] == 'M13mp18' else 'staple'
        direction = lambda d: 'FORWARD' if d[-1][1] > d[0][1] else 'REVERSE'
        for i, d in enumerate(ds):
            require(len(d) > 1, 'One-base domain needs explicit polarity evidence')
            add('strand-add', f"Draw {strand['name']} domain {i+1}",
                dict(_strand_id=sid[i], strand_type=stype, domains=[dict(
                    helix_id=hid[d[0][0]], start_bp=d[0][1], end_bp=d[-1][1], direction=direction(d))]),
                ['Fig.S71 directed rail'])
        for i, (a, b) in enumerate(zip(ds, ds[1:])):
            ah, ab = a[-1]
            bh, bb = b[0]
            canonical = ab == bb and any(
                crossover_neighbor(LatticeType.SQUARE, x, 0, ab, is_scaffold=sc) == (y, 0)
                for x, y in ((ah, bh), (bh, ah)) for sc in (False, True))
            jid = identity(f"{strand['name']}-join-{i}")
            if canonical:
                # Native nick position is the 3-prime base before a cut.
                da, db = direction(a), direction(b)
                sign_b = 1 if db == 'FORWARD' else -1
                add('crossover-place', f"Connect {strand['name']} domains {i+1}/{i+2}",
                    dict(crossover_id=jid, half_a=dict(helix_id=hid[ah], index=ab, strand=da),
                         half_b=dict(helix_id=hid[bh], index=bb, strand=db),
                         nick_bp_a=ab, nick_bp_b=bb-sign_b), ['Fig.S71 crossover curve'])
            else:
                add('forced-ligation-create', f"Join {strand['name']} domains {i+1}/{i+2}",
                    dict(_fl_id=jid, three_prime_strand_id=sid[0], five_prime_strand_id=sid[i+1]),
                    ['Fig.S71 noncanonical connection'])
            counts['crossovers' if canonical else 'forced_ligations'] += 1
            extra = strand['extra_bases'].get(i, '')
            if extra:
                add('crossover-extra-bases' if canonical else 'forced-ligation-extra-bases',
                    f"{strand['name']}: {len(extra)} bridge bases",
                    {('crossover_id' if canonical else 'fl_id'): jid, 'sequence': extra},
                    ['Table S2 exact sequence gap between bound domains'])
        add('strand-sequence', f"Assign {strand['name']} sequence", dict(
            strand_id=sid[0], name=strand['name'], sequence=strand.get('domain_sequence', strand['sequence'])),
            ['Methods M13mp18; sequence register verified against all staples' if stype == 'scaffold'
             else 'Table S4' if strand['name'].startswith('Edg') else 'Table S2'])
    report.update(counts)
    report['published_helix_spacing_nm'] = 3.0
    report['operation_count'] = len(operations)
    report['staple_nucleotides'] = sum(len(s['sequence']) for s in mapped)
    recipe = {'version': 1, 'design_id': 'D003',
        'name': 'D003 — square tile, strong–strong bridges', 'lattice': 'SQUARE',
        'unresolved': [], 'sources': sources, 'operations': operations,
        'folded_geometry': {'required': True,
            'evidence': 'Supplement pp6–10: four planar triangular panels; Fig.S71 is an unfolded routing diagram.'},
        'recovery': report,
        'profile_selections': ['Fig.S71, Table S2, unextended stacking edges from Table S4.',
            'Supplement p7 specifies 3 nm helix spacing; preserve the native B-DNA phase and rise constants.',
            'Printed row names T1–T4 map to consecutive groups of 22 helices; C sorts start positions.',
            'Upper/lower rail polarity and square register are independently checked with sequences.',
            'M13 represented with the figure nick; its circular closure is a biological convention.',
            'Short scaffold loops retain their drawn unpaired helical sites; no invented atomic loop geometry.']}
    report['recipe_operations_sha256'] = hashlib.sha256(repr(operations).encode()).hexdigest()
    return recipe, report
