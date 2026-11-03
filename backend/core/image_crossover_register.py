"""Infer a square-lattice BP register from image-derived crossover observations."""
import copy
from backend.core.crossover_positions import crossover_neighbor
from backend.core.image_reconstruction import cadnano_summary
from backend.core.models import LatticeType


def square_register_scores(draft):
    cells={v['num']:(v['row'],v['col']) for v in draft['vstrands']}
    observed=cadnano_summary(draft)['crossovers'];scores=[]
    for shift in range(32):
        hits={'scaf':0,'stap':0}
        tested=0
        for kind,h,bp,j,jp in observed:
            if bp!=jp:continue
            tested+=1
            if crossover_neighbor(LatticeType.SQUARE,*cells[h],bp+shift,is_scaffold=kind=='scaf')==cells[j]:hits[kind]+=1
        scores.append({'shift':shift,**hits,'total':sum(hits.values()),'tested':tested})
    return sorted(scores,key=lambda s:(-s['total'],s['shift']))


def translate_square_indices(draft, shift):
    """Uniform coordinate-origin translation; preserve every observed graph edge."""
    if type(shift) is not int or shift<0:raise ValueError('Nonnegative integer shift required')
    result=copy.deepcopy(draft)
    width=max(len(v['scaf']) for v in result['vstrands'])+shift
    width=((width+31)//32)*32
    for v in result['vstrands']:
        for kind in ('scaf','stap'):
            old=v[kind];v[kind]=[[-1]*4 for _ in range(width)]
            for bp,row in enumerate(old):
                adjusted=list(row)
                for col in (0,2):
                    if adjusted[col]!=-1:adjusted[col+1]+=shift
                v[kind][bp+shift]=adjusted
        for key in ('loop','skip'):
            old=v[key];v[key]=[0]*shift+old+[0]*(width-shift-len(old))
        for key in ('stap_colors','scaf_colors'):
            if key in v:v[key]=[[bp+shift,color] for bp,color in v[key]]
    return result
