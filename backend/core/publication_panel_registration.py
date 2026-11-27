"""Grid-normalized image overlap hypotheses using normalized cross-correlation.

Only source image pixels are consulted. Matches align image panels, not strands.
Repeated grids can produce aliases; retain competing peaks and reject weak gaps.
"""
import numpy as np
import pymupdf
from scipy.ndimage import binary_closing, find_objects, label
from scipy.signal import find_peaks
from skimage.feature import match_template
from skimage.transform import rescale


def panel_grid(rgb):
    """Recognize upright caDNAno orange row markers and nearby empty grid."""
    rgb=np.asarray(rgb,dtype=float);h,w,_=rgb.shape
    orange=(rgb[:,:,0]>180)&(rgb[:,:,1]>90)&(rgb[:,:,1]<230)&(rgb[:,:,2]<200)&(rgb[:,:,0]-rgb[:,:,2]>45)
    profile=orange[:,:round(w*.055)].sum(axis=1)
    components,_=label(binary_closing(profile>3,structure=np.ones(3)))
    rows=np.array([round((s[0].start+s[0].stop-1)/2) for s in find_objects(components) if s[0].stop-s[0].start>=5])
    if len(rows)<4:return None
    pitch=float(np.median(np.diff(rows)))
    if np.std(np.diff(rows))/pitch>.15:return None
    xs=np.arange(round(w*.05),round(w*.28))
    ys=np.concatenate([np.arange(max(0,int(y)-5),min(h,int(y)+6)) for y in rows])
    profile=np.median(rgb.mean(axis=2)[ys[:,None],xs],axis=0)
    peaks,_=find_peaks(-profile,prominence=8,distance=2)
    columns=xs[peaks]
    if len(columns)<10:return None
    median=np.median(np.diff(columns));pitches=np.arange(median*.8,median*1.2,.001)
    spectrum=np.exp(2j*np.pi*columns[None,:]/pitches[:,None]).mean(axis=1)
    best=int(np.argmax(abs(spectrum)));grid_pitch=float(pitches[best]);coherence=float(abs(spectrum[best]))
    if coherence<.7:return None
    return {'row_centers':rows.tolist(),'row_pitch':pitch,'grid_pitch':grid_pitch,'periodicity_coherence':coherence,
            'status':'relative_grid_only','limitation':'No helix identities, absolute base origin or strand connectivity assigned.'}


def match_panel_strip(reference,moving,*,scale,strip_height,crop_left,peak_count=5):
    a=np.asarray(reference,dtype=float)/255.;b=np.asarray(moving,dtype=float)/255.
    if not .25<=scale<=4 or not 1<=strip_height<=b.shape[0] or not 0<=crop_left<b.shape[1]:raise ValueError('Invalid panel registration bounds.')
    strip=rescale(b[:strip_height,crop_left:],scale,channel_axis=2,anti_aliasing=True)
    if strip.shape[0]>a.shape[0] or strip.shape[1]>a.shape[1]:return {'status':'strip_does_not_fit','peaks':[]}
    scores=match_template(a,strip)[:,:,0];peaks=[]
    for _ in range(peak_count):
        y,x=np.unravel_index(np.argmax(scores),scores.shape);score=float(scores[y,x])
        if score < -1:break
        peaks.append({'correlation':score,'translation_xy':[float(x-crop_left*scale),float(y)],'scale':scale})
        scores[max(0,y-4):y+5,max(0,x-4):x+5]=-2
    margin=peaks[0]['correlation']-peaks[1]['correlation'] if len(peaks)>1 else 0.
    strong=peaks[0]['correlation']>=.8 and margin>=.15
    return {'status':'supported_image_overlap' if strong else 'ambiguous_or_no_overlap', 'peaks':peaks,'peak_margin':margin,
            'native_routing_resolved':False,'limitation':'Similarity and margin thresholds are screening heuristics, not calibrated probabilities.'}


def register_panels(page):
    images={};panels=[];omitted=[];seen=set()
    for info in page.get_image_info(xrefs=True):
        xref=info.get('xref')
        if not xref or xref in seen:continue
        seen.add(xref)
        if info['width']*info['height']>4_000_000:
            omitted.append({'xref':xref,'reason':'native_asset_pixel_budget'});continue
        # Decode through the PDF engine: some valid PDF image streams are not
        # independently decodable by Pillow (e.g. nonstandard JPEG wrappers).
        try:
            pix=pymupdf.Pixmap(page.parent,xref)
            if pix.colorspace is None:
                omitted.append({'xref':xref,'reason':'image_mask_without_color'});continue
            if pix.colorspace.n!=3:pix=pymupdf.Pixmap(pymupdf.csRGB,pix)
            pixels=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
            rgb=pixels[:,:,:3]
            if pix.alpha:
                rgb=np.minimum(255,rgb.astype(float)+(255-pixels[:,:,3:4])).astype(np.uint8)
        except (RuntimeError,ValueError) as exc:
            omitted.append({'xref':xref,'reason':'asset_decode_failed','detail':str(exc)});continue
        grid=panel_grid(rgb)
        if grid:
            if len(panels)>=6:
                omitted.append({'xref':xref,'reason':'panel_count_budget'});continue
            images[xref]=rgb;panels.append({'xref':xref,'width':rgb.shape[1],'height':rgb.shape[0],**grid})
    comparisons=[]
    for a in panels:
        for b in panels:
            if a is b:continue
            ratio=a['grid_pitch']/b['grid_pitch']
            if not .25<=ratio<=4:
                comparisons.append({'reference_xref':a['xref'],'moving_xref':b['xref'],
                                    'status':'outside_scale_search_bound','peaks':[]});continue
            result=match_panel_strip(images[a['xref']],images[b['xref']],scale=ratio,
                strip_height=round(b['row_centers'][0]+b['row_pitch']/4),crop_left=round(b['width']*.08))
            comparisons.append({'reference_xref':a['xref'],'moving_xref':b['xref'],**result})
    return {'method':'grid-normalized-ncc-v1','panels':panels,'comparisons':comparisons,'omitted':omitted,
            'limitation':'Upright orange-label panels only. Asset overlaps do not authorize joining molecular endpoints.'}
