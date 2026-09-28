"""Projected bond pixels; a controller or unrelated visible geometry cannot pass."""
import json
from pathlib import Path
from urllib.parse import unquote
import numpy as np
from PIL import Image
from tools.vr_motion.visual_checks import project, coverage


def preview(directory, *, offscreen=False):
    directory = Path(directory)
    evidence = json.loads((directory/'evidence.json').read_text())
    state = evidence['state']['ligation']
    a = np.array(state['ends'][state['source']]['world'])
    b = np.array(state['preview_end'])
    if offscreen:
        a += 1000; b += 1000
    points = [((1-t)*a+t*b).tolist() for t in np.linspace(.2,.8,7)]
    checks = {}
    for name in ('left', 'right', 'mirror'):
        eye = next(e for e in evidence['eyes'] if e['eye'] == (evidence['mirror']['eye'] if name=='mirror' else name))
        rgb = np.asarray(Image.open(directory/(name+'.png')).convert('RGB'))
        mask = ((rgb[:,:,1]>130)&(rgb[:,:,0]<120)&(rgb[:,:,2]<130) if state['target'] is not None else
                (rgb[:,:,1]>130)&(rgb[:,:,2]>130)&(rgb[:,:,0]<120))
        projected = [project(p,eye) for p in points]
        if name=='mirror':
            vx,vy,vw,vh=evidence['mirror']['viewport_bottom_up']
            projected=[None if p is None else (vx+p[0]*vw/eye['width'],rgb.shape[0]-vy-vh+p[1]*vh/eye['height']) for p in projected]
        checks[name]=coverage(mask,projected,radius=3 if name=='mirror' else 5)
    report={'passed':min(checks.values())>=.7,'coverage':checks}
    if not offscreen:(directory/'bond-pixels.json').write_text(json.dumps(report,indent=2))
    return report


def committed(directory, source_identity, target_identity):
    directory=Path(directory)
    objects=json.loads((directory/'objects.json').read_text())
    # This generated fixture deliberately uses unambiguous IDs without colons.
    keys={':'.join(unquote(v).split(':')[3:6]) for v in (source_identity,target_identity)}
    ids=set()
    for obj in objects:
        for encoded in obj['owner_tokens']:
            token=json.loads(unquote(encoded))
            if token[0]=='bond' and set(token[1:3])==keys:ids.add(obj['id'])
            if token[:2]==['crossover','forced_ligation']:ids.add(obj['id'])
    counts={name:int(np.isin(np.fromfile(directory/(name+'.ids.u32'),dtype=np.uint32),list(ids)).sum()) for name in ('left','right')}
    report={'passed':bool(ids) and min(counts.values())>=1,'bond_ids':sorted(ids),'pixels':counts}
    (directory/'saved-bond-pixels.json').write_text(json.dumps(report,indent=2))
    return report
