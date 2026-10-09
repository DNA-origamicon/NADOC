"""Project every actual wheel surface into its captured eye; reject blank output."""
import math
import numpy as np
from PIL import Image
from tools.vr_motion.metrics import rotate, sub


def check(directory, evidence):
    rows=[]
    gallery=evidence['state']['component_gallery']
    controls=gallery['samples'] if gallery.get('component') in ('buttons','cards','lists') else gallery['wheels']
    for eye in evidence['eyes']:
        rgb=np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        q=eye['orientation_xyzw'];inverse=[-q[0],-q[1],-q[2],q[3]]
        left,right,up,down=map(math.tan,eye['fov_left_right_up_down'])
        for index,wheel in enumerate(controls):
            p=rotate(inverse,sub(wheel.get('surface_position',wheel['position']),eye['position']))
            x=(p[0]/-p[2]-left)/(right-left)*eye['width']
            y=(up-p[1]/-p[2])/(up-down)*eye['height']
            valid=p[2]<-.001 and 5<=x<eye['width']-5 and 5<=y<eye['height']-5
            pixels=rgb[int(y)-4:int(y)+5,int(x)-4:int(x)+5] if valid else np.zeros((9,9,3))
            lit=(pixels.max(axis=2)>80)&(pixels[:,:,1]>65)
            if gallery.get('component') in ('cards','lists'):
                # Card headers intentionally use a dark slate palette. Match the
                # rendered face itself, retaining the same sample-count floor;
                # black/empty captures cannot match this component color.
                if gallery.get('component')=='lists':
                    lit=lit|np.all(np.abs(pixels.astype(float)-np.array([26,37,48]))<=8,axis=2)|np.all(np.abs(pixels.astype(float)-np.array([31,82,97]))<=8,axis=2)
                slate=np.all(np.abs(pixels.astype(float)-np.array([46,64,84]))<=8,axis=2)
                lit=lit|slate
            visible=int(lit.sum())
            rows.append(dict(eye=eye['eye'],wheel=index,in_frame=valid,visible_samples=visible,passed=valid and visible>=20))
    return {'passed':len(rows)==2*len(controls) and all(r['passed'] for r in rows),'wheels':rows}
