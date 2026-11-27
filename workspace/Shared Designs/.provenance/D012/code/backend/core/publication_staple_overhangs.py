"""Assign routed on-helix overhang sequences with explicit image/table provenance."""
from collections import defaultdict
from copy import deepcopy
from backend.core.publication_base_conflicts import resolve_base_evidence


def classify_staple_overhangs(classified, insertions, image_labels=(), *, base_index_offset=0):
    scaffold={tuple(s) for p in classified['scaf'] for s in p['sites']}
    counts={(h,b):n for h,b,n in insertions['counts']}
    labels=defaultdict(list);directions=defaultdict(set)
    for label in image_labels:
        labels[(label['helix'],label['bp']+base_index_offset,label['direction'])].append(label['base'])
    for path in classified['stap']:
        for a,b in zip(path['sites'],path['sites'][1:]):
            if a[0]==b[0] and abs(b[1]-a[1])==1:directions[a[0]].add(b[1]-a[1])
    runs=[];invalid=[]
    for number,path in enumerate(classified['stap']):
        seq=path['table_row']['sequence'].upper()
        sites=[tuple(s) for s in path['sites'] for _ in range(1+counts.get(tuple(s),0))]
        if len(seq)!=len(sites) or set(seq)-set('ACGT'):
            invalid.append(number);continue
        i=0
        while i<len(sites):
            if sites[i] in scaffold:i+=1;continue
            start=i;h=sites[i][0]
            direction=next(iter(directions[h])) if len(directions[h])==1 else None
            while (i+1<len(sites) and sites[i+1] not in scaffold and sites[i+1][0]==h
                   and sites[i+1][1]-sites[i][1] in (0,direction)):
                i+=1
            end=i;observations=[]
            for j in range(start,end+1):
                values=labels.get((*sites[j],direction),[])
                readable=set(values)-{None}
                image=next(iter(readable)) if len(readable)==1 else None
                status=('conflict' if len(readable)>1 or image is not None and image!=seq[j]
                        else 'image_match' if image is not None
                        else 'table_fallback_unreadable_image' if values else 'table_fallback_no_image')
                resolution=resolve_base_evidence([
                    {'source':'table','base':seq[j]},
                    *({'source':'image','base':base} for base in sorted(readable))])
                observations.append({'site':list(sites[j]),'table_offset':j,'table_base':seq[j],
                                     'image_base':image,'status':status, **resolution})
            resolved=direction is not None and all(o['selected_base'] is not None for o in observations)
            runs.append({'staple_row':number,'source_path_id':path.get('path_id'),
                         'helix':h,'start':list(sites[start]),'end':list(sites[end]),
                         'direction':direction,'table_start':start,'table_end_exclusive':end+1,
                         'sequence':''.join(o['selected_base'] or 'N' for o in observations),
                         'table_sequence':seq[start:end+1], 'length':end-start+1,
                         'position':'five_prime' if start==0 else 'three_prime' if end==len(sites)-1 else 'internal',
                         'classification':'on_helix_overhang',
                         'resolved':resolved,'bases':observations,
                         'basis':'Drawn staple positions lack scaffold partners; table and readable image letters retained. Strongest evidence selects the base; equal evidence uses T > A > C > G. Disagreements remain non-blocking notices.'})
            i+=1
    bases=[b for r in runs for b in r['bases']]
    return {'resolved':not invalid and all(r['resolved'] for r in runs), 'runs':runs,
            'bases':len(bases),'accepted_bases':sum(r['length'] for r in runs if r['resolved']),
            'image_verified_bases':sum(b['status']=='image_match' for b in bases),
            'table_fallback_bases':sum(b['status'].startswith('table_fallback') for b in bases),
            'conflicting_bases':sum(b['status']=='conflict' for b in bases),
            'conflicts':[{'staple_row':r['staple_row'],'source_path_id':r['source_path_id'], **b}
                         for r in runs for b in r['bases'] if b['conflict']],
            'conflict_policy':'Non-blocking notices; strongest evidence first, ties use T > A > C > G.',
            'invalid_staple_rows':invalid,
            'native_authored':False,
            'limitation':'Sequence assignment does not recover missing routes or repair scaffold length discrepancies. Native publication still requires recorded on-helix overhang authoring.'}


def apply_overhang_evidence(search, overhangs):
    """Do not penalize explicitly assigned overhangs as missing scaffold sequence."""
    from backend.core.publication_sequence_search import _confidence
    result=deepcopy(search)
    if 'best' not in result:return result
    accepted=min(overhangs['accepted_bases'],result['best']['unknown_bases'])
    result['assigned_overhang_bases']=accepted
    result['unresolved_partner_bases']=result['best']['unknown_bases']-accepted
    result['overhang_sequence_conflicts']=overhangs['conflicting_bases']
    result['alignment_resolved']=(result['best']['mismatches']==0 and result['best_ties']==1
                                  and not result['invalid_staple_rows'] and not result.get('unsearched_candidates')
                                  and result['unresolved_partner_bases']==0 and overhangs['resolved'])
    result['resolved']=(result['alignment_resolved'] and not result.get('unmatched_table_rows')
                        and not result.get('length_discrepancy'))
    if result['resolved']:result['status']='validated'
    # Keep raw search/complementarity counts intact: table fallbacks are not
    # independent scaffold matches, and do not inflate exact_staples.
    result['confidence']=_confidence(result)
    return result
