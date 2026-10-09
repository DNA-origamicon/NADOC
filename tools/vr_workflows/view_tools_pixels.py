"""Check actual tablet tile pixels in both eyes and the delivered mirror."""
import json
import re
from pathlib import Path
import numpy as np
from PIL import Image
from tools.vr_motion.visual_checks import project, coverage


def active_icon_colors(keys):
    # Glyphs using currentColor inherit the desktop button's actual active tint.
    # Keep the UI stylesheet authoritative (not a generic bright-color mask).
    html=(Path(__file__).resolve().parents[2]/'frontend/index.html').read_text()
    colors=re.findall(r'\.vt-btn\.active\[data-vt="([^"]+)"\]\s*\{\s*color:\s*#([0-9a-fA-F]{6})',html)
    return [[int(rgb[i:i+2],16) for i in (0,2,4)] for key,rgb in colors if key in keys]


def check(directory, *, offscreen=False):
    directory=Path(directory);e=json.loads((directory/'evidence.json').read_text())
    items=e['state']['view_tools']['items']
    centers=np.array([i['center'] for i in items]);right=centers[1]-centers[0];down=centers[2]-centers[0]
    points=[(p-right*(130/376)-down*(14/112)+(1000 if offscreen else 0)).tolist() for p in centers]
    checks={}
    for name in ('left','right','mirror'):
        eye=next(v for v in e['eyes'] if v['eye']==(e['mirror']['eye'] if name=='mirror' else name))
        rgb=np.asarray(Image.open(directory/(name+'.png')).convert('RGB')).astype(int)
        # With barely visible fills, require the desktop glyphs themselves.
        # Neutral light strokes and explicit heatmap/loop-skip RGB values count;
        # the white veil and cyan floor cannot satisfy this mask.
        mask=(rgb.min(axis=2)>100)&(np.ptp(rgb,axis=2)<80)
        for color in [[59,130,246],[168,85,247],[239,68,68],[255,136,0],[255,34,34],
                      *active_icon_colors({item['key'] for item in items if item['active']})]:
            mask |= np.max(abs(rgb-color),axis=2)<15
        projected=[project(p,eye) for p in points]
        if name=='mirror':
            x,y,w,h=e['mirror']['viewport_bottom_up']
            projected=[None if p is None else (x+p[0]*w/eye['width'],rgb.shape[0]-y-h+p[1]*h/eye['height']) for p in projected]
        checks[name]=coverage(mask,projected,radius=5 if name=='mirror' else 12)
    result={'passed':min(checks.values())>=.8,'coverage':checks}
    if not offscreen:(directory/'tablet-pixels.json').write_text(json.dumps(result,indent=2))
    return result
