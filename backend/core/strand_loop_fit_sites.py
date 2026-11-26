"""Conservative native stamping scope for plain, rigid duplex environments.

All complex placement paths use the full builder. Plain residues have a measured
O5'-centred template bound; bridge endpoints and reciprocal partners are retained
as dependencies, including long bonds whose endpoints lie outside the loop box.
"""
from functools import lru_cache
import numpy as np
from backend.core.ring_piercing import SEARCH_NM


@lru_cache(maxsize=1)
def template_radius():
    from backend.core.strand_loop_atoms import loop_template
    return max(float(np.linalg.norm(np.array([a[2:] for a in defs])-origin,axis=1).max())
        for residue in ('DA','DC','DG','DT') for direction in ('FORWARD','REVERSE')
        for defs,origin,_ in [loop_template(residue,direction)])


def fit_sites(design, records):
    if (design.atomistic_reference or design.deformations or design.nucleotide_transforms
            or design.extensions or design.duplexes or design.overhang_connections
            or design.flexible_connections or design.flexible_segment_marks
            or design.photoproduct_junctions or design.nanoparticles
            or design.protein_attachments or any(h.loop_skips for h in design.helices)
            or any(x.extra_bases for x in [*design.crossovers,*design.forced_ligations])
            or {h.id for h in design.helices} - {r['helix_id'] for r in records}):
        return None
    loops=[r for r in records if r.get('loop_order',0)>0]
    if not loops:
        return None
    radius=template_radius()
    beads=np.array([r['backbone_position'] for r in loops])
    # One radius for rotating loop atoms, one for a fixed template, and an
    # additional radius for phosphate branch offsets/bows off a bridge chord.
    lo=beads.min(axis=0)-(3*radius+SEARCH_NM+1e-10)
    hi=beads.max(axis=0)+(3*radius+SEARCH_NM+1e-10)
    ordinary=[r for r in records if not r.get('loop_order',0)]
    keys=[(r['helix_id'],r['bp_index'],r['direction']) for r in ordinary]
    lookup={key:i for i,key in enumerate(keys)}
    xyz=np.array([r['backbone_position'] for r in ordinary])
    keep=((xyz>=lo)&(xyz<=hi)).all(axis=1)
    from backend.core.strand_loops import strand_entries
    edges=[]
    for strand in design.strands:
        walk=[entry[:3] for entry in strand_entries(design,strand) if entry[3]==0]
        edges.extend((lookup[a],lookup[b]) for a,b in zip(walk,walk[1:])
                     if a in lookup and b in lookup)
        for loop in strand.loops:
            at=(loop.helix_id,loop.bp_index,loop.direction)
            if at in lookup:
                keep[lookup[at]]=True
    for ligation in design.forced_ligations:
        a=(ligation.three_prime_helix_id,ligation.three_prime_bp,ligation.three_prime_direction.value)
        b=(ligation.five_prime_helix_id,ligation.five_prime_bp,ligation.five_prime_direction.value)
        if a in lookup and b in lookup:
            edges.append((lookup[a],lookup[b]))
    edges=np.asarray(edges,dtype=int).reshape(-1,2)
    if len(edges):
        ends=xyz[edges]
        overlap=((ends.max(axis=1)>=lo)&(ends.min(axis=1)<=hi)).all(axis=1)
        keep[edges[overlap].ravel()]=True
    # Interpolation bows use both reciprocal connectors. Expand selected
    # connector dependencies to a fixed point, not an arbitrary radius.
    from backend.core.junction_topology import crossover_connectors, reciprocal_pairs
    connectors=crossover_connectors(design)
    groups=[]
    for a,b in reciprocal_pairs(connectors):
        sites=[(c.from_helix,c.from_bp,c.from_dir) for c in (connectors[a],connectors[b])]
        sites += [(c.to_helix,c.to_bp,c.to_dir) for c in (connectors[a],connectors[b])]
        groups.append([lookup[k] for k in sites if k in lookup])
    overhangs=[]
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id:
                low,high=sorted((domain.start_bp,domain.end_bp))
                overhangs.append([lookup[k] for bp in range(low,high+1)
                    if (k:=(domain.helix_id,bp,domain.direction.value)) in lookup])
    # Keep adjacent residues for phosphate interpolation and bond exclusions.
    for _ in range(2):
        if len(edges):
            keep[edges[keep[edges].any(axis=1)].ravel()]=True
    for strand in design.strands:
        for a,b in zip(strand.domains,strand.domains[1:]):
            sites=[(a.helix_id,a.end_bp,a.direction.value),(b.helix_id,b.start_bp,b.direction.value)]
            groups.append([lookup[k] for k in sites if k in lookup])
    while True:
        count=int(keep.sum())
        for group in [*groups,*overhangs]:
            if group and keep[group].any():
                keep[group]=True
        if int(keep.sum())==count:
            break
    return {key for key,selected in zip(keys,keep) if selected}
