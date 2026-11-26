"""Recover routing from calibrated vector diagram pixels/paths and visible labels.

This module never reads caDNAno/reference files. The supported input is a vector
PDF with a visible base-index ruler, numbered rows and separate scaffold/staple
colors. Geometry establishes an undirected graph; staple sequences resolve its
orientation. Graphic path ordering and component IDs are not biological data.
"""
from collections import Counter, defaultdict
import hashlib
import re

import pymupdf

from backend.core.article_sequence_inference import contiguous_anchor, sequence_variants, COMPLEMENT
from backend.core.image_evaluation import clusters


def _color(color, target):
    return color is not None and len(color) == 3 and max(abs(a-b) for a,b in zip(color,target)) < .04


def _numeric_words(page):
    return [(int(w[4]), (w[0]+w[2])/2, (w[1]+w[3])/2) for w in page.get_text('words') if re.fullmatch(r'\d+',w[4])]


def _components(edges):
    adjacency = defaultdict(set)
    for a,b in edges:
        if a == b:
            continue
        adjacency[a].add(b); adjacency[b].add(a)
    if any(len(neighbors) > 2 for neighbors in adjacency.values()):
        raise ValueError('Ambiguous routing junction: more than two neighbors at an observed site.')
    pending = set(adjacency)
    paths = []
    while pending:
        seed = min(pending)
        group, stack = set(), [seed]
        while stack:
            node = stack.pop()
            if node in group:
                continue
            group.add(node); stack.extend(adjacency[node]-group)
        ends = sorted(n for n in group if len(adjacency[n]) == 1)
        if len(ends) != 2:
            raise ValueError('Closed or isolated routing requires an independently identified origin.')
        path, previous, current = [], None, ends[0]
        while current is not None:
            path.append(current)
            following = adjacency[current] - ({previous} if previous is not None else set())
            previous, current = current, next(iter(following), None)
        if len(path) != len(group):
            raise ValueError('Routing component was not completely traced.')
        paths.append(path); pending -= group
    return paths


def recover_vector_graph(data, page_number=0):
    """Read a ruler, row labels and every drawn covalent edge independently."""
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if not 0 <= page_number < len(doc):
            raise ValueError('Diagram page is outside the PDF.')
        page = doc[page_number]
        drawings = page.get_drawings()
        blue = [p for p in drawings if _color(p.get('color'), (0,.4,.8)) and p.get('fill') is None]
        gray = [p for p in drawings if _color(p.get('color'), (.5,.5,.5)) and p.get('fill') is None]
        if not blue or not gray:
            raise ValueError('Separate scaffold and staple vector tracks were not found.')
        horizontal = [(i[1],i[-1]) for p in blue for i in p['items']
                      if i[0] == 'l' and abs(i[1].y-i[-1].y) < .1 and abs(i[1].x-i[-1].x) > 1]
        if not horizontal:
            raise ValueError('No horizontal scaffold spans found.')
        min_x = min(min(a.x,b.x) for a,b in horizontal)
        min_y = min(a.y for a,b in horizontal)
        nums = _numeric_words(page)
        labels = [(n,x,y) for n,x,y in nums if x < min_x-5 and y >= min_y-10]
        if len(labels) < 2:
            raise ValueError('Visible numeric helix-row labels are required.')
        columns = clusters([x for _,x,_ in labels], 4)
        label_column = max(columns, key=lambda c: sum(abs(x-c) <= 4 for _,x,_ in labels))
        labels = sorted((n,x,y) for n,x,y in labels if abs(x-label_column) <= 4)
        if len({n for n,_,_ in labels}) != len(labels):
            raise ValueError('Helix labels are not unique.')
        row_centers = {n:y for n,_,y in labels}
        spacing = min(abs(a-b) for a,b in zip(sorted(row_centers.values()),sorted(row_centers.values())[1:]))
        headers = [(n,x,y) for n,x,y in nums if y < min_y-spacing/2 and x >= min_x-3]
        header_ys = clusters([y for _,_,y in headers], 2)
        if not header_ys:
            raise ValueError('A visible base-index ruler is required; scale will not be guessed.')
        header_y = max(header_ys, key=lambda cy: sum(abs(y-cy)<2 for _,_,y in headers))
        ticks = sorted((n,x) for n,x,y in headers if abs(y-header_y)<2)
        if len(ticks) < 3 or len({n for n,x in ticks}) != len(ticks):
            raise ValueError('At least three unambiguous base-index ruler ticks are required.')
        scale = (ticks[-1][1]-ticks[0][1])/(ticks[-1][0]-ticks[0][0])
        origin = ticks[0][1]-ticks[0][0]*scale
        if scale <= 0 or any(abs(x-(origin+n*scale)) > .1*scale for n,x in ticks):
            raise ValueError('Ruler is not uniformly calibrated; piecewise calibration is required.')
        def site(point):
            value = (point.x-origin)/scale
            bp = round(value)
            row = min(row_centers,key=lambda n: abs(row_centers[n]-point.y))
            if abs(value-bp) > .12 or abs(row_centers[row]-point.y) > spacing*.35:
                raise ValueError('A path endpoint does not lie on the observed base/row grid.')
            return row,bp
        graphs, observations = {}, {}
        for kind, paths in [('scaf',blue),('stap',gray)]:
            edges, primitives = set(), []
            for p in paths:
                for item in p['items']:
                    if item[0] not in ('l','c'):
                        raise ValueError('Unsupported path primitive in a routing track.')
                    a,b = item[1],item[-1]
                    if abs(a-b) < .01:
                        continue
                    u,v = site(a),site(b)
                    primitives.append({'kind':item[0],'start':list(u),'end':list(v)})
                    if u[0] == v[0]:
                        if item[0] != 'l' or abs(a.y-b.y) > .1:
                            raise ValueError('An intrarow curve needs explicit insertion/loop interpretation.')
                        walk = [(u[0],bp) for bp in range(u[1],v[1]+(1 if v[1]>u[1] else -1),1 if v[1]>u[1] else -1)]
                        edges.update(tuple(sorted((first,second))) for first,second in zip(walk,walk[1:]))
                    else:
                        edges.add(tuple(sorted((u,v))))
            graphs[kind] = _components(edges)
            observations[kind] = {'primitives':primitives,'edge_count':len(edges)}
        # A red X is a visible deletion annotation shared by the paired tracks.
        cross_lines = [i for p in drawings if _color(p.get('color'),(.8,0,0))
                       for i in p['items'] if i[0]=='l' and abs(i[1].x-i[-1].x)>1 and abs(i[1].y-i[-1].y)>1]
        groups = defaultdict(list)
        for line in cross_lines:
            center = (line[1]+line[-1])/2
            groups[site(center)].append(line)
        deletions = []
        for address, lines in groups.items():
            slopes = {(1 if (i[-1].x-i[1].x)*(i[-1].y-i[1].y)>0 else -1) for i in lines}
            if len(lines)!=2 or slopes != {-1,1}:
                raise ValueError('Unresolved red annotation; cannot certify insertion/deletion state.')
            deletions.append(address)
        # Optional numbered square-lattice inset. Its translation is immaterial.
        circles = [p for p in drawings if p.get('fill') and _color(p.get('fill'),(1,.7,.2))]
        lattice = {}
        if circles:
            centers = [(p['rect'].tl+p['rect'].br)/2 for p in circles]
            xs,ys = clusters([c.x for c in centers],.5),clusters([c.y for c in centers],.5)
            for p,c in zip(circles,centers):
                inside = [(n,x,y) for n,x,y in nums if p['rect'].contains(pymupdf.Point(x,y))]
                if len(inside)!=1:
                    raise ValueError('A lattice inset label is missing or ambiguous.')
                lattice[inside[0][0]] = [min(range(len(ys)),key=lambda i:abs(ys[i]-c.y)),min(range(len(xs)),key=lambda i:abs(xs[i]-c.x))]
            if set(lattice) != set(row_centers):
                raise ValueError('Lattice inset and path-view labels disagree.')
        return {'schema':1, 'source_sha256':hashlib.sha256(data).hexdigest(),'page':page_number+1,
                'calibration':{'origin_x':origin,'points_per_base':scale,'ruler_ticks':ticks,'row_centers':row_centers},
                'paths':graphs,'observations':observations,'deletions':sorted(deletions),'lattice':lattice,
                'width':max(n for n,x in ticks),'status':'undirected image-derived routing'}


def orient_with_sequences(graph, scaffold_sequence, raw_staples):
    """Resolve scaffold direction/register and each staple independently.

    Only image-derived paths and supplied sequences are consulted. This is not
    a lookup of a known design. Unknown unpaired bases are reported, not filled.
    """
    if len(graph['paths']['scaf']) != 1:
        raise ValueError('This extractor requires one observed linear scaffold.')
    raw_scaffold = [tuple(p) for p in graph['paths']['scaf'][0]]
    deleted = {tuple(p) for p in graph['deletions']}
    walk = [p for p in raw_scaffold if p not in deleted]
    n = len(scaffold_sequence)
    if len(walk) != n:
        raise ValueError(f'Image scaffold has {len(walk)} bases after deletions, sequence has {n}.')
    raw_paths = [[tuple(p) for p in path] for path in graph['paths']['stap']]
    filtered = [[p for p in path if p not in deleted] for path in raw_paths]
    rows = [sequence_variants(s) for s in raw_staples]
    by_length = defaultdict(list)
    for row, variants in enumerate(rows):
        for sequence, variant in variants:
            by_length[len(sequence)].append((row,sequence,variant))
    complementary = scaffold_sequence.upper().translate(COMPLEMENT)
    doubled = complementary*2
    solutions = []
    for scaffold_reverse in (False,True):
        directed = list(reversed(walk)) if scaffold_reverse else walk
        index = {p:i for i,p in enumerate(directed)}
        templates = [[index.get(p) for p in path] for path in filtered]
        offsets = {0}
        for template in sorted(templates,key=lambda t:sum(i is not None for i in t),reverse=True)[:12]:
            for candidate in (template,template[::-1]):
                start,anchor = contiguous_anchor(candidate)
                if len(anchor)<8:
                    continue
                for _,sequence,_ in by_length[len(candidate)]:
                    query=sequence[start:start+len(anchor)]
                    if anchor[-1]<anchor[0]: query=query[::-1]
                    if len(set(query))<3: continue
                    pos=doubled.find(query)
                    while 0<=pos<n:
                        offsets.add((pos-min(anchor))%n);pos=doubled.find(query,pos+1)
        for offset in sorted(offsets):
            assignments=[]
            for path,template in enumerate(templates):
                matches=[]
                for reverse in (False,True):
                    chosen=template[::-1] if reverse else template
                    if sum(i is not None for i in chosen)<12: continue
                    predicted=''.join('?' if i is None else complementary[(i+offset)%n] for i in chosen)
                    for row,seq,variant in by_length[len(chosen)]:
                        if all(a=='?' or a==b for a,b in zip(predicted,seq)):
                            matches.append({'path':path,'staple_row':row,'reverse':reverse,'variant':variant,
                                            'paired_bases':sum(i is not None for i in chosen),
                                            'unknown_bases':sum(i is None for i in chosen)})
                # Avoid double-counting equivalent raw/core interpretations.
                unique={(m['staple_row'],m['reverse']):m for m in matches}
                if len(unique)==1: assignments.append(next(iter(unique.values())))
            counts=Counter(m['staple_row'] for m in assignments)
            assignments=[m for m in assignments if counts[m['staple_row']]==1]
            solutions.append({'scaffold_reverse':scaffold_reverse,'offset':offset,'assignments':assignments,
                              'matched_staples':len(assignments),
                              'paired_bases_verified':sum(m['paired_bases'] for m in assignments)})
    solutions.sort(key=lambda s:(-s['matched_staples'],-s['paired_bases_verified']))
    best=solutions[0]
    ties=[s for s in solutions if (s['matched_staples'],s['paired_bases_verified']) == (best['matched_staples'],best['paired_bases_verified'])]
    resolved=len(ties)==1 and best['matched_staples']==len(raw_paths)==len(rows)
    result={'method':'visible-grid-vector-graph-sequence-orientation-v1','source_sha256':graph['source_sha256'],
            'resolved':resolved,'best_ties':len(ties),'hypotheses_tested':len(solutions),
            'best':best,'alternatives':solutions[:8],'unknown_bases':sum(m['unknown_bases'] for m in best['assignments']),
            'graph':graph,'limitations':['Vector PDF only; visible uniform base ruler and numbered rows required.',
                                        'No inference of missing insertions, circular origins or molecular geometry.',
                                        'Sequence agreement at unknown partners does not establish their chemistry.']}
    if resolved:
        ordered={m['path']:m for m in best['assignments']}
        result['directed_paths']={'scaf':[raw_scaffold[::-1] if best['scaffold_reverse'] else raw_scaffold],
                                  'stap':[path[::-1] if ordered[i]['reverse'] else path for i,path in enumerate(raw_paths)]}
    return result


def extract_routing(data, scaffold_sequence, staples, page_number=0):
    return orient_with_sequences(recover_vector_graph(data,page_number),scaffold_sequence,staples)
