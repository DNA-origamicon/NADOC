"""Deterministic visible-page registration and conservative color skeleton tracing.

Coordinates are PDF points and rendered pixels, never helix/base identities.
Occlusion is resolved by the PDF renderer, not by stacking extracted assets.
"""
import colorsys
import numpy as np
import pymupdf
from skimage.morphology import skeletonize


def trace_mask(mask, *, max_edges=20000):
    skeleton = skeletonize(mask)
    nodes = set(zip(*np.nonzero(skeleton)))
    def neighbors(p):
        y, x = p
        return sorted((y+dy, x+dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dy or dx) and (y+dy, x+dx) in nodes and
                      not (dy and dx and ((y+dy, x) in nodes or (y, x+dx) in nodes)))
    adjacency = {p: neighbors(p) for p in nodes}
    endpoints = sorted(p for p in nodes if len(adjacency[p]) != 2)
    used, paths = set(), []
    edge = lambda a,b: tuple(sorted((a,b)))
    # Start at junctions/ends first; remaining degree-two components are cycles.
    for start in endpoints + sorted(nodes - set(endpoints)):
        for nxt in adjacency[start]:
            if edge(start,nxt) in used:continue
            if len(paths) >= max_edges:
                return paths, [(p, len(adjacency[p])) for p in endpoints], True
            path = [start, nxt]; used.add(edge(start,nxt))
            previous, current = start, nxt
            while len(adjacency[current]) == 2 and current != start:
                after = next(p for p in adjacency[current] if p != previous)
                if edge(current,after) in used:break
                used.add(edge(current,after)); path.append(after)
                previous,current = current,after
            # Keep all endpoints and corners; straight interior pixels add no evidence.
            compact = [path[0]]
            for i in range(1,len(path)-1):
                a,b,c = path[i-1:i+2]
                if (b[0]-a[0],b[1]-a[1]) != (c[0]-b[0],c[1]-b[1]):compact.append(b)
            compact.append(path[-1])
            paths.append([[int(x),int(y)] for y,x in compact])
    return paths, [(p, len(adjacency[p])) for p in endpoints], False


def register_and_trace(page, *, max_dimension=4096):
    placements = page.get_image_info(xrefs=True)
    if not placements:return None
    # Retain native raster detail where the resource bound allows it. A fixed
    # whole-page thumbnail scale loses narrow strokes before tracing even begins.
    native_scale = max(max(p['width']/max(.01,p['bbox'][2]-p['bbox'][0]),
                           p['height']/max(.01,p['bbox'][3]-p['bbox'][1])) for p in placements)
    scale = min(max(1., native_scale), max_dimension/max(page.rect.width,page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale), alpha=False, colorspace=pymupdf.csRGB)
    rgb = np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    # Analyze only raster placement regions, but render their final visible composition.
    visible = np.zeros((pix.height,pix.width),dtype=bool)
    for placement in placements:
        box = (pymupdf.Rect(placement['bbox']) * page.rotation_matrix) & page.rect
        x0,y0,x1,y1 = box
        visible[max(0,int(y0*scale)-pix.y):min(pix.height,int(np.ceil(y1*scale))-pix.y),
                max(0,int(x0*scale)-pix.x):min(pix.width,int(np.ceil(x1*scale))-pix.x)] = True
    high, low = rgb.max(axis=2),rgb.min(axis=2)
    chromatic = visible & ((high.astype(int)-low)>55) & (low<200)
    # Nearest fixed hue anchor avoids splitting red at the hue wraparound.
    anchors = np.array([colorsys.hsv_to_rgb(i/12,1,1) for i in range(12)])
    normalized = (rgb.astype(float)-low[:,:,None])/np.maximum(1,high.astype(float)-low)[:,:,None]
    labels = np.full(visible.shape,-1,dtype=np.int8)
    labels[chromatic] = np.argmin(((normalized[chromatic,None,:]-anchors[None,:,:])**2).sum(axis=2),axis=1)
    def pdf_point(x, y):
        point = pymupdf.Point((x+pix.x)/scale, (y+pix.y)/scale) * page.derotation_matrix
        return [point.x, point.y]
    layers=[]; truncated=False
    for index in range(12):
        mask = labels==index
        if not mask.any():continue
        paths, nodes, limit = trace_mask(mask)
        truncated |= limit
        layers.append({'hue_bin':index,'color_rgb':np.median(rgb[mask],axis=0).astype(int).tolist(),
                       'paths_pdf':[[pdf_point(x,y) for x,y in path] for path in paths],
                       'junctions_pdf':[pdf_point(x,y) for (y,x),degree in nodes if degree>2],
                       'path_count':len(paths), 'truncated':limit})
    from backend.core.publication_panel_registration import register_panels
    from backend.core.publication_staple_tracing import classify_and_trace_page
    panel_registration=register_panels(page)
    classified=classify_and_trace_page(page,panel_registration)
    return {'classified_tracing':classified,'panel_registration':panel_registration,'method':'visible-pdf-color-skeleton-v1','status':'pixel_traces_unregistered_to_bases',
            'registration':{'pixels_per_pdf_point':scale,'pixel_origin':[pix.x,pix.y],
                            'width':pix.width,'height':pix.height,'page_rotation':page.rotation,
                            'native_pixels_per_pdf_point':native_scale,
                            'native_resolution_retained':scale >= native_scale - 1e-6},
            'placements':[{'bbox':list(p['bbox']),'transform':list(p['transform']),'xref':p.get('xref'),'width':p['width'],'height':p['height']} for p in placements],
            'layers':layers,'path_count':sum(l['path_count'] for l in layers),'truncated':truncated,
            'unresolved':['Raster helix labels and absolute base register require calibration.',
                          'Distinct-color straight crossings may be resolved; other junctions and strand polarity remain ambiguous.',
                          'Dark neutral strokes are screened against the local grid; weak endpoint markers and uncertain attachments remain unresolved.',
                          'Small ink gaps are not strand breaks; sequence-supported continuity candidates require image-register resolution before native routing.']}
