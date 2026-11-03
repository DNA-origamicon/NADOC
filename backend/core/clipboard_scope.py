"""Resolve clipboard ownership to a union of authored domains, without growing strands."""
import uuid

from backend.core.base_keys import parse_base_key
from backend.core.design_geometry import fitting_geometry


def domain_scope(source, refs):
    strands = {s.id: s for s in source.strands}
    selected = set()
    proteins, particles = set(), set()

    def domain(sid, index):
        if sid not in strands or not isinstance(index, int) or not 0 <= index < len(strands[sid].domains):
            raise ValueError('Selected domain no longer exists')
        selected.add((sid, index))

    def strand(sid):
        if sid not in strands:
            raise ValueError('Selected strand no longer exists')
        for i in range(len(strands[sid].domains)):
            domain(sid, i)

    def slot(hid, bp, direction, sid=None):
        found = [(s.id, i) for s in source.strands if sid is None or s.id == sid
                 for i, d in enumerate(s.domains) if d.helix_id == hid and d.direction == direction
                 and min(d.start_bp, d.end_bp) <= bp <= max(d.start_bp, d.end_bp)]
        if not found:
            raise ValueError('Selected nucleotide has no owning domain')
        for s, i in found:
            domain(s, i)

    def overhang(oid):
        found = [(s.id, i) for s in source.strands for i, d in enumerate(s.domains) if d.overhang_id == oid]
        if not found:
            raise ValueError('Selected overhang no longer exists')
        for s, i in found:
            domain(s, i)

    def extension(eid):
        e = next((e for e in source.extensions if e.id == eid), None)
        if e is None or e.strand_id not in strands:
            raise ValueError('Selected extension no longer exists')
        domain(e.strand_id, 0 if e.end == 'five_prime' else len(strands[e.strand_id].domains)-1)

    def crossover(xid, subtype='crossover'):
        collection = source.forced_ligations if subtype == 'forced_ligation' else source.crossovers
        x = next((x for x in collection if x.id == xid), None)
        if x is None:
            raise ValueError('Selected crossover no longer exists')
        if subtype == 'forced_ligation':
            slot(x.three_prime_helix_id, x.three_prime_bp, x.three_prime_direction)
            slot(x.five_prime_helix_id, x.five_prime_bp, x.five_prime_direction)
        else:
            for h in (x.half_a, x.half_b):
                slot(h.helix_id, h.index, h.strand)

    def base(key, sid=None):
        p = parse_base_key(key)
        if p is None:
            raise ValueError('Invalid selected base')
        if p.family == 'xover':
            crossover(p.crossover_id)
        elif p.family == 'extension':
            extension(p.helix_id[len('__ext_'):])
        elif p.family == 'sslink' and any(d.helix_id == p.helix_id for s in source.strands for d in s.domains):
            slot(p.helix_id, p.bp_index, p.direction.upper(), sid)
        elif p.family == 'sslink':
            c = next((c for c in source.overhang_connections if c.id == p.helix_id[len('__lnk__'):]), None)
            if c is None:
                raise ValueError('Selected linker no longer exists')
            overhang(c.overhang_a_id)
            overhang(c.overhang_b_id)
        else:
            slot(p.helix_id, p.bp_index, p.direction.upper(), sid)

    for ref in refs:
        kind = ref.get('kind')
        if kind == 'strand':
            strand(ref['id'])
        elif kind == 'domain':
            domain(ref['strandId'], ref['domainIndex'])
        elif kind in ('base', 'end'):
            base(ref['key'])
        elif kind == 'bond':
            base(ref['fromKey'], ref.get('strandId'))
            base(ref['toKey'], ref.get('strandId'))
        elif kind == 'crossover':
            crossover(ref['id'], ref.get('subtype', 'crossover'))
        elif kind == 'extension':
            extension(ref['id'])
        elif kind == 'overhang':
            overhang(ref['id'])
        elif kind == 'cluster':
            c = next((c for c in source.cluster_transforms if c.id == ref['id']), None)
            if c is None:
                raise ValueError('Selected cluster no longer exists')
            if c.domain_ids:
                for d in c.domain_ids:
                    domain(d.strand_id, d.domain_index)
            else:
                for s in source.strands:
                    for i, d in enumerate(s.domains):
                        if d.helix_id in c.helix_ids:
                            domain(s.id, i)
        elif kind == 'protein':
            a = next((a for a in source.protein_attachments if a.id == ref['id']), None)
            if a is None:
                raise ValueError('Selected protein no longer exists')
            proteins.add(a.id)
            if a.binder_strand_id:
                strand(a.binder_strand_id)
        elif kind == 'nanoparticle':
            p = next((p for p in source.nanoparticles if p.id == ref['id']), None)
            if p is None:
                raise ValueError('Selected nanoparticle no longer exists')
            particles.add(p.id)
            for r in p.biotin_dna:
                strand(r.strand_id)
            for c in source.nanoparticle_conjugations:
                if c.nanoparticle_id == p.id:
                    for r in c.surface_strands:
                        strand(r.strand_id)
        else:
            raise ValueError('Unknown clipboard selection type')
    if not selected and not proteins and not particles:
        raise ValueError('Nothing selected to copy')
    return selected, proteins, particles


def scoped_source(source, selected):
    """Keep maximal consecutive domain runs; never join across an unselected gap."""
    mapping, fragments = {}, []
    for s in source.strands:
        runs = []
        for i in range(len(s.domains)):
            if (s.id, i) not in selected:
                continue
            if not runs or runs[-1][-1] != i-1:
                runs.append([])
            runs[-1].append(i)
        for j, run in enumerate(runs):
            sid = s.id if j == 0 else str(uuid.uuid4())
            for index, old in enumerate(run):
                mapping[s.id, old] = sid, index
            fragments.append(s.model_copy(deep=True, update={
                'id': sid, 'domains': [s.domains[i].model_copy(deep=True) for i in run],
                'sequence': s.sequence if len(run) == len(s.domains) else None,
                'routing_seed': None, 'custom_scaffold_length': None,
            }))
    overhangs = []
    for o in source.overhangs:
        owner = next((mapping[s.id, i][0] for s in source.strands for i, d in enumerate(s.domains)
                      if d.overhang_id == o.id and (s.id, i) in mapping), None)
        if owner:
            overhangs.append(o.model_copy(deep=True, update={'strand_id': owner}))
    extensions = []
    for e in source.extensions:
        s = next((s for s in source.strands if s.id == e.strand_id), None)
        key = (e.strand_id, 0 if e.end == 'five_prime' else len(s.domains)-1) if s else None
        if key in mapping:
            extensions.append(e.model_copy(deep=True, update={'strand_id': mapping[key][0]}))
    geometry = []
    for n in fitting_geometry(source):
        key = (n.get('strand_id'), n.get('domain_index', 0))
        # Extension geometry belongs to its terminal domain, not a synthetic domain index.
        if str(n.get('helix_id', '')).startswith('__ext_'):
            e = next((e for e in source.extensions if '__ext_'+e.id == n['helix_id']), None)
            s = next((s for s in source.strands if e and s.id == e.strand_id), None)
            if s:
                key = (s.id, 0 if e.end == 'five_prime' else len(s.domains)-1)
        if key in mapping:
            sid, index = mapping[key]
            geometry.append({**n, 'strand_id': sid, 'domain_index': index})
    return source.model_copy(deep=True, update={'strands': fragments, 'overhangs': overhangs,
                                                'extensions': extensions}), geometry
