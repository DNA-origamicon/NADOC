"""Check the actual X11 desktop client rectangle against a fresh native mirror.

Run after motion finishes (never on the timed input thread). Fails if the viewer
is covered, offscreen, missing or on another desktop. Does not raise windows.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from .session import LiveSession
from frontend.scrywrite.mcp_bridge import Bridge


def pixel_agreement(expected, actual):
    import numpy as np
    if expected.shape!=actual.shape:return {'passed':False,'reason':'desktop/window dimensions differ'}
    mask=expected.max(axis=2)>80
    y,x=np.nonzero(mask)
    if len(x)<100:return {'passed':False,'reason':'no visible UI to compare'}
    matches=np.zeros(len(x),dtype=bool)
    for dy in (-1,0,1):
        for dx in (-1,0,1):
            sample=actual[np.clip(y+dy,0,actual.shape[0]-1),np.clip(x+dx,0,actual.shape[1]-1)]
            matches|=(np.abs(sample.astype(float)-expected[y,x]).max(axis=1)<32)
    fraction=float(matches.mean())
    return {'passed':fraction>=.95,'visible_feature_pixels':len(x),'matching_fraction':fraction,
            'required_fraction':.95,'pixel_tolerance':32,'registration_tolerance_px':1}


def run(socket, output):
    import numpy as np
    from PIL import Image, ImageGrab
    live=LiveSession(Bridge(socket),physical=True)
    pid=int(live.session.split('-')[0])
    tree=subprocess.check_output(['xwininfo','-root','-tree'],text=True,timeout=3)
    window=None
    for line in tree.splitlines():
        if 'WAITING FOR FIRST FRAME' not in line:continue
        identifier=line.strip().split()[0]
        prop=subprocess.check_output(['xprop','-id',identifier,'_NET_WM_PID'],text=True,timeout=3)
        if prop.strip().endswith('= '+str(pid)):window=identifier;break
    if not window:raise RuntimeError('current viewer client window not found on this X display')
    info=subprocess.check_output(['xwininfo','-id',window],text=True,timeout=3)
    def field(name):
        return int(re.search(re.escape(name)+r':\s*(-?\d+)',info).group(1))
    x,y,w,h=[field(k) for k in ('Absolute upper-left X','Absolute upper-left Y','Width','Height')]
    output.mkdir(parents=True,exist_ok=False)
    evidence,_=live.capture_to(output/'capture',files=('left.png','right.png','mirror.png','evidence.json'),discard_source=True)
    desktop=ImageGrab.grab(xdisplay=os.environ.get('DISPLAY',':1'))
    if x<0 or y<0 or x+w>desktop.width or y+h>desktop.height:
        result={'passed':False,'reason':'viewer partly outside desktop'}
    else:
        crop=desktop.crop((x,y,x+w,y+h))
        result=pixel_agreement(np.asarray(Image.open(output/'capture/mirror.png').convert('RGB')),np.asarray(crop.convert('RGB')))
        # Never retain other applications exposed by an obscured/failed window.
        if result['passed']:crop.save(output/'desktop-client.png')
    result.update(session=live.session,frame=evidence['state']['frame'],window=window,rectangle=[x,y,w,h],
        scope='Actual X11 desktop pixels versus submitted-eye mirror; not physical headset scanout')
    (output/'desktop-check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket');parser.add_argument('output',type=Path)
    args=parser.parse_args();result=run(args.socket,args.output)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
