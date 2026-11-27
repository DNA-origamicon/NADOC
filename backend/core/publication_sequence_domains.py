"""Bounded split alignment of oligos to a circular scaffold reverse complement.

Candidates are sequence-domain hypotheses, not routes. No image positions,
reference design, native model or presumed overhang lengths are inputs.
"""
from collections import defaultdict


def scaffold_seed_index(scaffold, minimum_domain):
    scaffold=scaffold.upper()
    if not scaffold or set(scaffold)-set('ACGT'):raise ValueError('Scaffold must contain A/C/G/T.')
    if type(minimum_domain) is not int or not 2<=minimum_domain<=len(scaffold):raise ValueError('Invalid minimum domain length.')
    reference=scaffold.translate(str.maketrans('ACGT','TGCA'))[::-1]
    circle=reference+reference[:minimum_domain-1]
    index=defaultdict(list)
    for offset in range(len(reference)):index[circle[offset:offset+minimum_domain]].append(offset)
    return reference,index


def align_domains(sequence, reference, index, *, minimum_domain=8, max_domains=6, beam_width=12, max_transitions=200000, required_pairs=None):
    """Beam dynamic programming; report pruning and never certify native uniqueness.

    Score lexicographically by paired bases, then fewer contiguous domains.
    Every chunk length is tested, not only maximal exact matches. Unmatched
    bases remain unassigned; they are not automatically called overhangs.
    """
    sequence=sequence.upper();length=len(sequence);n=len(reference)
    required_pairs=dict(required_pairs or {})
    if any(type(p) is not int or not 0<=p<length or type(site) is not int or not 0<=site<n
           or sequence[p]!=reference[n-1-site] for p,site in required_pairs.items()):
        raise ValueError('Invalid anchor mapping.')
    if not sequence or set(sequence)-set('ACGT'):raise ValueError('Oligo must contain A/C/G/T.')
    if type(max_transitions) is not int or not 1<=max_transitions<=1000000:raise ValueError('Invalid transition budget.')
    if not 1<=length<=300 or not 1<=max_domains<=12 or not 1<=beam_width<=64:raise ValueError('Sequence search bounds exceeded.')
    # Each state contains ordered (oligo start, rc-scaffold start, length) blocks.
    states=[defaultdict(list) for _ in range(length+1)];states[0][0]=[(0,())]
    pruned=0;expanded=0;transitions=0;exhausted=False
    def retain(pos,count,score,blocks):
        nonlocal pruned,transitions,exhausted
        transitions+=1
        if transitions>max_transitions:
            exhausted=True;return
        bucket=states[pos][count]
        state=(score,blocks)
        if state in bucket:return
        bucket.append(state);bucket.sort(key=lambda s:(-s[0],s[1]))
        if len(bucket)>beam_width:
            bucket.pop();pruned+=1
    for pos in range(length):
        if exhausted:break
        matches=[]
        if pos+minimum_domain<=length:
            for offset in index.get(sequence[pos:pos+minimum_domain],[]):
                size=minimum_domain
                while size<min(length-pos,n) and sequence[pos+size]==reference[(offset+size)%n]:size+=1
                matches.append((offset,size))
        for count,bucket in list(states[pos].items()):
            for score,blocks in bucket:
                if exhausted:break
                expanded+=1
                if pos not in required_pairs:retain(pos+1,count,score,blocks)
                if count>=max_domains:continue
                used={(start+i)%n for _,start,size in blocks for i in range(size)}
                for offset,maximum in matches:
                    if exhausted:break
                    for size in range(minimum_domain,maximum+1):
                        if exhausted:break
                        if any((offset+i)%n in used for i in range(size)):break
                        if any(p in required_pairs and required_pairs[p]!=(n-1-offset-(p-pos))%n
                               for p in range(pos,pos+size)):continue
                        # Adjacent collinear domains are a single chunk, already
                        # enumerated from its original start; do not create aliases.
                        if blocks and blocks[-1][0]+blocks[-1][2]==pos and (blocks[-1][1]+blocks[-1][2])%n==offset:continue
                        retain(pos+size,count+1,score+size,blocks+((pos,offset,size),))
    candidates=[]
    pools=defaultdict(list)
    for pool in (states if exhausted else [states[-1]]):
        for count,bucket in pool.items():pools[count].extend(bucket)
    for count,bucket in pools.items():
        bucket=list(set(bucket))
        for paired,blocks in bucket:
            covered={p+i for p,_,size in blocks for i in range(size)}
            if not required_pairs.keys()<=covered:continue
            candidates.append({'paired_bases':paired,'domain_count':count,
                'domains':[{'oligo_start':p,'length':size,'scaffold_start':(n-1-offset)%n,'scaffold_step':-1} for p,offset,size in blocks],
                'unassigned_offsets':[i for i in range(length) if i not in covered]})
    candidates.sort(key=lambda c:(-c['paired_bases'],c['domain_count']))
    best=candidates[0] if candidates else {'paired_bases':0,'domain_count':0};best_score=(best['paired_bases'],best['domain_count'])
    ties=sum((c['paired_bases'],c['domain_count'])==best_score for c in candidates)
    return {'candidates':candidates[:beam_width], 'best_ties_retained':ties,
            'required_pairs':[{'oligo_offset':p,'scaffold_offset':site} for p,site in sorted(required_pairs.items())],
            'states_expanded':expanded,'states_pruned':pruned,'transitions':transitions,
            'budget_exhausted':exhausted,'max_transitions':max_transitions,
            'search_complete_within_bounds':not exhausted and pruned==0 and len(candidates)<=beam_width,
            'status':'budget_exhausted' if exhausted else 'sequence_domain_hypotheses','minimum_domain':minimum_domain,'max_domains':max_domains,
            'beam_width':beam_width,
            'limitation':'Pruned or truncated searches cannot prove uniqueness. Chunk boundaries, scaffold identity, helix placement and unassigned-base function remain unverified.'}


def align_table(rows, scaffold, *, minimum_domain=8, max_domains=6, beam_width=12, max_transitions=200000):
    reference,index=scaffold_seed_index(scaffold,minimum_domain)
    return {'method':'bounded-circular-split-alignment-v1','rows':[
        {'row_id':r['id'],**align_domains(r['sequence'],reference,index,minimum_domain=minimum_domain,max_domains=max_domains,beam_width=beam_width,max_transitions=max_transitions)}
        for r in rows], 'native_routing_resolved':False}


def select_compatible_domains(search, scaffold_length, *, time_limit=10):
    """MILP chooses non-overlapping hypotheses and tests a second optimum.

    At most one staple can claim each scaffold base. Each oligo may instead be
    left unassigned. Optimality is only within the retained (possibly pruned)
    candidate pool; this never certifies image routing.
    """
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix, vstack
    from backend.core.publication_domain_optimization import DomainOccupancy
    model=DomainOccupancy(search,scaffold_length)
    rows=model.rows;count=len(rows);options=model.options;costs=model.costs
    matrix=model.matrix;lower=model.lower;upper=model.upper
    settings={'time_limit':time_limit,'mip_rel_gap':0.}
    result=model.solve(time_limit)
    report={'method':'nonoverlapping-scaffold-domain-milp','solver_status':int(result.status),'solver_message':result.message,
        'time_limit_seconds_per_solve':time_limit,'native_routing_resolved':False,
        'candidate_pool_complete':all(r['search_complete_within_bounds'] for r in rows),
        'limitation':'Compatibility covers scaffold occupancy only. Image positions, allowed crossovers and scaffold identity remain unverified; pruned pools cannot prove global uniqueness.'}
    if result.x is None:return {**report,'status':'no_incumbent','assignments':[]}
    selected=np.flatnonzero(result.x>.5);assignments=[];total=0
    for column in selected:
        row_index,candidate_index=options[column];candidate=rows[row_index]['candidates'][candidate_index] if candidate_index is not None else None
        total+=candidate['paired_bases'] if candidate else 0
        assignments.append({'row_id':rows[row_index]['row_id'],'candidate_index':candidate_index})
    report.update(status='optimal_in_retained_pool' if result.status==0 else 'incumbent_not_proven_optimal',assignments=assignments,paired_bases=total,
                  objective=float(result.fun),mip_gap=float(result.mip_gap))
    if result.status==0:
        no_good=coo_matrix((np.ones(len(selected)),(np.zeros(len(selected),dtype=int),selected)),shape=(1,len(options))).tocsc()
        constrained=LinearConstraint(vstack([matrix,no_good]),np.r_[lower,0],np.r_[upper,count-1])
        alternative=milp(np.array(costs,dtype=float),integrality=np.ones(len(options)),bounds=Bounds(0,1),constraints=constrained,options=settings)
        tied=alternative.fun is not None and abs(alternative.fun-result.fun)<.5
        report['alternative_search']={'solver_status':int(alternative.status),'equal_score_witness':bool(tied),
            'status':'ambiguous_in_retained_pool' if tied else 'no_equal_alternative_in_retained_pool' if alternative.status in (0,2) else 'budget_exhausted',
            'objective':float(alternative.fun) if alternative.fun is not None else None,
            'assignments':model.assignments(alternative) if tied else []}
    return report


def sequence_fallback(rows, scaffold, *, scaffold_name='unverified supplied scaffold', beam_width=8, time_limit=2):
    """Two bounded passes, followed by occupancy compatibility and ambiguity checks."""
    if not 1<=len(rows)<=500:raise ValueError('Select 1–500 table rows for sequence fallback.')
    passes=[]
    for minimum in (8,6):
        search=align_table(rows,scaffold,minimum_domain=minimum,beam_width=beam_width,max_transitions=50000)
        compatibility=select_compatible_domains(search,len(scaffold),time_limit=time_limit)
        passes.append({'minimum_domain':minimum,'alignment':search,'compatibility':compatibility})
    from backend.core.publication_sequence_anchors import identify_stable_anchors, challenge_anchors
    anchors=identify_stable_anchors(rows,scaffold,passes)
    anchors=challenge_anchors(anchors,passes,len(scaffold),maximum_probes=4,time_limit=min(1,time_limit),paired_slack=4)
    from backend.core.publication_sequence_refinement import expand_anchor_candidates
    refinement=expand_anchor_candidates(rows,scaffold,passes,anchors,maximum_rows=12,beam_width=16,max_transitions=50000,time_limit=time_limit)
    return {'anchor_refinement':refinement,'anchors':anchors,'method':'split-domain-alignment-and-occupancy-v2','scaffold_name':scaffold_name,
            'scaffold_identity_confirmed':False,'passes':passes,'native_routing_resolved':False,
            'limitation':'Sequence-domain candidates only. No image-to-domain placement or permitted crossover graph has been established. Equal-score solutions and search budgets are retained.'}
