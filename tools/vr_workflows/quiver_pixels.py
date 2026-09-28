"""Visible scissors versus restored sphere at the gesture's return pose."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project, coverage


def check(directory,offscreen=False):
    directory=Path(directory);e=json.loads((directory/'evidence.json').read_text());s=e['state'];h=s['hands'][1]
    q=h['orientation_xyzw'];center=np.array(h['position'])+rotate(q,[0,0,-.12])
    equipped=s['ligation']['nick_active']
    if equipped:
        points=[center+rotate(q,[side*np.sin(.65)*t,np.cos(.65)*t-.022,0]) for side in (-1,1) for t in (.025,.04,.052)]
    else:
        # Default selection radius is retained throughout this fixture. Spheres
        # use world-axis circles, unlike the controller-oriented scissors.
        points=[center+.025*np.array([np.cos(t),np.sin(t),0]) for t in np.linspace(0,2*np.pi,8,endpoint=False)]
    results={}
    for name in ('left','right','mirror'):
        eye=next(x for x in e['eyes'] if x['eye']==(e['mirror']['eye'] if name=='mirror' else name))
        rgb=np.array(Image.open(directory/(name+'.png')).convert('RGB'))
        mask=((rgb[:,:,1]>150)&(rgb[:,:,2]>170)&(rgb[:,:,0]>70) if equipped else
              (rgb[:,:,0]>100)&(rgb[:,:,0]>rgb[:,:,1]*1.3)&(rgb[:,:,2]<100))
        pixels=[project((p+1000 if offscreen else p).tolist(),eye) for p in points]
        if name=='mirror':
            vx,vy,vw,vh=e['mirror']['viewport_bottom_up']
            pixels=[None if p is None else (vx+p[0]*vw/eye['width'],rgb.shape[0]-vy-vh+p[1]*vh/eye['height']) for p in pixels]
        results[name]=coverage(mask,pixels,radius=3 if name=='mirror' else 5)
    report={'passed':min(results.values())>=.66,'equipped':equipped,'coverage':results}
    if not offscreen:(directory/'quiver-pixels.json').write_text(json.dumps(report,indent=2))
    return report
