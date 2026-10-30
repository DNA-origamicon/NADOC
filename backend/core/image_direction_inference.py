"""Image-only caDNAno direction hypotheses. No native-design inputs permitted.

Canonical renderer convention is verified in cadnano2 commit239ecc85:
virtualhelix.py:isDrawn5to3 and virtualhelixitem.py:isStrandOnTop.
Mirror/rotation and nonstandard coloring remain explicit hypotheses.
"""
from statistics import median


def track_hypotheses(evidence, axis=0):
    """Pair overlapping scaffold/staple strokes; retain both page orientations.

    Blue is only a scaffold-color hypothesis. Gray grid/dense paths are excluded
    from staple evidence. Votes are weighted by overlapping stroke length.
    """
    scaffold, staple = [], []
    for path in evidence['paths']:
        r,g,b = path['color'][:3]
        blue = abs(r)<.04 and abs(g-.4)<.04 and abs(b-.8)<.04
        if not blue and (path['flags'] or max(r,g,b)-min(r,g,b)<.03 and (r>.7 or r<.1)):
            continue
        for primitive in path['primitives']:
            if primitive['kind'] != 'line': continue
            a,z = primitive['points']
            if abs(a[1-axis]-z[1-axis]) > .02 or abs(a[axis]-z[axis]) < 2: continue
            segment = (min(a[axis],z[axis]),max(a[axis],z[axis]),(a[1-axis]+z[1-axis])/2,path['id'])
            (scaffold if blue else staple).append(segment)
    matches=[]
    for a,b,y,pid in scaffold:
        candidates=[]
        for c,d,z,qid in staple:
            overlap=min(b,d)-max(a,c)
            gap=abs(z-y)
            if overlap>=2 and gap>.03:
                candidates.append((gap,overlap,z,qid))
        if candidates:
            gap=min(x[0] for x in candidates)
            for dist,overlap,z,qid in candidates:
                if dist <= gap+.02:
                    matches.append({'track':y,'offset':z-y,'gap':dist,'weight':overlap,'scaffold_path':pid,'staple_path':qid})
    if not matches:
        return {'axis':axis,'tracks':[],'status':'no paired-track evidence'}
    # The smaller nearest-neighbor gap population avoids adjacent-helix matches.
    ordered=sorted(m['gap'] for m in matches)
    unit=median(ordered[:max(1,len(ordered)//2)])
    groups=[]
    for m in sorted(matches,key=lambda x:x['track']):
        if m['gap']>unit*1.3: continue
        if not groups or abs(m['track']-median(x['track'] for x in groups[-1]))>unit*.25:
            groups.append([])
        groups[-1].append(m)
    tracks=[]
    for group in groups:
        positive=sum(m['weight'] for m in group if m['offset']>0)
        negative=sum(m['weight'] for m in group if m['offset']<0)
        direction=1 if positive>0 and negative==0 else -1 if negative>0 and positive==0 else None
        tracks.append({'drawing_coordinate':median(m['track'] for m in group),
                       'direction_if_unmirrored_horizontal':direction if axis==0 else None,
                       'signed_track_offset':direction,'opposite_orientation_sign':-direction if direction else None,
                       'status':'consistent track-offset evidence' if direction else 'conflicting track-offset evidence',
                       'evidence':group})
    return {'axis':axis,'track_spacing_drawing_units':unit,'tracks':tracks,
            'status':'conditional on scaffold color and page orientation',
            'limitations':['No helix number inferred from row order.','No BP register inferred from pixel distances.',
                           'For vertical drawings both rotation senses remain hypotheses.','Canonical layout must be confirmed; forced crossovers need not follow lattice offsets.']}


def propagate_directions(nodes, opposite_pairs, anchors):
    """Solve explicitly observed antiparallel constraints, retaining reversal freedom.

    Edges must be classified antiparallel from image evidence, not assumed for
    every drawn crossing. Anchors are independently established image directions.
    """
    graph={n:[] for n in nodes}
    for a,b in opposite_pairs:
        if a not in graph or b not in graph: raise ValueError('Unknown track')
        graph[a].append(b);graph[b].append(a)
    if any(n not in graph or d not in (-1,1) for n,d in anchors.items()): raise ValueError('Invalid anchor')
    components=[];visited=set()
    for node in nodes:
        if node in visited:continue
        signs={node:1};queue=[node];conflicts=[]
        while queue:
            a=queue.pop();visited.add(a)
            for b in graph[a]:
                if b in signs and signs[b]!=-signs[a]: conflicts.append([a,b])
                elif b not in signs:signs[b]=-signs[a];queue.append(b)
        scales={anchors[n]*s for n,s in signs.items() if n in anchors}
        if len(scales)>1:conflicts.append('incompatible direction anchors')
        hypotheses=[] if conflicts else [{n:s*k for n,s in signs.items()} for k in (sorted(scales) if scales else [-1,1])]
        components.append({'nodes':list(signs),'hypotheses':hypotheses,'conflicts':conflicts,
                           'status':'inconsistent' if conflicts else 'anchored' if scales else 'global reversal unresolved'})
    return components


def crossover_corroboration(evidence, hypothesis):
    """Check isolated Bézier junction attachments against paired-track directions.

    Whole multi-curve paths require segmentation first and are deliberately left
    unresolved. No junction is inserted or moved to improve agreement.
    """
    tracks=hypothesis['tracks'];axis=hypothesis['axis']
    if not tracks:return {'junctions':[],'opposite':0,'conflicting':0}
    unit=hypothesis['track_spacing_drawing_units']
    centers=[(t['drawing_coordinate'],median(m['track']+m['offset'] for m in t['evidence'])) for t in tracks]
    junctions=[]
    for path in evidence['paths']:
        primitives=path['primitives']
        if path['closed'] or sum(p['kind']=='bezier' for p in primitives)!=1 or len(primitives)!=5:continue
        blue=all(abs(a-b)<.04 for a,b in zip(path['color'],[0,.4,.8]))
        endpoints=[primitives[0]['points'][0],primitives[-1]['points'][-1]]
        mapped=[]
        for point in endpoints:
            idx=min(range(len(centers)),key=lambda i:abs(centers[i][0 if blue else 1]-point[1-axis]))
            if abs(centers[idx][0 if blue else 1]-point[1-axis])>unit*.15:break
            mapped.append(idx)
        if len(mapped)!=2 or mapped[0]==mapped[1]:continue
        a,b=mapped;da,db=[tracks[i]['signed_track_offset'] for i in mapped]
        verdict='opposite' if da and db and da==-db else 'conflicting' if da and db else 'unresolved'
        junctions.append({'path':path['id'],'class_hypothesis':'scaffold' if blue else 'staple','tracks':[a,b],'verdict':verdict})
    return {'junctions':junctions,'opposite':sum(j['verdict']=='opposite' for j in junctions),'conflicting':sum(j['verdict']=='conflicting' for j in junctions)}
