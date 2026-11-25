"""Bounded scaffold-loop hypotheses from sequence evidence, without model edits."""
import math
import re

import numpy as np

MAX_LOOP_BASES = 512
MAX_PARTITIONS = 4096
LENGTH_PENALTY = 10.0  # Evidence-score points; not a calibrated probability.


def _partitions(total, count):
    if count == 0:
        if total == 0:
            yield ()
        return
    if count == 1:
        if 1 <= total <= MAX_LOOP_BASES:
            yield (total,)
        return
    for first in range(max(1,total-(count-1)*MAX_LOOP_BASES), min(MAX_LOOP_BASES,total-count+1)+1):
        for rest in _partitions(total-first,count-1):
            yield (first,*rest)


def search_loop_candidates(classified, insertions, sequence):
    """Score every shift/direction for every bounded positive loop partition.

    Unresolved annotations must be scaffold-only. Segment register costs allow
    all candidates to be scored without re-aligning every staple for each loop
    length combination. +/-1 length hypotheses leave an explicit gap at the nick;
    they never insert, delete or ligate a nucleotide in the observed graph.
    """
    sequence=re.sub(r'\s+','',sequence).upper()
    if not sequence or set(sequence)-set('ACGT'):
        raise ValueError('Scaffold sequence must contain only A/C/G/T.')
    if len(classified['scaf'])!=1:
        raise ValueError('Loop search requires one scaffold.')
    sites=[tuple(s) for s in classified['scaf'][0]['sites']]
    known={(h,b):n for h,b,n in insertions['counts']}
    loops={tuple(s) for s in insertions['unresolved']}
    stap_sites=[tuple(s) for p in classified['stap'] for s in p['sites']]
    if len(set(sites))!=len(sites) or len(set(stap_sites))!=len(stap_sites):
        raise ValueError('Repeated strand sites cannot count as independent evidence.')
    if loops & set(stap_sites) or not loops.issubset(sites):
        raise ValueError('Unresolved loops must be observed scaffold-only annotations.')
    if loops & known.keys() or len(known)!=len(insertions['counts']) or any(type(n)!=int or n<1 for n in known.values()):
        raise ValueError('Invalid or conflicting loop annotations.')
    if len(loops)>3:
        raise ValueError('Loop search bound exceeded: at most three unresolved loops.')
    base_length=sum(1+known.get(s,0) for s in sites)
    n=len(sequence)
    partitions=[]
    for delta in (0,1,-1):  # sequence length minus represented length
        total=n-base_length-delta
        if total < len(loops) or total > len(loops)*MAX_LOOP_BASES:
            continue
        if loops and math.comb(total-1,len(loops)-1)>MAX_PARTITIONS:
            raise ValueError('Loop search partition bound exceeded; additional evidence is required.')
        partitions.extend((part,delta) for part in _partitions(total,len(loops)))
    if not partitions or len(partitions)>MAX_PARTITIONS:
        raise ValueError('No loop partitions fit the configured search bounds.')
    complement=np.frombuffer(sequence.translate(str.maketrans('ACGT','TGCA')).encode(),dtype=np.uint8)
    candidates=[]; hypotheses=0
    for reverse in (False,True):
        order=sites[::-1] if reverse else sites
        blocks={}; boundaries=[]; ordered_loops=[]; cursor=0
        for site in order:
            blocks[site]=list(range(cursor,cursor+1+known.get(site,0)))
            cursor+=1+known.get(site,0)
            if site in loops:
                boundaries.append(cursor);ordered_loops.append(site)
        idx=[];obs=[]
        for path in classified['stap']:
            raw=re.sub(r'\s+','',path['table_row']['sequence']).upper()
            template=[i for site in path['sites'] for i in reversed(blocks.get(tuple(site),[None]*(1+known.get(tuple(site),0))))]
            if len(raw)!=len(template) or path['table_row'].get('length',len(raw))!=len(raw) or set(raw)-set('ACGT'):
                raise ValueError('Loop search requires length-consistent staple sequences.')
            for i,base in zip(template,raw):
                if i is not None:
                    idx.append(i);obs.append(ord(base))
        if not idx:
            raise ValueError('No paired sequence evidence for loop search.')
        idx=np.asarray(idx,dtype=np.int64);obs=np.asarray(obs,dtype=np.uint8)
        segments=np.searchsorted(boundaries,idx,side='right')
        costs=[]
        for segment in range(len(loops)+1):
            selected=segments==segment
            # Empty flanking regions contribute no evidence. Equivalent loop
            # partitions therefore remain ties rather than receiving a guess.
            a,b=idx[selected],obs[selected]
            scores=np.zeros(n,dtype=np.int32)
            for start in range(0,n,128):
                offsets=np.arange(start,min(start+128,n))
                scores[start:start+len(offsets)]=np.count_nonzero(complement[(a[None,:]+offsets[:,None])%n]!=b,axis=1)
            costs.append(scores)
        offsets=np.arange(n)
        for partition,delta in partitions:
            cumulative=0;score=costs[0].copy()
            for segment,length in enumerate(partition,1):
                cumulative+=length
                score+=costs[segment][(offsets+cumulative)%n]
            extra=0
            if delta<0:
                shifted=idx+np.asarray([sum(partition[:segment]) for segment in segments])
                omitted=shifted>=n
                extra=int(np.count_nonzero(omitted))
                if extra:
                    score-=np.count_nonzero(complement[(shifted[omitted][None,:]+offsets[:,None])%n]!=obs[omitted],axis=1)
            minimum=int(score.min())
            matches=np.flatnonzero(score==minimum)
            candidates.append({'reverse':reverse,'offset':int(matches[0]),'mismatches':minimum,
                               'compared_bases':len(idx)-extra,'length_discrepancy':delta,
                               'loop_counts':[[h,b,count] for (h,b),count in zip(ordered_loops,partition)],
                               'penalty_points':LENGTH_PENALTY*abs(delta),
                               'offset_ties':len(matches),'offset_candidates':matches[:8].tolist()})
            hypotheses+=n
    candidates.sort(key=lambda c:(c['mismatches'],abs(c['length_discrepancy']),c['reverse'],c['offset']))
    best=candidates[0]
    return {'best':best,'alternatives':candidates[:8],
            'best_ties':sum(c['offset_ties'] for c in candidates if (c['mismatches'],abs(c['length_discrepancy']))==(best['mismatches'],abs(best['length_discrepancy']))),
            'candidates_tested':hypotheses,'partitions_tested':len(partitions),
            'bounds':{'max_loop_bases':MAX_LOOP_BASES,'max_partitions':MAX_PARTITIONS,'max_length_discrepancy':1},
            'method':'bounded positive scaffold-loop partitions, all cyclic shifts and both directions'}
