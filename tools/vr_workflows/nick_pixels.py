"""Independent projected scissors blades and impending bond glow checks."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project, coverage


def check(directory,offscreen=False):
    directory=Path(directory);e=json.loads((directory/'evidence.json').read_text());s=e['state'];l=s['ligation']
    h=s['hands'][1];q=h['orientation_xyzw'];center=np.array(h['position'])+rotate(q,[0,0,-.12])
    angle=l['scissor_angles'][1]
    blades=[center+rotate(q,[side*np.sin(angle)*t,np.cos(angle)*t-.022,0]) for side in (-1,1) for t in (.025,.04,.052)]
    bond=l['bonds'][l['nick_hover'][1]]
    points={'scissors':blades,'glow':[(1-t)*np.array(bond['a'])+t*np.array(bond['b']) for t in (.25,.5,.75)]}
    result={}
    for name in ('left','right','mirror'):
        eye=next(x for x in e['eyes'] if x['eye']==(e['mirror']['eye'] if name=='mirror' else name))
        rgb=np.array(Image.open(directory/(name+'.png')).convert('RGB'))
        masks={'scissors':(rgb[:,:,1]>150)&(rgb[:,:,2]>170)&(rgb[:,:,0]>70),
               'glow':(rgb[:,:,0]>160)&(rgb[:,:,1]>80)&(rgb[:,:,2]<180)}
        for kind,ps in points.items():
            projected=[project((p+1000 if offscreen else p).tolist(),eye) for p in ps]
            if name=='mirror':
                vx,vy,vw,vh=e['mirror']['viewport_bottom_up']
                projected=[None if p is None else (vx+p[0]*vw/eye['width'],rgb.shape[0]-vy-vh+p[1]*vh/eye['height']) for p in projected]
            result[name+'_'+kind]=coverage(masks[kind],projected,radius=3 if name=='mirror' else 5)
    report={'passed':min(result.values())>=.66,'coverage':result,'angle':angle}
    if not offscreen:(directory/'nick-pixels.json').write_text(json.dumps(report,indent=2))
    return report
