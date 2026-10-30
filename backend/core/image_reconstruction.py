"""Stage-two image evidence and reference audits, with no guessed connectivity.

PDF path order is NOT DNA polarity. Coordinates remain drawing coordinates.
Reference files are comparison inputs and never fill missing image evidence.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math


def extract_page_evidence(page):
    """Keep independent line/curve primitives, including fragmented and rotated paths.

    Unlike the first-stage detector this does not mistake every grid line for a
    crossover. It preserves candidates for calibrated tracing, not asserted bonds.
    """
    paths = []
    for index, path in enumerate(page.get_drawings()):
        if path.get('color') is None or path.get('fill') is not None:
            continue
        primitives = []
        for item in path['items']:
            if item[0] in ('l', 'c'):
                primitives.append({'kind': 'line' if item[0] == 'l' else 'bezier',
                                   'points': [[float(p.x), float(p.y)] for p in item[1:]]})
        if primitives:
            paths.append({'id': index, 'color': list(path['color']), 'width': path['width'],
                          'closed': bool(path.get('closePath')), 'primitives': primitives,
                          'flags': ['dense path: grid/text candidate'] if len(primitives) > 400 else []})
    images = []
    for item in page.get_image_info(hashes=True):
        images.append({'bounds': list(item['bbox']), 'width': item['width'], 'height': item['height'],
                       'digest': item['digest'].hex()})
    return {'schema_version': 1, 'coordinate_system': 'PDF page points; no molecular distances',
            'page_bounds': list(page.rect), 'paths': paths, 'raster_images': images,
            'status': 'uncalibrated evidence', 'missing_for_cadnano': [
                'reviewed figure crop and row-to-helix/lattice map',
                'piecewise bp anchors (including stretched intervals)',
                'strand class and directed 5-prime-to-3-prime walks',
                'confirmed nicks, omitted crossover branches and path joins',
                'insertion/deletion and overhang annotations'],
            'limitations': ['PDF path boundaries and order do not establish strand ends or polarity.',
                            'Raster resolution is recorded; no upscaled pixels are treated as recovered bases.']}


def calibrated_index(value, anchors):
    """Piecewise interpolation only within supplied anchors; never extrapolate.

    Anchors may run either direction (rotated/mirrored drawing). Return a float
    so the caller must explicitly resolve sub-base offsets rather than round them.
    """
    if len(anchors) < 2:
        raise ValueError('At least two bp anchors are required')
    ordered = sorted((float(x), float(bp)) for x, bp in anchors)
    if not all(math.isfinite(x) and math.isfinite(bp) for x, bp in ordered):
        raise ValueError('Anchors must be finite')
    dx = [b[0] - a[0] for a,b in zip(ordered, ordered[1:])]
    db = [b[1] - a[1] for a,b in zip(ordered, ordered[1:])]
    if min(dx) <= 0 or not (all(v > 0 for v in db) or all(v < 0 for v in db)):
        raise ValueError('Anchors must be strictly monotonic')
    if not math.isfinite(value) or not ordered[0][0] <= value <= ordered[-1][0]:
        raise ValueError('Outside calibrated interval; add an anchor')
    for (x0,b0),(x1,b1) in zip(ordered, ordered[1:]):
        if x0 <= value <= x1:
            return b0 + (value-x0)/(x1-x0)*(b1-b0)
    raise ValueError('No calibrated interval')


def cadnano_summary(data):
    """Audit the provided file; do not promote it to publication ground truth."""
    helices = data.get('vstrands', [])
    lookup = {v['num']: v for v in helices}
    if len(lookup) != len(helices):
        raise ValueError('Duplicate helix numbers')
    counts = Counter()
    crossovers, ends, problems, sites, indels = [], [], [], [], []
    for v in helices:
        active = False
        for kind in ('scaf', 'stap'):
            for bp, neighbors in enumerate(v[kind]):
                if neighbors == [-1]*4: continue
                active = True
                counts[kind + '_occupied_sites'] += 1
                sites.append([kind, v['num'], bp])
                delta = sum(v.get(key, [])[bp] if bp < len(v.get(key, [])) else 0 for key in ('loop','skip'))
                counts[kind + '_nucleotides'] += 1 + delta
                if delta:
                    indels.append([kind, v['num'], bp, delta])
                for side, start, other in [('previous',0,2), ('next',2,0)]:
                    h, idx = neighbors[start:start+2]
                    if h == -1:
                        ends.append([kind,v['num'],bp,side])
                        if idx != -1: problems.append([kind,v['num'],bp,'partial-null neighbor'])
                        continue
                    target = lookup.get(h, {}).get(kind, [])
                    if idx < 0 or idx >= len(target) or target[idx][other:other+2] != [v['num'],bp]:
                        problems.append([kind,v['num'],bp,'nonreciprocal or invalid neighbor',h,idx])
                    if side == 'next' and h != v['num']:
                        crossovers.append([kind,v['num'],bp,h,idx])
        counts['active_helices'] += active
    return {'counts': dict(counts), 'crossovers': crossovers, 'termini': ends,
            'sites': sites, 'indels': indels, 'connectivity_problems': problems, 'reference_is_publication_ground_truth': False}


def compare_cadnano(observed, reference):
    """Exact address comparison after an explicitly supplied mapping; no fitting."""
    a,b = cadnano_summary(observed), cadnano_summary(reference)
    sets = lambda report, key: set(map(tuple, report[key]))
    result = {'counts_observed': a['counts'], 'counts_reference': b['counts'],
              'registration': 'caller-supplied helix IDs and bp origin; no automatic relabelling'}
    for key in ('crossovers','termini','sites','indels'):
        aa,bb = sets(a,key),sets(b,key)
        result[key] = {'shared': len(aa & bb), 'observed_only': sorted(aa-bb), 'reference_only': sorted(bb-aa)}
    result['observed_connectivity_problems'] = a['connectivity_problems']
    result['reference_connectivity_problems'] = b['connectivity_problems']
    return result


def evidence_digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_reviewed_routes(review):
    """Compile explicitly reviewed image walks to a caDNAno v2 draft.

    This accepts directed nucleotide addresses, NOT PDF path order. All uncertain
    decisions are supplied by the reviewer. No reference connectivity is copied.
    A strand's sites are listed in 5-prime-to-3-prime order. Insertions/deletions
    are explicit caDNAno site annotations, not extra spatial drawing distance.
    """
    for flag in ('directions_reviewed', 'termini_reviewed', 'indels_reviewed'):
        if review.get(flag) is not True:
            raise ValueError(f'{flag} must be explicitly confirmed')
    if review.get('registration_source') not in ('image-reviewed', 'reference-assisted'):
        raise ValueError('Declare image-reviewed or reference-assisted registration')
    if not review.get('source_sha256') or not review.get('evidence_ids'):
        raise ValueError('Source hash and traced evidence IDs are required')
    lattice = review.get('lattice')
    if lattice not in ('honeycomb', 'square'):
        raise ValueError('Explicit lattice is required')
    period = 21 if lattice == 'honeycomb' else 32
    helices = review.get('helices', [])
    routes = review.get('routes', [])
    if not helices or not routes:
        raise ValueError('Reviewed helices and directed routes are required')
    numbers = [h['num'] for h in helices]
    if any(type(n) is not int or n < 0 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError('Helix numbers must be distinct nonnegative integers')
    if len({(h['row'],h['col']) for h in helices}) != len(helices):
        raise ValueError('Duplicate lattice cell')
    sites = [site for route in routes for site in route['sites']]
    if any(len(s) != 2 or type(s[0]) is not int or s[0] not in numbers or type(s[1]) is not int or s[1] < 0 for s in sites):
        raise ValueError('Every site requires a known helix and nonnegative integer bp')
    if not sites:
        raise ValueError('No reviewed sites')
    width = ((max(s[1] for s in sites) + 1 + period - 1) // period) * period
    by_num = {h['num']:dict(num=h['num'], row=h['row'], col=h['col'],
        scaf=[[-1]*4 for _ in range(width)], stap=[[-1]*4 for _ in range(width)],
        loop=[0]*width, skip=[0]*width, stap_colors=[]) for h in helices}
    occupied = set()
    for route in routes:
        kind = route['kind']
        if kind not in ('scaf','stap'):
            raise ValueError('Route class must be scaf or stap')
        walk = route['sites']
        if len(walk) < 2 or (route.get('circular') and len(walk) < 3):
            raise ValueError('Isolated one-base strands cannot be represented by this compiler')
        for i,(h,bp) in enumerate(walk):
            key = (kind,h,bp)
            if key in occupied:
                raise ValueError('Overlapping routes; resolve path joins/nicks first')
            occupied.add(key)
            prev = walk[i-1] if i or route.get('circular') else [-1,-1]
            nxt = walk[(i+1)%len(walk)] if i+1 < len(walk) or route.get('circular') else [-1,-1]
            for neighbor in (prev,nxt):
                if neighbor[0] == h and abs(neighbor[1]-bp) != 1:
                    raise ValueError('Same-helix gaps require explicit site walks, including skip annotations')
            by_num[h][kind][bp] = list(prev)+list(nxt)
        if kind == 'stap' and 'color' in route:
            by_num[walk[0][0]]['stap_colors'].append([walk[0][1],int(route['color'])])
    annotated = set()
    for indel in review.get('indels', []):
        h,bp,delta = indel['helix'],indel['bp'],indel['delta']
        if h not in by_num or type(bp) is not int or not 0 <= bp < width or type(delta) is not int or delta < -1 or delta == 0:
            raise ValueError('Invalid insertion/deletion annotation')
        if (h,bp) in annotated or not any((kind,h,bp) in occupied for kind in ('scaf','stap')):
            raise ValueError('Duplicate or unoccupied insertion/deletion annotation')
        annotated.add((h,bp))
        by_num[h]['skip' if delta == -1 else 'loop'][bp] = delta
    draft = {'name':review.get('name','Image reconstruction draft'), 'vstrands':list(by_num.values())}
    audit = cadnano_summary(draft)
    if audit['connectivity_problems']:
        raise ValueError('Compiled connectivity is not reciprocal')
    return {'cadnano':draft, 'provenance':{k:review[k] for k in ('source_sha256','evidence_ids','registration_source')},
            'status':'reviewed-route draft; publication equivalence and geometry not established', 'audit':audit}


def expand_reviewed_trace(vertices, anchors, *, order):
    """Turn directed, row-identified image landmarks into exact site walks.

    Each vertex supplies helix and drawing-axis coordinate x; per-helix anchors
    map x to bp. Curve endpoints on different helices create only the observed
    branch. Bézier control points must not be included. No global pixel scale,
    lattice repeat, branch completion, or rounding is inferred.
    """
    if order != '5prime-to-3prime':
        raise ValueError('Explicit 5prime-to-3prime trace order is required')
    sites = []
    for vertex in vertices:
        h = vertex['helix']
        value = calibrated_index(vertex['x'], anchors[str(h)])
        bp = round(value)
        if abs(value - bp) > 1e-6:
            raise ValueError('Landmark does not map to an integer bp; review its calibration')
        if sites and sites[-1][0] == h:
            previous = sites[-1][1]
            if previous == bp: continue
            step = 1 if bp > previous else -1
            sites.extend([[h, b] for b in range(previous + step, bp + step, step)])
        else:
            sites.append([h,bp])
    return sites
