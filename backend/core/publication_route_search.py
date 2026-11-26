"""Bounded source-only staple route search; exhausted budgets never prove uniqueness."""
from collections import defaultdict


def search_missing_routes(classified, insertions, alignment, table, lattice, *, max_states=200000):
    from backend.core.sequences import SCAFFOLD_LIBRARY, P7704_SEQUENCE
    from backend.core.models import LatticeType
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.lattice import _lattice_direction
    result = {'rows': [], 'method': 'Directed native crossover graph; exact paired sequence, table endpoints and length; occupied staple sites excluded',
              'native_reference_consulted': False, 'max_states_per_row': max_states}
    if (len(classified['scaf']) != 1 or not alignment.get('sequence_supported')
            or alignment['best']['reverse'] or insertions['unresolved'] or not lattice.get('resolved')):
        return {**result, 'status': 'insufficient_alignment_or_lattice'}
    library = {n:s for n,_,s in SCAFFOLD_LIBRARY}; library['p7704'] = P7704_SEQUENCE
    seq = library[alignment['scaffold_name']]; off = alignment['best']['offset']
    seq = seq[off:] + seq[:off]
    counts = {(h,b):n for h,b,n in insertions['counts']}
    blocks = {}; directions = {}; cursor = 0
    scaffold = [tuple(s) for s in classified['scaf'][0]['sites']]
    for site in scaffold:
        n = 1 + counts.get(site, 0)
        blocks[site] = seq[cursor:cursor+n][::-1].translate(str.maketrans('ACGT','TGCA')); cursor += n
    for a,b in zip(scaffold,scaffold[1:]):
        if a[0]==b[0] and abs(a[1]-b[1])==1: directions[a[0]] = a[1]-b[1]
    cells = {int(h):tuple(c) for h,c in lattice['cells'].items()}
    shifts = [shift for shift in (0,1) if all(_lattice_direction(r+shift,c,LatticeType.HONEYCOMB).value == ('REVERSE' if directions[h]==1 else 'FORWARD') for h,(r,c) in cells.items())]
    if len(shifts)!=1: return {**result,'status':'ambiguous_lattice_polarity'}
    cells = {h:(r+shifts[0],c) for h,(r,c) in cells.items()}; inverse={c:h for h,c in cells.items()}
    occupied = {tuple(s) for p in classified['stap'] for s in p['sites']}
    key = lambda row:(tuple(row['start']),tuple(row['end']),row['sequence'])
    matched = {key(p['table_row']) for p in classified['stap']}
    for index,row in enumerate(table['rows']):
        if key(row) in matched: continue
        start,end = tuple(row['start']),tuple(row['end']); target=row['sequence']; length=len(target)
        record={'table_row':index,'start':start,'end':end,'length':length,'sequence':target,'candidates':[],'states':0,'search_complete':True}
        if row['length']!=length or set(target)-set('ACGT'):
            record.update(status='invalid_sequence',search_complete=False); result['rows'].append(record); continue
        # Every move consumes a base. A length-wide register window around both
        # endpoints is therefore a complete bound for this graph's +/-1/0 moves.
        lo=min(start[1],end[1])-length; hi=max(start[1],end[1])+length
        stack=[(start,0,(),0)]
        while stack:
            site,pos,path,paired=stack.pop(); record['states']+=1
            if record['states']>max_states:
                record['search_complete']=False; break
            if site in occupied or site in path or site[0] not in cells or not lo<=site[1]<=hi: continue
            block=blocks.get(site); n=1+counts.get(site,0)
            if pos+n>length or (block is not None and target[pos:pos+n]!=block): continue
            route=path+(site,); pos+=n; paired+=n if block is not None else 0
            if pos==length:
                if site==end: record['candidates'].append({'sites':list(route),'paired_bases':paired,'unpaired_bases':length-paired})
                if len(record['candidates'])>=2:
                    record['search_complete']=False
                    break  # two witnesses suffice to disprove uniqueness
                continue
            if site==end: continue
            h,b=site
            neighbors={(h,b+directions[h])}
            # Both native half-site classes are admitted, matching the compiler.
            for scaf in (False,True):
                other=inverse.get(crossover_neighbor(LatticeType.HONEYCOMB,*cells[h],b,is_scaffold=scaf))
                if other is not None and directions[other]!=directions[h]: neighbors.add((other,b))
            for nxt in sorted(neighbors,reverse=True): stack.append((nxt,pos,route,paired))
        record['status']=('ambiguous' if len(record['candidates'])>1 else 'budget_exhausted' if not record['search_complete'] else 'unique' if record['candidates'] else 'no_match')
        result['rows'].append(record)
    # Individually unique routes must also be mutually compatible.
    claims=defaultdict(list)
    for r in result['rows']:
        if r['status']=='unique':
            for s in r['candidates'][0]['sites']: claims[s].append(r)
    for rows in claims.values():
        if len(rows)>1:
            for r in rows:r['status']='conflicts_with_other_row'
    result['status']='complete'
    result['limitation']='Uniqueness is conditional on native lattice crossovers and exact paired sequence; nonlocal/forced joins are not guessed.'
    return result
