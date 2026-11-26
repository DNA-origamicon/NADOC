"""Read visible DNA glyphs independently of damaged PDF Unicode mappings."""
from functools import lru_cache
import math
from statistics import median
from pathlib import Path
from PIL import Image
import numpy as np
import pymupdf



def _ink_mask(pix, color):
    pixels=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3)/255
    ink=np.linalg.norm(pixels-np.array(color),axis=2)<.14
    yy,xx=np.where(ink)
    return (np.asarray(Image.fromarray(ink[yy.min():yy.max()+1,xx.min():xx.max()+1]).resize((24,40),Image.Resampling.NEAREST),bool)
            if len(xx) else None)


@lru_cache(maxsize=1)
def _templates():
    result=[]
    with pymupdf.open() as doc:
        fonts = [('cour', None), ('helv', None), ('tiro', None)]
        for filename in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                         '/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf',
                         '/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf'):
            if Path(filename).is_file():fonts.append(('external'+str(len(fonts)),filename))
        for font, filename in fonts:
            for base in 'ACGT':
                page=doc.new_page(width=100,height=100)
                page.insert_text((15,80),base,fontsize=70,fontname=font,fontfile=filename)
                result.append((base,_ink_mask(page.get_pixmap(), (0,0,0))))
    return result


def extract_base_labels(page, calibration):
    scale=calibration['points_per_base']; origin=calibration['origin_x']
    centers={int(h):y for h,y in calibration['row_centers'].items()}
    ys=sorted(centers.values());pitch=median(b-a for a,b in zip(ys,ys[1:]))
    spans=[]; glyphs={}
    for span in page.get_texttrace():
        direction=tuple(round(v,4) for v in span['dir'])
        if direction not in ((1,0),(-1,0)) or not .5*scale <= span['size'] <= 2*scale:
            continue
        for char in span['chars']:
            _,glyph,_,bbox=char
            x=(bbox[0]+bbox[2])/2; y=(bbox[1]+bbox[3])/2
            h=min(centers,key=lambda h:abs(y-centers[h]))
            if abs(y-centers[h])>pitch*.45 or x<origin:continue
            key=(span['font'],glyph,direction)
            if key not in glyphs:
                zoom=min(40,70/span['size'])
                pix=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=pymupdf.Rect(bbox),colorspace=pymupdf.csRGB,alpha=False)
                mask=_ink_mask(pix,span['color'])
                scores={}
                if mask is not None:
                    if direction[0]<0:mask=mask[::-1,::-1]
                    for base,template in _templates():
                        score=np.count_nonzero(mask & template)/max(1,np.count_nonzero(mask | template))
                        scores[base]=max(scores.get(base,0),float(score))
                ranked=sorted(scores.items(),key=lambda x:-x[1])
                glyphs[key]=(ranked[0] if len(ranked)>1 and ranked[0][1]>.68 and ranked[0][1]-ranked[1][1]>.06 else (None,0))
            base,confidence=glyphs[key]
            spans.append({'helix':h,'bp':math.floor((x-origin)/scale+1e-4),
                          'direction':int(direction[0]),'base':base,'confidence':confidence})
    return spans
