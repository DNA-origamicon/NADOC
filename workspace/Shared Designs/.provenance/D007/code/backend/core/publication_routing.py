"""Extract legacy caDNAno vector figures and endpoint-labelled staple tables.

All calibration and routing inputs come from the PDF. Native design files are
not accepted by this module. Results are evidence, not authored molecular models.
"""
from collections import Counter, defaultdict
import math
import re
from statistics import median

import pymupdf

from backend.core.publication_diagram_labels import numeric_labels


_TABLE_ROW = re.compile(r'(\d+)\[(\d+)\]\s+(\d+)\[(\d+)\]\s+([ACGTacgt]+)\s+(\d+)\s+(#[0-9a-fA-F]{6})')


def staple_tables(doc):
    tables = []
    for index, page in enumerate(doc):
        text = page.get_text()
        rows = [{'start':[int(m[1]),int(m[2])], 'end':[int(m[3]),int(m[4])],
                 'sequence':m[5], 'length':int(m[6]), 'color':m[7]}
                for m in _TABLE_ROW.finditer(text)]
        if rows:
            tables.append({'page':index+1, 'rows':rows,
                           'context':text[:text.find(rows[0]['sequence'])],
                           'sequence_lengths_valid':all(len(r['sequence'])==r['length'] for r in rows)})
    return tables


def extract_publication_paths(page):
    short = [tuple(round(v) for v in t['dir']) for t in page.get_texttrace() if 0<len(t['chars'])<=3]
    direction = Counter(short).most_common(1)[0][0] if short else (1,0)
    rotation = {(1,0):0,(0,-1):270,(-1,0):180,(0,1):90}.get(direction,0)
    if rotation:
        with pymupdf.open() as normalized:
            width,height=page.rect.width,page.rect.height
            target=normalized.new_page(width=height if rotation%180 else width,
                                       height=width if rotation%180 else height)
            target.show_pdf_page(target.rect,page.parent,page.number,rotate=rotation)
            result=_extract_publication_paths(target)
            result['normalization_rotation']=rotation
            return result
    result = _extract_publication_paths(page)
    result['normalization_rotation'] = 0
    return result


def _extract_publication_paths(page):
    labels = numeric_labels(page)
    all_labels = labels
    horizontal, vertical = defaultdict(list), defaultdict(list)
    for label in labels:
        horizontal[round(label['y'],1)].append(label)
        vertical[round(label['x'],1)].append(label)
    rulers = []
    for group in horizontal.values():
        group = sorted(group,key=lambda l:l['x'])
        if len(group)<5 or len({l['value'] for l in group})!=len(group):
            continue
        slope = (group[-1]['x']-group[0]['x'])/(group[-1]['value']-group[0]['value'])
        if slope<=0:
            continue
        origin = group[0]['x']-slope*group[0]['value']
        if all(abs(l['x']-origin-slope*l['value'])<slope*.08 for l in group):
            rulers.append((group,slope,origin))
    if not rulers:
        raise ValueError('No uniformly labelled publication ruler.')
    ruler, scale, origin = max(rulers,key=lambda r:len(r[0]))
    columns = [g for g in vertical.values() if len(g)>=4 and max(l['x'] for l in g)<origin
               and len({l['value'] for l in g})==len(g)]
    if not columns:
        raise ValueError('No unique helix label column beside the ruler.')
    labels = max(columns,key=len)
    centers = {l['value']:l['y'] for l in labels}
    ys=sorted(centers.values()); pitch=median(b-a for a,b in zip(ys,ys[1:]))
    def site(point):
        row=min(centers,key=lambda n:abs(point.y-centers[n]))
        if abs(point.y-centers[row])>pitch*.25:
            raise ValueError('Path lies outside paired helix tracks.')
        return (row,math.floor((point.x-origin)/scale+1e-4))
    paths=[]
    for path_id, drawing in enumerate(page.get_drawings()):
        if drawing['color'] is None or drawing.get('fill') is not None:
            continue
        items=drawing['items']
        # A covalent route contains horizontal spans and inter-row curves.
        if not any(i[0]=='l' and abs(i[1].y-i[-1].y)<.1 and abs(i[1].x-i[-1].x)>scale*2 for i in items):
            continue
        walk=[]; previous=None
        for item in items:
            if item[0] not in ('l','c'):
                raise ValueError('Unsupported routing primitive.')
            a,b=item[1],item[-1]
            if previous is not None and abs(a-previous)>.1:
                raise ValueError('Disconnected subpaths in a candidate route.')
            previous=b
            u,v=site(a),site(b)
            if u[1]<0 or v[1]<0:
                raise ValueError('Route outside the visible ruler.')
            if u[0]==v[0] and item[0]=='l':
                if abs(a.y-b.y)>.1:
                    raise ValueError('Diagonal intrarow line requires separate interpretation.')
                step=1 if v[1]>=u[1] else -1
                segment=[(u[0],x) for x in range(u[1],v[1]+step,step)]
            else:
                segment=[u,v]
            walk.extend(segment[1:] if walk and walk[-1]==segment[0] else segment)
        if len(set(walk))!=len(walk):
            raise ValueError('Repeated sites or closed route require explicit cycle handling.')
        paths.append({'path_id':path_id,'sites':walk,'color':drawing['color']})
    if not paths:
        raise ValueError('No continuous publication routing paths.')
    insertions=[]
    for drawing in page.get_drawings():
        items=drawing['items']; rect=drawing['rect']
        if not drawing.get('color') or drawing.get('fill') is not None or len(items)!=2 or any(i[0]!='c' for i in items):
            continue
        if abs(items[0][1]-items[-1][-1])>.01 or abs(items[0][-1]-items[1][1])>.01:
            continue
        if not .5*scale<rect.width<2.5*scale or not .5*scale<rect.height<2.5*scale:
            continue
        try:
            address=site(items[0][1])
        except ValueError:
            continue
        insertions.append(address)
    return {'paths':paths,'insertion_annotations':sorted(set(insertions)),'calibration' :{'origin_x':origin,'points_per_base':scale,'row_centers':centers},
            'lattice':recover_lattice(page,all_labels,centers),
            'status':'unclassified image-derived paths'}


def pair_endpoint_table(graph, table):
    """Orient each drawn staple with published endpoints, retaining mismatches."""
    by_ends=defaultdict(list)
    for row in table['rows']:
        by_ends[frozenset((tuple(row['start']),tuple(row['end'])))].append(row)
    # Older exports can shift the printed ruler relative to the drawing. Test
    # translations proposed by actual endpoint pairs, then require a unique winner.
    offsets = {0}
    for path in graph['paths']:
        a,b=path['sites'][0],path['sites'][-1]
        for row in table['rows']:
            for start,end in [(row['start'],row['end']),(row['end'],row['start'])]:
                if a[0]==start[0] and b[0]==end[0] and start[1]-a[1]==end[1]-b[1]:
                    offsets.add(start[1]-a[1])
    counts = {}
    for offset in offsets:
        counts[offset]=sum(len(by_ends.get(frozenset(((p['sites'][0][0],p['sites'][0][1]+offset),
                                                     (p['sites'][-1][0],p['sites'][-1][1]+offset))),[]))==1
                           for p in graph['paths'])
    maximum=max(counts.values(),default=0)
    winners=[offset for offset,count in counts.items() if count==maximum]
    offset=winners[0] if len(winners)==1 and maximum>=3 else 0
    insertion_sites={(h,b+offset) for h,b in graph.get('insertion_annotations',[])}
    matched=[]; remaining=[]
    for path in graph['paths']:
        sites=[(h,b+offset) for h,b in path['sites']]; rows=by_ends.get(frozenset((sites[0],sites[-1])),[])
        if len(rows)!=1:
            remaining.append({**path,'sites':sites});continue
        row=rows[0]; directed=sites if sites[0]==tuple(row['start']) else sites[::-1]
        matched.append({**path,'sites':directed,'table_row':row,
                        'length_agrees':len(sites)==row['length'],
                        'length_with_unit_insertions_agrees':len(sites)+len(set(sites)&insertion_sites)==row['length'],
                        'observed_insertions':sorted(set(sites)&insertion_sites),
                        'sequence_length_agrees':len(row['sequence'])==row['length']})
    unit_insertions={site for p in matched if p['length_with_unit_insertions_agrees'] for site in p['observed_insertions']}
    return {'unit_insertions':sorted(unit_insertions), 'unresolved_insertions':sorted(insertion_sites-unit_insertions),
            'base_index_offset':offset, 'offset_candidates':counts, 'offset_resolved':len(winners)==1 and maximum>=3,
            'matched':matched,'unmatched_paths':remaining,'table_rows':len(table['rows']),
            'all_table_endpoints_matched':len(matched)==len(table['rows']) and len({tuple(p['table_row']['start']) for p in matched})==len(table['rows'])}


def classify_scaffold(pairing):
    """Orient unmatched scaffold strokes only with unanimous antiparallel evidence."""
    staple_steps={}
    for path in pairing['matched']:
        for a,b in zip(path['sites'],path['sites'][1:]):
            if a[0]==b[0] and abs(b[1]-a[1])==1:
                staple_steps[a]=b[1]-a[1]
                staple_steps[b]=b[1]-a[1]
    scaffold=[]; unresolved=[]
    for path in pairing['unmatched_paths']:
        votes=[]
        for a,b in zip(path['sites'],path['sites'][1:]):
            if a[0]==b[0] and abs(b[1]-a[1])==1 and a in staple_steps:
                votes.append((b[1]-a[1])*staple_steps[a])
        if len(votes)<3 or len(set(votes))!=1:
            unresolved.append(path);continue
        sites=path['sites'] if votes[0]<0 else path['sites'][::-1]
        scaffold.append({**path,'sites':sites,'antiparallel_votes':len(votes)})
    return {'scaf':scaffold,'stap':pairing['matched'],'unresolved':unresolved}


def publication_evidence(graph, tables, custom_sequence=None):
    from backend.core.publication_sequence_search import search_declared_scaffold
    from backend.core.publication_unpaired_scaffold import aligned_unpaired_scaffold
    from backend.core.publication_auxiliary_placement import infer_auxiliary_placement
    candidates=[]
    for table in tables:
        pairing=pair_endpoint_table(graph,table)
        if len(pairing['matched'])<3 or not pairing['offset_resolved']:
            continue
        classified=classify_scaffold(pairing)
        insertion_solution=resolve_insertions(pairing,classified,table)
        sequence_search=search_declared_scaffold(classified,insertion_solution,table,custom_sequence)
        source_insertions=insertion_solution
        hypothesis=sequence_search.get('insertion_hypothesis')
        if hypothesis and hypothesis['sequence_supported'] and sequence_search.get('sequence_supported'):
            insertion_solution={**insertion_solution,**hypothesis,
                                'represented_scaffold_length':sequence_search['represented_length'],
                                'sequence_length_discrepancy':sequence_search['length_discrepancy']}
        unpaired = aligned_unpaired_scaffold(classified, insertion_solution, table,
                                             sequence_search, graph['lattice'], custom_sequence)
        candidates.append({'sequence_search':sequence_search,
                           'unpaired_scaffold': unpaired,
                           'auxiliary_placement': infer_auxiliary_placement(graph['lattice'], classified, unpaired),
                           'normalization_rotation': graph.get('normalization_rotation', 0),
                           'source_insertion_solution':source_insertions,
                           'sequence_resolved_loops':len(source_insertions['unresolved'])-len(insertion_solution['unresolved']),
                           'table_page':table['page'], 'table_rows':len(table['rows']),
                           'matched_staples':len(pairing['matched']),
                           'lengths_agree':sum(p['length_with_unit_insertions_agrees'] for p in pairing['matched']),
                           'unit_insertions_resolved':len(pairing['unit_insertions']),
                           'unresolved_insertions':len(insertion_solution['unresolved']),
                           'insertion_solution':insertion_solution,
                           'sequence_lengths_agree':sum(p['sequence_length_agrees'] for p in pairing['matched']),
                           'base_index_offset':pairing['base_index_offset'],
                           'scaffold_paths':len(classified['scaf']),
                           'unclassified_paths':len(classified['unresolved']),
                           'all_table_endpoints_matched':pairing['all_table_endpoints_matched'],
                           'complete_reconstruction':False,
                           'recovered_topology':{
                               'directed_paths':{kind:[p['sites'] for p in classified[kind]] for kind in ('scaf','stap')},
                               'lattice':graph['lattice'], 'insertions':insertion_solution,
                               'unclassified_paths':[p['sites'] for p in classified['unresolved']],
                               'deletions_verified':False},
                           'basis':'visible path geometry and published staple endpoints',
                           'limitation':'Endpoint and length agreement does not certify sequence complementarity, indels, lattice geometry or completeness of the publication.'})
    return sorted(candidates,key=lambda c:-c['matched_staples'])


def recover_lattice(page, labels, row_ids):
    """Read labelled circles and fit a honeycomb inset, allowing export rounding."""
    circles={}
    for drawing in page.get_drawings():
        items=drawing['items'];rect=drawing['rect']
        if not drawing.get('color') or len(items)!=4 or not all(i[0]=='c' for i in items):
            continue
        if rect.width<=0 or abs(rect.width-rect.height)>.03*rect.width:
            continue
        inside=[n for n in labels if rect.contains(pymupdf.Point(n['x'],n['y']))]
        if len(inside)==1 and inside[0]['value'] in row_ids:
            key=inside[0]['value']
            if key in circles:
                return {'resolved':False,'reason':'Repeated lattice labels.'}
            circles[key]=((rect.x0+rect.x1)/2,(rect.y0+rect.y1)/2,rect.width/2)
    missing = sorted(set(row_ids) - set(circles))
    if len(circles) < 3:
        return {'resolved': False, 'inset_resolved': False,
                'missing_helices': missing, 'reason': 'Incomplete numbered lattice inset.'}
    radius=median(v[2] for v in circles.values())
    minx=min(v[0] for v in circles.values());miny=min(v[1] for v in circles.values())
    fits=[]
    for phase in (0,1):
        cells={};residual=0
        for helix,(x,y,r) in circles.items():
            col=round((x-minx)/(math.sqrt(3)*radius))
            options=[(abs(y-(miny+3*radius*row+radius*((row+col+phase)%2))),row)
                     for row in range(round((y-miny)/(3*radius))+2)]
            error,row=min(options)
            residual=max(residual,error,abs(x-minx-col*math.sqrt(3)*radius),abs(r-radius))
            cells[helix]=[row,col]
        if residual<radius*.15 and len({tuple(v) for v in cells.values()})==len(cells):
            fits.append({'resolved':True,'kind':'honeycomb','cells':cells,'max_residual_in_radii':residual/radius})
    if len(fits) != 1:
        return {'resolved': False, 'inset_resolved': False, 'missing_helices': missing,
                'reason': 'Lattice does not have a unique honeycomb fit.'}
    fit = {**fits[0], 'inset_resolved': True, 'missing_helices': missing}
    if missing:
        fit.update(resolved=False, reason='Path-view helices absent from numbered lattice inset.')
    return fit


def resolve_insertions(pairing, classified, table):
    """Solve positive loop lengths from oligo lengths and a declared scaffold length.

    A single remaining scaffold-only loop is identifiable by mass balance. More
    than one remains unresolved; no sequence or reference fills that ambiguity.
    """
    counts={tuple(site):1 for site in pairing['unit_insertions']}
    unknown={tuple(site) for site in pairing['unresolved_insertions']}
    declared=re.findall(r'\bp(\d+)\s+scaffold\b',table.get('context',''),re.I)
    if len(set(declared))==1 and len(unknown)==1 and len(classified['scaf'])==1:
        scaffold=classified['scaf'][0]['sites']; site=next(iter(unknown))
        if site in scaffold:
            remaining=int(declared[0])-len(scaffold)-sum(counts.get(p,0) for p in scaffold)
            if remaining>0:
                counts[site]=remaining;unknown.clear()
    lengths_ok=all(len(p['sites'])+sum(counts.get(site,0) for site in p['sites'])==p['table_row']['length']
                   for p in pairing['matched'])
    return {'counts':[[h,b,n] for (h,b),n in sorted(counts.items())],
            'unresolved':sorted(unknown),'all_matched_lengths_agree':lengths_ok,
            'declared_scaffold_length':int(declared[0]) if len(set(declared))==1 else None,
            'method':'positive insertion lengths from staple lengths and declared scaffold length; assumes no compensating deletions'}
