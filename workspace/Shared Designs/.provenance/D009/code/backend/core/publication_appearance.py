"""Preserve observed diagram styling without using it to infer molecular routing."""
import math
import re
from collections import defaultdict


def rgb_hex(rgb):
    if not isinstance(rgb,(tuple,list)) or len(rgb)!=3 or any(not math.isfinite(v) or not 0<=v<=1 for v in rgb):
        return None
    return '#'+''.join(f'{round(v*255):02x}' for v in rgb)


def staple_colors(paths):
    """Prefer the PDF stroke; infer missing strokes only from an unanimous palette.

    PDF color conversion need not equal the table's nominal caDNAno hex value.
    Keep both observations and explicitly label fallback for table-only routes.
    """
    palette=defaultdict(set)
    for path in paths:
        observed=rgb_hex(path.get('color'))
        table=path.get('table_row',{}).get('color','').lower()
        if observed and re.fullmatch(r'#[0-9a-f]{6}',table):palette[table].add(observed)
    result=[]
    for path in paths:
        observed=rgb_hex(path.get('color'))
        table=path.get('table_row',{}).get('color','').lower()
        if observed:color,basis=observed,'source PDF route stroke'
        elif len(palette[table])==1:color,basis=next(iter(palette[table])),'table color mapped to unanimous observed figure palette'
        elif re.fullmatch(r'#[0-9a-f]{6}',table):color,basis=table,'table color; no unique observed figure palette mapping'
        else:color,basis=None,'no source color; editor default retained'
        result.append({'color':color,'basis':basis,'image_color':observed,'table_color':table or None})
    return result


def figure_order(row_centers, sources):
    """Top-to-bottom in the orientation-normalized figure; stable auxiliary ties."""
    centers={int(h):y for h,y in row_centers.items()}
    if any(source['source_helix'] not in centers for source in sources.values()):
        raise ValueError('Missing source row position; cannot preserve figure order')
    return sorted(sources,key=lambda h:(centers[sources[h]['source_helix']],h))
