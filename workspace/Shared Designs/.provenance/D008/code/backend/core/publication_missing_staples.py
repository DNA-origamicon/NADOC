"""Recover a drawn but unlisted oligo from independently aligned scaffold bases."""
from copy import deepcopy


def recover_unlisted_staples(classified, insertions, alignment):
    from backend.core.sequences import SCAFFOLD_LIBRARY, P7704_SEQUENCE
    result = deepcopy(classified)
    recovered = []
    if (not alignment.get('resolved') or alignment.get('length_discrepancy')
            or alignment['best']['reverse'] or insertions['unresolved']
            or len(classified['scaf']) != 1):
        return result, recovered
    library = {name: seq for name, _, seq in SCAFFOLD_LIBRARY}
    library['p7704'] = P7704_SEQUENCE
    seq = library.get(alignment.get('scaffold_name'))
    if not seq:
        return result, recovered
    offset = alignment['best']['offset']
    seq = seq[offset:] + seq[:offset]
    scaffold = [tuple(s) for s in classified['scaf'][0]['sites']]
    counts = {(h,b):n for h,b,n in insertions['counts']}
    blocks = {}; cursor = 0; directions = {}
    for site in scaffold:
        size = 1 + counts.get(site, 0)
        blocks[site] = seq[cursor:cursor+size]; cursor += size
    if cursor != len(seq):
        return result, recovered
    for a,b in zip(scaffold, scaffold[1:]):
        if a[0] == b[0] and abs(b[1]-a[1]) == 1:
            directions[a] = directions[b] = b[1]-a[1]
    occupied = {tuple(s) for p in classified['stap'] for s in p['sites']}
    remaining = []
    for path in result['unresolved']:
        sites = [tuple(s) for s in path['sites']]
        votes = [(b[1]-a[1])*directions[a] for a,b in zip(sites,sites[1:])
                 if a[0] == b[0] and abs(b[1]-a[1]) == 1 and a in directions]
        if (len(votes) < 3 or len(set(votes)) != 1 or set(sites) & occupied
                or len(set(sites)) != len(sites) or set(sites)-blocks.keys()):
            remaining.append(path); continue
        if votes[0] > 0:
            sites.reverse()
        sequence = ''.join(blocks[s][::-1] for s in sites).translate(str.maketrans('ACGT','TGCA'))
        row = {'start':list(sites[0]), 'end':list(sites[-1]), 'length':len(sequence),
               'sequence':sequence, 'sequence_source':'derived_from_aligned_scaffold',
               'basis':'Existing drawn route; unanimous antiparallel direction; scaffold complement. Not a published table entry.'}
        result['stap'].append({**path,'sites':sites,'table_row':row})
        occupied.update(sites)
        recovered.append({'path_id':path['path_id'], **row})
    result['unresolved'] = remaining
    return result, recovered
