"""Independent depth reconstruction checks for a local representation change.

Only baseline design pixels count. Menu, controller and outline pixels cannot
satisfy this check. Interior changes and exterior preservation are both required.
"""
import json
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

def compare(enabled, disabled, volume):
    evidence=json.loads((disabled/'evidence.json').read_text())
    enabled_evidence=json.loads((enabled/'evidence.json').read_text())
    checks=[]
    for eye in evidence['eyes']:
        name=eye['eye'];height,width=eye['height'],eye['width']
        before=np.asarray(Image.open(disabled/f'{name}.png').convert('RGB'),dtype=np.int16)
        after=np.asarray(Image.open(enabled/f'{name}.png').convert('RGB'),dtype=np.int16)
        ids=np.fromfile(disabled/f'{name}.ids.u32',dtype=np.uint32).reshape(height,width)[::-1]
        depth=np.fromfile(disabled/f'{name}.depth.f32',dtype=np.float32).reshape(height,width)[::-1]
        y,x=np.nonzero((ids!=0)&(depth<1))
        n,f=evidence['depth_near_m'],evidence['depth_far_m']
        d=2*n*f/(f+n-(2*depth[y,x]-1)*(f-n))
        left,right,up,down=np.tan(eye['fov_left_right_up_down'])
        camera=np.column_stack((d*(left+(x+.5)/width*(right-left)),d*(up-(y+.5)/height*(up-down)),-d))
        world=Rotation.from_quat(eye['orientation_xyzw']).apply(camera)+eye['position']
        distances=np.column_stack([(world-face['world_center'])@np.array(face['world_normal']) for face in volume['faces']])
        interior=distances.max(axis=1)<-.002
        exterior=distances.max(axis=1)>.01
        # Reproject the SAME baseline surfaces into the enabled eye. Tracked
        # headset poses may drift between captures even on a stationary stand.
        target_eye=next(e for e in enabled_evidence['eyes'] if e['eye']==name)
        target=Rotation.from_quat(target_eye['orientation_xyzw']).inv().apply(world-target_eye['position'])
        tl,tr,tu,td=np.tan(target_eye['fov_left_right_up_down'])
        tx=np.rint((target[:,0]/-target[:,2]-tl)/(tr-tl)*width-.5).astype(int)
        ty=np.rint((tu-target[:,1]/-target[:,2])/(tu-td)*height-.5).astype(int)
        enabled_ids=np.fromfile(enabled/f'{name}.ids.u32',dtype=np.uint32).reshape(height,width)[::-1]
        difference=np.full(len(x),255,dtype=np.int16)
        # A one-pixel raster footprint, always constrained to the SAME primitive
        # ID. A nearby outline/controller/different base cannot explain a match.
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                xx,yy=tx+dx,ty+dy
                valid=(xx>=0)&(xx<width)&(yy>=0)&(yy<height)&(target[:,2]<0)
                indices=np.flatnonzero(valid)
                indices=indices[enabled_ids[yy[indices],xx[indices]]==ids[y[indices],x[indices]]]
                error=np.max(abs(before[y[indices],x[indices]]-after[yy[indices],xx[indices]]),axis=1)
                difference[indices]=np.minimum(difference[indices],error)
        changed=int(((difference>25)&interior).sum())
        stable=float((difference[exterior]<=25).mean()) if exterior.any() else 0
        row={'eye':name,'interior_design_pixels':int(interior.sum()),'interior_changed_pixels':changed,
             'exterior_design_pixels':int(exterior.sum()),'exterior_stable_fraction':stable}
        row['passed']=changed>100 and row['exterior_design_pixels']>100 and stable>.95
        checks.append(row)
    return {'checks':checks,'passed':len(checks)==2 and all(c['passed'] for c in checks)}
