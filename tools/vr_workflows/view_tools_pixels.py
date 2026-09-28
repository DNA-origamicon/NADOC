"""Check actual tablet tile pixels in both eyes and the delivered mirror."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from tools.vr_motion.visual_checks import project, coverage


def check(directory, *, offscreen=False):
    directory=Path(directory);e=json.loads((directory/'evidence.json').read_text())
    items=e['state']['view_tools']['items']
    centers=np.array([i['center'] for i in items]);right=centers[1]-centers[0];down=centers[2]-centers[0]
    points=[(p+right*.25+down*.2+(1000 if offscreen else 0)).tolist() for p in centers]
    checks={}
    for name in ('left','right','mirror'):
        eye=next(v for v in e['eyes'] if v['eye']==(e['mirror']['eye'] if name=='mirror' else name))
        rgb=np.asarray(Image.open(directory/(name+'.png')).convert('RGB')).astype(int)
        mask=np.any(np.stack([np.max(abs(rgb-c),axis=2)<9 for c in ([36,49,70],[22,75,67])]),axis=0)
        projected=[project(p,eye) for p in points]
        if name=='mirror':
            x,y,w,h=e['mirror']['viewport_bottom_up']
            projected=[None if p is None else (x+p[0]*w/eye['width'],rgb.shape[0]-y-h+p[1]*h/eye['height']) for p in projected]
        checks[name]=coverage(mask,projected,radius=2 if name=='mirror' else 4)
    result={'passed':min(checks.values())>=.8,'coverage':checks}
    if not offscreen:(directory/'tablet-pixels.json').write_text(json.dumps(result,indent=2))
    return result
