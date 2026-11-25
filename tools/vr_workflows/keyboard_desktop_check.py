"""Exercise all four native keyboard studies using actual desktop mouse input.

Owns one GLFW window and writes only to the requested development evidence folder.
The process is stopped in finally; no browser, workspace or headset is changed.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np
from PIL import Image, ImageGrab
from tools.vr_workflows.tour_catalog import ROOT
from tools.vr_workflows.desktop_input import DesktopInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.development-artifacts/vr-keyboard-studies/desktop')
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    command = [str(ROOT/'native/vr_viewer/build/nadoc-vr-viewer'), str(ROOT/'native/vr_viewer/examples/empty_authoring.nadocvr'),
               '--component-gallery', 'keyboards', '--gallery-desktop', 'on', '--gallery-output', str(output)]
    desktop_input = DesktopInput()
    with (output/'viewer.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
    results = []
    try:
        deadline = time.monotonic()+20
        while True:
            try:
                window = desktop_input.window(process.pid); break
            except (subprocess.CalledProcessError, LookupError):
                if time.monotonic()>deadline or process.poll() is not None: raise
                time.sleep(.1)
        desktop_input.reveal(window);time.sleep(.3)
        info = subprocess.check_output(['xwininfo','-id',window],text=True)
        x,y,w,h = [int(re.search(re.escape(k)+r':\s*(-?\d+)',info).group(1)) for k in ('Absolute upper-left X','Absolute upper-left Y','Width','Height')]
        def key(k): desktop_input.key(k);time.sleep(.15)
        def capture():
            before = len(list(output.glob('desktop-*.json')))
            desktop_input.move(x+w-15,y+h-15);key('s')
            deadline = time.monotonic()+5
            while len(list(output.glob('desktop-*.json'))) <= before:
                if time.monotonic()>deadline: raise RuntimeError('Gallery capture missing')
                time.sleep(.05)
            latest = max(output.glob('desktop-*.json'),key=lambda p:p.stat().st_mtime_ns)
            return latest, json.loads(latest.read_text())
        _, state = capture()
        def click(identifier):
            point = next(c['position'] for c in state['controls'] if c['id']==identifier)
            f = 1/math.tan(math.radians(26)); distance = 1.25-point[2]
            px=x+w/2+point[0]*f/distance*h/2; py=y+h/2-point[1]*f/distance*h/2
            desktop_input.move(round(px),round(py)); desktop_input.click();time.sleep(.1)
        for variant in range(4):
            key('f');click(variant);_,state=capture();assert state['variant']==variant
            click(6);_,state=capture()
            click(10);_,state=capture();assert state['length']==1  # number 1
            click(20);_,state=capture();assert state['length']==0  # Backspace
            click(21);_,state=capture();assert state['length']==1  # Q
            click(5);_,state=capture();assert state['disabled']
            click(21);_,state=capture();assert state['length']==1
            click(5);_,state=capture()
            for view in ('front','oblique'):
                if view=='oblique':key('o')
                path,state=capture();time.sleep(.15)
                desktop=ImageGrab.grab(xdisplay=os.environ.get('DISPLAY',':1')).crop((x,y,x+w,y+h)).convert('RGB')
                desktop.save(output/f'style-{variant+1}-{view}-desktop.png')
                native=Image.open(path.with_suffix('.png')).convert('RGB')
                a,b=np.asarray(desktop),np.asarray(native)
                assert a.shape==b.shape
                agreement=float(np.mean(np.max(np.abs(a.astype(int)-b.astype(int)),axis=2)<12))
                assert agreement>.98, (variant,view,agreement)
                assert np.count_nonzero(a[:,:,0]>150)>2500, 'blank delivered window'
                border=np.concatenate([a[:4].reshape(-1,3),a[-4:].reshape(-1,3),a[:,:4].reshape(-1,3),a[:,-4:].reshape(-1,3)])
                assert not np.any(border.min(axis=1)>100), 'gallery text is clipped at the window edge'
                results.append(dict(style=variant+1,view=view,desktop_agreement=agreement))
        (output/'result.json').write_text(json.dumps({'passed':True,'views':results},indent=2))
    finally:
        desktop_input.close()
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill();process.wait()
    print(output/'result.json')


if __name__=='__main__': main()
