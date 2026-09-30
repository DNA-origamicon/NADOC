"""Check the actual X11 desktop client rectangle against a fresh native mirror.

Run after motion finishes (never on the timed input thread). Fails if the viewer
is covered, offscreen, missing or on another desktop. Optional reveal raises only
the verified viewer. Desktop samples overlap capture encoding to avoid comparing
a saved eye with a later moving-head frame; XR rendering is never paused.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading
import time
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


def reveal_viewer(live, *, lower=False):
    """Stack only the verified owned viewer; lower exposes real desktop content."""
    import ctypes as c
    import ctypes.util
    import time
    window = int(viewer_window(live),16)
    client = window
    x = c.CDLL(ctypes.util.find_library('X11'))
    x.XOpenDisplay.argtypes=[c.c_char_p];x.XOpenDisplay.restype=c.c_void_p
    x.XQueryTree.argtypes=[c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_ulong),c.POINTER(c.POINTER(c.c_ulong)),c.POINTER(c.c_uint)]
    x.XRaiseWindow.argtypes=[c.c_void_p,c.c_ulong]
    x.XIconifyWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_int]
    x.XDefaultScreen.argtypes=[c.c_void_p];x.XDefaultScreen.restype=c.c_int
    x.XMapRaised.argtypes=[c.c_void_p,c.c_ulong]
    x.XInternAtom.argtypes=[c.c_void_p,c.c_char_p,c.c_int];x.XInternAtom.restype=c.c_ulong
    class ClientData(c.Union):
        _fields_=[('b',c.c_char*20),('s',c.c_short*10),('l',c.c_long*5)]
    class ClientMessage(c.Structure):
        _fields_=[('type',c.c_int),('serial',c.c_ulong),('send_event',c.c_int),
                  ('display',c.c_void_p),('window',c.c_ulong),('message_type',c.c_ulong),
                  ('format',c.c_int),('data',ClientData)]
    class Event(c.Union):
        _fields_=[('client',ClientMessage),('pad',c.c_long*24)]
    x.XSendEvent.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_long,c.POINTER(Event)]
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
        if lower:
            x.XIconifyWindow(display,client,x.XDefaultScreen(display))
        else:
            x.XMapRaised(display,client)
            # Ask the window manager to activate/unminimize this owned client;
            # raising its decoration alone can leave another app above it.
            event=Event();event.client.type=33;event.client.send_event=1
            event.client.display=display;event.client.window=client
            event.client.message_type=x.XInternAtom(display,b'_NET_ACTIVE_WINDOW',False)
            event.client.format=32;event.client.data.l[0]=2
            x.XSendEvent(display,root.value,False,(1<<20)|(1<<19),c.byref(event))
            x.XRaiseWindow(display,window)
        x.XSync(display,0)
    finally:x.XCloseDisplay(display)
    time.sleep(.3)  # Desktop composition, outside all measured motion.


def sample_during_capture(capture, grab, *, interval=.02, capacity=32):
    """Bound memory and retain only samples overlapping this capture request.

    Native PNG encoding happens after mirror presentation. Sampling concurrently
    observes that frame while it is displayed, before capture_to returns. Samples
    remain private in memory unless the existing pixel oracle accepts them.
    """
    samples = deque(maxlen=capacity)
    stop = threading.Event()
    ready = threading.Event()
    started = time.monotonic()

    def sample():
        try:
            while not stop.is_set():
                image = grab()
                samples.append((time.monotonic() - started, image))
                ready.set()
                stop.wait(interval)
        finally:
            ready.set()  # Also unblock the caller if the desktop grab fails.

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(sample)
        ready.wait()
        if worker.done():
            worker.result()
        try:
            evidence = capture()
        finally:
            stop.set()
            worker.result()
    # Include the original post-capture observation for diagnostics/comparison.
    final_image = grab()
    samples.append((time.monotonic() - started, final_image))
    return evidence, list(samples)


def run(socket, output, *, live=None, reveal=False):
    import numpy as np
    from PIL import Image, ImageGrab
    if live is None:
        live = LiveSession(Bridge(socket), physical=True)
    if reveal:
        reveal_viewer(live)
    window = viewer_window(live)

    def rectangle():
        info = subprocess.check_output(['xwininfo', '-id', window], text=True, timeout=3)
        return [int(re.search(re.escape(k) + r':\s*(-?\d+)', info).group(1))
                for k in ('Absolute upper-left X', 'Absolute upper-left Y', 'Width', 'Height')]

    bounds = rectangle()
    x, y, w, h = bounds
    output.mkdir(parents=True, exist_ok=False)

    def grab():
        desktop = ImageGrab.grab(xdisplay=os.environ.get('DISPLAY', ':1'))
        if x < 0 or y < 0 or x+w > desktop.width or y+h > desktop.height:
            return None
        return desktop.crop((x, y, x+w, y+h)).convert('RGB')

    (evidence, _), samples = sample_during_capture(
        lambda: live.capture_to(output/'capture',
            files=('left.png', 'right.png', 'mirror.png', 'evidence.json'), discard_source=True),
        grab)
    with Image.open(output/'capture/mirror.png') as expected:
        expected = np.asarray(expected.convert('RGB'))
    comparisons = [dict(
        pixel_agreement(expected, np.asarray(crop)) if crop is not None else
        {'passed': False, 'reason': 'viewer partly outside desktop'},
        sample_seconds=seconds) for seconds, crop in samples]
    best = max(range(len(comparisons)), key=lambda i: comparisons[i].get('matching_fraction', -1))
    result = dict(comparisons[best])
    if rectangle() != bounds:
        result.update(passed=False, reason='viewer moved or resized during capture')
    # Never retain other applications exposed by an obscured/failed window.
    if result['passed']:
        samples[best][1].save(output/'desktop-client.png')
    result.update(session=live.session, frame=evidence['state']['frame'], window=window,
        rectangle=bounds, revealed_owned_viewer=reveal, samples=comparisons,
        selected_sample=best, sampling='concurrent with native capture; no render pause',
        scope='Actual X11 desktop pixels versus submitted-eye mirror; not physical headset scanout')
    (output/'desktop-check.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket');parser.add_argument('output',type=Path)
    args=parser.parse_args();result=run(args.socket,args.output)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
