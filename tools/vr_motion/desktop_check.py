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


def viewer_window(live):
    pid=int(live.session.split('-')[0])
    tree=subprocess.check_output(['xwininfo','-root','-tree'],text=True,timeout=3)
    window=None
    for line in tree.splitlines():
        if 'WAITING FOR FIRST FRAME' not in line:continue
        identifier=line.strip().split()[0]
        prop=subprocess.check_output(['xprop','-id',identifier,'_NET_WM_PID'],text=True,timeout=3)
        if prop.strip().endswith('= '+str(pid)):window=identifier;break
    if not window:raise RuntimeError('current viewer client window not found on this X display')
    return window


def reveal_viewer(live):
    """Raise only the verified owned viewer's frame, without restarting anything."""
    import ctypes as c
    import ctypes.util
    import time
    window = int(viewer_window(live),16)
    x = c.CDLL(ctypes.util.find_library('X11'))
    x.XOpenDisplay.argtypes=[c.c_char_p];x.XOpenDisplay.restype=c.c_void_p
    x.XQueryTree.argtypes=[c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_ulong),c.POINTER(c.POINTER(c.c_ulong)),c.POINTER(c.c_uint)]
    x.XRaiseWindow.argtypes=[c.c_void_p,c.c_ulong]
    x.XSync.argtypes=[c.c_void_p,c.c_int];x.XCloseDisplay.argtypes=[c.c_void_p]
    x.XFree.argtypes=[c.c_void_p]
    display=x.XOpenDisplay(os.environ.get('DISPLAY',':1').encode())
    if not display:raise RuntimeError('cannot open viewer X display')
    try:
        for _ in range(16):
            root=c.c_ulong();parent=c.c_ulong();children=c.POINTER(c.c_ulong)();count=c.c_uint()
            if not x.XQueryTree(display,window,c.byref(root),c.byref(parent),c.byref(children),c.byref(count)):
                raise RuntimeError('viewer disappeared before reveal')
            if children:x.XFree(children)
            if parent.value in (0,root.value):break
            window=parent.value
        else:raise RuntimeError('unexpected viewer window ancestry')
        x.XRaiseWindow(display,window);x.XSync(display,0)
    finally:x.XCloseDisplay(display)
    time.sleep(.3)  # Desktop composition, outside all measured motion.


def run(socket, output, *, live=None, reveal=False):
    import numpy as np
    from PIL import Image, ImageGrab
    if live is None:
        live=LiveSession(Bridge(socket),physical=True)
    if reveal:reveal_viewer(live)
    window=viewer_window(live)
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
        revealed_owned_viewer=reveal,
        scope='Actual X11 desktop pixels versus submitted-eye mirror; not physical headset scanout')
    (output/'desktop-check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket');parser.add_argument('output',type=Path)
    args=parser.parse_args();result=run(args.socket,args.output)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
