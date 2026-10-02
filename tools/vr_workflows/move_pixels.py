"""Registered submitted-eye ID/depth evidence for a visible exact-scope edit."""
import json
from pathlib import Path
import numpy as np
from tools.vr_motion.metrics import rotate

def centers(directory,eye_name,token):
 directory=Path(directory);e=json.loads((directory/'evidence.json').read_text())
 eye=next(v for v in e['eyes'] if v['eye']==eye_name)
 ids=np.fromfile(directory/f'{eye_name}.ids.u32',dtype=np.uint32)
 depth=np.fromfile(directory/f'{eye_name}.depth.f32',dtype=np.float32)
 objects=json.loads((directory/'objects.json').read_text())
 selected={o['id'] for o in objects if token in o['owner_tokens']}
 result={}
 index=np.flatnonzero(ids)
 if len(index):
  w,h=eye['width'],eye['height'];near,far=e['depth_near_m'],e['depth_far_m']
  z=near*far/(far-depth[index]*(far-near));left,right,up,down=np.tan(eye['fov_left_right_up_down'])
  points=np.column_stack(((left+(right-left)*((index%w+.5)/w))*z,(down+(up-down)*((index//w+.5)/h))*z,-z))
  labels,inverse,counts=np.unique(ids[index],return_inverse=True,return_counts=True)
  means=np.column_stack([np.bincount(inverse,weights=points[:,axis])/counts for axis in range(3)])
  for identity,count,center in zip(labels,counts,means):
   if count>=4:
    result[int(identity)]=np.array(eye['position'])+rotate(eye['orientation_xyzw'],center.tolist())
 return result,selected

def compare(before,after,token,*,entire_scene=False):
 report={}
 for eye in ('left','right'):
  a,selected=centers(before,eye,token);b,_=centers(after,eye,token)
  common=a.keys()&b.keys()
  moved=[float(np.linalg.norm(b[i]-a[i])) for i in common if i in selected]
  fixed=[float(np.linalg.norm(b[i]-a[i])) for i in common if i not in selected]
  report[eye]={'selected_visible':len(moved),'selected_shift_m':float(np.median(moved)) if moved else None,
               'other_visible':len(fixed),'other_shift_m':float(np.median(fixed)) if fixed else None}
 report['passed']=all(r['selected_visible']>0 and r['selected_shift_m']>.03 and (r['other_visible']==0 if entire_scene else r['other_visible']>20 and r['other_shift_m']<.015) for r in report.values())
 report['scope']='entire molecular scene' if entire_scene else 'selected subset with stationary witnesses'
 return report
