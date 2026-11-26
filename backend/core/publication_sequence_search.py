"""Bounded, exhaustive sequence-register search; never edits routing or nicks."""
import hashlib
import re

import numpy as np


def apply_supported_insertions(insertions, search):
    """Carry accepted loop-count evidence into native planning without editing it."""
    from copy import deepcopy
    solution = deepcopy(insertions)
    hypothesis = search.get('insertion_hypothesis')
    if hypothesis and hypothesis.get('sequence_supported') and search.get('sequence_supported'):
        solution.update(deepcopy(hypothesis))
        solution['represented_scaffold_length'] = search['represented_length']
        solution['sequence_length_discrepancy'] = search['length_discrepancy']
    return solution


def search_scaffold_register(classified, insertions, sequence, *, scaffold_name='custom', allow_length_discrepancy=False):
    """Score every cyclic shift in both directions against every supplied staple.

    Insertion bases are expanded into scaffold-order blocks. Staple traversal
    reverses each paired block. Missing partners are not assigned invented bases.
    A sequence origin is reported separately from the observed physical nick.
    """
    sequence=re.sub(r'\s+', '', sequence).upper()
    if not sequence or set(sequence)-set('ACGT'):
        raise ValueError('Scaffold sequence must contain only A/C/G/T.')
    if len(classified['scaf'])!=1 or insertions['unresolved']:
        raise ValueError('One scaffold and resolved insertion lengths are required.')
    sites=[tuple(s) for s in classified['scaf'][0]['sites']]
    counts={(h,b):n for h,b,n in insertions['counts']}
    if len(counts)!=len(insertions['counts']) or any(not isinstance(n,int) or isinstance(n,bool) for n in counts.values()):
        raise ValueError('Duplicate or noninteger insertion annotations.')
    staple_sites=[tuple(site) for path in classified['stap'] for site in path['sites']]
    if len(set(staple_sites))!=len(staple_sites):
        raise ValueError('Repeated staple sites cannot count as independent evidence.')
    if set(counts)-set(sites)-set(staple_sites):
        raise ValueError('Insertion annotation has no observed strand site.')
    if len(set(sites))!=len(sites) or any(n<1 for n in counts.values()):
        raise ValueError('Repeated scaffold sites or invalid insertion lengths.')
    n=len(sequence)
    represented_length=sum(1+counts.get(s,0) for s in sites)
    discrepancy=n-represented_length
    if discrepancy and (not allow_length_discrepancy or abs(discrepancy)>1):
        raise ValueError('Expanded scaffold length does not match the supplied sequence.')
    complement=np.frombuffer(sequence.translate(str.maketrans('ACGT','TGCA')).encode(),dtype=np.uint8)
    results=[]; mappings={}; observations={}
    for reverse in (False,True):
        addresses=[]; blocks={}
        for site in (sites[::-1] if reverse else sites):
            start=len(addresses)
            addresses.extend((site[0],site[1],i) for i in range(1+counts.get(site,0)))
            blocks[site]=list(range(start,len(addresses)))
        indices=[]; bases=[]; records=[]; invalid=[]
        for row,path in enumerate(classified['stap']):
            raw=re.sub(r'\s+', '', path['table_row']['sequence']).upper()
            template=[i for s in path['sites'] for i in reversed(blocks.get(tuple(s),[None]*(1+counts.get(tuple(s),0))))]
            if len(raw)!=len(template) or path['table_row'].get('length',len(raw))!=len(raw) or set(raw)-set('ACGT'):
                invalid.append(row);continue
            template=[i if i is None or i<n else None for i in template]
            known=[(i,ord(base)) for i,base in zip(template,raw) if i is not None]
            start=len(indices);indices.extend(i for i,_ in known);bases.extend(b for _,b in known)
            records.append({'row':row,'start':start,'end':len(indices),'unknown_bases':sum(i is None for i in template)})
        if not indices:
            raise ValueError('No comparable staple bases.')
        idx=np.asarray(indices,dtype=np.int64); observed=np.asarray(bases,dtype=np.uint8)
        # Bounded batches avoid allocating a scaffold-length × all-bases matrix.
        for start in range(0,n,128):
            offsets=np.arange(start,min(start+128,n))
            mismatches=np.count_nonzero(complement[(idx[None,:]+offsets[:,None])%n]!=observed,axis=1)
            results.extend((int(score),reverse,int(offset)) for score,offset in zip(mismatches,offsets))
        mappings[reverse]=addresses
        observations[reverse]=(idx,observed,records,invalid)
    results.sort()
    score,reverse,offset=results[0]
    idx,observed,records,invalid=observations[reverse]
    wrong=complement[(idx+offset)%n]!=observed
    rows=[{'staple_row':r['row'],'compared_bases':r['end']-r['start'],
           'mismatches':int(np.count_nonzero(wrong[r['start']:r['end']])),
           'unknown_bases':r['unknown_bases']} for r in records]
    mismatch_details=[]
    for r in records:
        for local in np.flatnonzero(wrong[r['start']:r['end']]):
            j=r['start']+int(local)
            mismatch_details.append({'staple_row':r['row'], 'paired_base_index':int(local),
                                     'scaffold_address':list(mappings[reverse][int(idx[j])]),
                                     'observed':chr(int(observed[j])),
                                     'expected':chr(int(complement[(idx[j]+offset)%n]))})
    ties=sum(r[0]==score for r in results)
    unknown=sum(r['unknown_bases'] for r in rows)
    return {'method':'exhaustive cyclic shifts in both scaffold directions',
            'scaffold_name':scaffold_name,'scaffold_length':n,
            'scaffold_sha256':hashlib.sha256(sequence.encode()).hexdigest(),
            'candidates_tested':2*n,'best_ties':ties,
            'represented_length':represented_length,'length_discrepancy':discrepancy,
            'unrepresented_sequence_indices':[(offset+represented_length)%n] if discrepancy>0 else [],
            'unassigned_image_addresses':[list(a) for a in mappings[reverse][n:]],
            'gap_location_verified':False if discrepancy else None,
            'length_discrepancy_note':'A one-base gap is placed at the observed nick boundary for alignment; its physical location and cause remain unverified. No topology was changed.' if discrepancy else '',
            'resolved':ties==1 and score==0 and not invalid and unknown==0,
            'best':{'reverse':reverse,'offset':offset,'mismatches':score,
                    'compared_bases':len(idx),'unknown_bases':unknown,
                    'unpaired_scaffold_bases':n-len(set(idx.tolist())),
                    'sequence_origin_address':list(mappings[reverse][(-offset)%n]) if (-offset)%n<represented_length else None,
                    'exact_staples':sum(r['mismatches']==0 and r['unknown_bases']==0 for r in rows)},
            'runner_up_mismatches':results[1][0], 'invalid_staple_rows':invalid,
            'staples':rows, 'mismatch_details':mismatch_details[:100],
            'mismatch_details_truncated':len(mismatch_details)>100,
            'alternatives':[{'mismatches':s,'reverse':rev,'offset':off} for s,rev,off in results[:8]],
            'nick_note':'Sequence origin is a register hypothesis; the observed physical nick is not moved.'}


def search_declared_scaffold(classified, insertions, table, custom_sequence=None):
    """Search named scaffolds, or explicitly labelled length-matched hypotheses.

    A declared but unavailable scaffold never falls back silently to another one.
    Sequence alignment of recovered routes is distinct from validating all rows.
    """
    from backend.core.sequences import SCAFFOLD_LIBRARY, P7704_SEQUENCE
    if len(classified['scaf'])!=1:
        return {'resolved':False,'reason':'One scaffold and resolved insertion lengths are required.',
                'status':'unresolved_routing'}
    library={name.lower():(name,seq) for name,_,seq in SCAFFOLD_LIBRARY}
    library['p7704']=('p7704',P7704_SEQUENCE)
    if custom_sequence:
        candidates=[('custom',custom_sequence)]; basis='user-supplied sequence'
    else:
        mentions=re.findall(r'\b(p[A-Za-z0-9]+|M13mp18)\s+scaffold\b|\((p[A-Za-z0-9]+|M13mp18)\)',table.get('context',''),re.I)
        names={name.lower() for pair in mentions for name in pair if name}
        if names:
            if len(names)!=1 or not names.issubset(library):
                return {'resolved':False,'reason':'Supply the scaffold sequence; the named scaffold is unavailable or ambiguous.',
                        'status':'unsupported_scaffold'}
            candidates=[library[next(iter(names))]];basis='scaffold named in publication'
        else:
            counts={(h,b):n for h,b,n in insertions['counts']}
            length=sum(1+counts.get(tuple(s),0) for s in classified['scaf'][0]['sites'])
            unknown=len(insertions['unresolved'])
            candidates=[(name,seq) for name,seq in library.values()
                        if length+unknown-1<=len(seq)<=length+512*unknown+1]
            basis='length-matched library hypotheses; scaffold not named in table' if not insertions['unresolved'] else 'bounded loop-length library hypotheses; scaffold not named in table'
            if not candidates:
                return {'resolved':False,'reason':f'No library scaffold matches the expanded length {length}; supply its sequence.',
                        'status':'unsupported_scaffold'}
    results=[]; unsearched=[]
    for name,sequence in candidates:
        try:
            results.append(_search_candidate(classified,insertions,sequence,name))
        except ValueError as exc:
            unsearched.append({'name':name,'reason':str(exc)})
    if not results:
        return {'resolved':False,'reason':unsearched[0]['reason'],'status':'invalid_sequence_evidence','unsearched_candidates':unsearched}
    results.sort(key=lambda r:(r['best']['mismatches'],abs(r.get('length_discrepancy',0))))
    best=results[0]
    best['selection_basis']=basis
    best['unsearched_candidates']=unsearched
    best['search_complete']=not unsearched
    best['scaffolds_tested']=[{'name':r['scaffold_name'],'sha256':r['scaffold_sha256'],
                             'mismatches':r['best']['mismatches'],'best_ties':r['best_ties']} for r in results]
    best['candidates_tested']=sum(r['candidates_tested'] for r in results)
    tied=[r for r in results if (r['best']['mismatches'],abs(r.get('length_discrepancy',0)))==(best['best']['mismatches'],abs(best.get('length_discrepancy',0)))]
    best['best_ties']=sum(r['best_ties'] for r in tied)
    if len(results)>1:
        best['runner_up_mismatches']=min(best['runner_up_mismatches'],results[1]['best']['mismatches'])
    best['sequence_supported']=best['best']['mismatches']==0 and best['best_ties']==1 and not best['invalid_staple_rows'] and not unsearched
    best['alignment_resolved']=best['resolved'] and best['best_ties']==1 and not unsearched
    best['table_rows']=len(table.get('rows',classified['stap']))
    best['matched_rows']=len(classified['stap'])
    best['unmatched_table_rows']=max(0,best['table_rows']-best['matched_rows'])
    best['resolved']=best['alignment_resolved'] and best['unmatched_table_rows']==0 and best.get('length_discrepancy',0)==0
    best['status']='supported_with_length_discrepancy' if best['sequence_supported'] and best.get('length_discrepancy') else 'validated' if best['resolved'] else 'partial_or_conflicting_evidence'
    if best.get('insertion_hypothesis'):
        best['insertion_hypothesis']['sequence_supported']=best['sequence_supported']
    best['confidence']=_confidence(best)
    return best


def _search_candidate(classified, insertions, sequence, name):
    from backend.core.publication_loop_search import search_loop_candidates
    solution=insertions
    loop_search=None
    if insertions['unresolved']:
        loop_search=search_loop_candidates(classified,insertions,sequence)
        solution={**insertions,'counts':[*insertions['counts'],*loop_search['best']['loop_counts']],'unresolved':[]}
    result=search_scaffold_register(classified,solution,sequence,scaffold_name=name,allow_length_discrepancy=True)
    if loop_search:
        best=loop_search['best']
        if (result['best']['mismatches'],result['best']['reverse'],result['best']['offset']) != (best['mismatches'],best['reverse'],best['offset']):
            raise ValueError('Loop candidate disagrees with independent full-route sequence validation.')
        result['loop_search']=loop_search
        result['candidates_tested']=loop_search['candidates_tested']
        if len(loop_search['alternatives'])>1:
            result['runner_up_mismatches']=min(result['runner_up_mismatches'],loop_search['alternatives'][1]['mismatches'])
        result['best_ties']=loop_search['best_ties']
        result['resolved']=result['resolved'] and loop_search['best_ties']==1
        result['insertion_hypothesis']={'counts':solution['counts'],'unresolved':[],
            'method':'flanking-sequence loop search; original paths are unchanged',
            'sequence_supported':best['mismatches']==0 and loop_search['best_ties']==1}
    return result


def _confidence(result):
    """Transparent evidence score, deliberately not a probability of correctness."""
    from backend.core.publication_loop_search import LENGTH_PENALTY
    best=result['best']; penalties=[]
    if result.get('length_discrepancy'):
        penalties.append({'reason':'one-base scaffold length discrepancy','points':LENGTH_PENALTY})
    if result.get('unmatched_table_rows'):
        penalties.append({'reason':'unmatched staple table rows','points':100*result['unmatched_table_rows']/max(1,result['table_rows'])})
    unresolved=result.get('unresolved_partner_bases',best['unknown_bases'])
    if unresolved:
        penalties.append({'reason':('unresolved on-helix overhang sequences' if 'assigned_overhang_bases' in result
                                    else 'staple bases with unknown scaffold partners'),
                          'points':100*unresolved/max(1,best['compared_bases']+best['unknown_bases'])})
    if result['invalid_staple_rows']:
        penalties.append({'reason':'invalid staple sequences','points':100*len(result['invalid_staple_rows'])/max(1,result['matched_rows'])})
    if result.get('unsearched_candidates'):
        penalties.append({'reason':'incomplete bounded candidate search','points':20.0})
    if result['best_ties']>1:
        penalties.append({'reason':'ambiguous best hypotheses','points':20.0})
    agreement=100*(1-best['mismatches']/max(1,best['compared_bases']))
    return {'score':round(max(0,agreement-sum(p['points'] for p in penalties)),2),
            'sequence_agreement':round(agreement,2),'penalties':penalties,
            'kind':'heuristic sequence-evidence score, not a calibrated probability or whole-design confidence',
            'policy':'on-helix-overhang-v2' if 'assigned_overhang_bases' in result else 'one-base-discrepancy-v1'}
