"""Reconcile on-helix staple portions against every occupied scaffold interval."""
from collections import defaultdict
from uuid import uuid5


def scaffold_intervals(design):
    ranges=defaultdict(list)
    for strand in design.strands:
        if strand.is_scaffold and not strand.is_reference:
            for d in strand.domains:ranges[d.helix_id].append(tuple(sorted((d.start_bp,d.end_bp))))
    for h in design.helices:
        if h.native_residues:
            ranges[h.id].extend((s.bp_index,s.bp_index) for s in h.native_residues)
    result={}
    for h,items in ranges.items():
        merged=[]
        for lo,hi in sorted(items):
            if merged and lo<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
            else:merged.append((lo,hi))
        result[h]=merged
    return result


def reconcile_scaffold_gaps(design):
    """Split and tag any number of internal scaffold gaps, without changing routes.

    Outer-end detection remains with the existing reconciler. Explicit/protected
    overhangs and binder domains retain their authored ownership.
    """
    from backend.core.models import StrandType, OverhangSpec, SubDomain, NADOC_SUBDOMAIN_NS
    from backend.core.lattice import _pivot_for_junction, _next_overhang_label
    cov=scaffold_intervals(design); specs={o.id:o for o in design.overhangs}
    helices={h.id:h for h in design.helices}
    protected={i for c in design.overhang_connections for i in (c.overhang_a_id,c.overhang_b_id)}
    strands=[]
    for strand in design.strands:
        if strand.strand_type!=StrandType.STAPLE or strand.is_reference:
            strands.append(strand);continue
        domains=[]
        for d in strand.domains:
            intervals=cov.get(d.helix_id,[])
            own=bool(d.overhang_id and d.overhang_id.startswith('ovhg_gap_'))
            if (d.overhang_id and (not own or d.overhang_id in protected)) or d.binds_overhang_id:
                domains.append(d);continue
            step=1 if d.direction.value=='FORWARD' else -1
            groups=[]
            for bp in range(d.start_bp,d.end_bp+step,step):
                gap=bool(intervals and not any(lo<=bp<=hi for lo,hi in intervals))
                if not groups or groups[-1][0]!=gap:groups.append((gap,[]))
                groups[-1][1].append(bp)
            old=specs.get(d.overhang_id)
            if own:specs.pop(d.overhang_id,None)
            for gap,bps in groups:
                tag=None
                if gap:
                    tag=f'ovhg_gap_{strand.id}_{d.helix_id}_{bps[0]}_{bps[-1]}'
                    adjacent=min((b for lo,hi in intervals for b in (lo,hi)),key=lambda b:min(abs(b-bps[0]),abs(b-bps[-1])))
                    size=len(bps)
                    prior=specs.get(tag) or (old if len(groups)==1 else None)
                    specs[tag]=prior.model_copy(update={'id':tag,'strand_id':strand.id}) if prior else OverhangSpec(
                        id=tag,helix_id=d.helix_id,strand_id=strand.id,label=_next_overhang_label(specs.values()),
                        pivot=_pivot_for_junction(helices,d.helix_id,adjacent),
                        sub_domains=[SubDomain(id=str(uuid5(NADOC_SUBDOMAIN_NS,f'{tag}:whole')),name='a',start_bp_offset=0,length_bp=size)])
                domains.append(d.model_copy(update={'start_bp':bps[0],'end_bp':bps[-1],'overhang_id':tag}))
        strands.append(strand.model_copy(update={'domains':domains}))
    used={d.overhang_id for s in strands for d in s.domains}
    return design.copy_with(strands=strands,overhangs=[o for o in specs.values() if not o.id.startswith('ovhg_gap_') or o.id in used or o.id in protected])
