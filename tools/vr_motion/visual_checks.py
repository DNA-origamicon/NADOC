"""Independent projected-path, paint-pixel and actual mirror-buffer checks.

No rendered debug overlay from this checker is used as proof. Native stencil IDs
identify surviving fragments, while PNG RGB confirms visible colour/contrast.
"""
import math
from .metrics import rotate, dot, sub


def project(point, eye):
    q=eye['orientation_xyzw']
    p=rotate([-q[0],-q[1],-q[2],q[3]],sub(point,eye['position']))
    if p[2]>=-.001:return None
    left,right,up,down=map(math.tan,eye['fov_left_right_up_down'])
    return ((p[0]/-p[2]-left)/(right-left)*eye['width'],
            (up-p[1]/-p[2])/(up-down)*eye['height'])


def contact(pose, state, ideal=False):
    panel=state['extrude'];normal=rotate(panel['panel_orientation_xyzw'],[0,0,1])
    direction=[-v for v in normal] if ideal else rotate(pose.get('orientation_xyzw',pose.get('orientation')),[0,0,-1])
    denominator=dot(direction,normal)
    if abs(denominator)<1e-8:return None
    t=dot(sub(panel['panel_position'],pose['position']),normal)/denominator
    if t<0:return None
    return [v+t*d for v,d in zip(pose['position'],direction)]


def coverage(mask, points, radius=8):
    """Include missing/offscreen points in the denominator; never silently clip."""
    height,width=mask.shape;hits=0
    for p in points:
        if p is None:continue
        x,y=map(round,p)
        if not 0<=x<width or not 0<=y<height:continue
        hits+=bool(mask[max(0,y-radius):min(height,y+radius+1),max(0,x-radius):min(width,x+radius+1)].any())
    return hits/len(points) if points else 0


def check_capture(directory, evidence, rows, stage, *, require_controller=True):
    import numpy as np
    from PIL import Image
    state=evidence['state'];results={};checks={}
    for eye in evidence['eyes']:
        name=eye['eye'];rgb=np.asarray(Image.open(directory/(name+'.png')).convert('RGB'))
        tags=np.fromfile(directory/(name+'.classes.u8'),dtype=np.uint8).reshape(eye['height'],eye['width'])[::-1]
        result={}
        for key,tag in [('intended',6),('actual',7)]:
            points=[project(p,eye) if (p:=contact(row[key],state,key=='intended')) is not None else None for row in rows]
            colour=((rgb[:,:,0]>200)&(rgb[:,:,1]>170)&(rgb[:,:,2]<100) if key=='intended' else (rgb[:,:,0]>200)&(rgb[:,:,1]<100)&(rgb[:,:,2]>140))
            visible=(tags==tag)&colour
            corridor=np.zeros(tags.shape,dtype=bool)
            for a,b in zip(points,points[1:]):
                if a is None or b is None:continue
                for u in np.linspace(0,1,min(10000,max(2,math.ceil(math.dist(a,b))))):
                    x,y=map(round,(a[0]+u*(b[0]-a[0]),a[1]+u*(b[1]-a[1])))
                    if 0<=x<eye['width'] and 0<=y<eye['height']:
                        corridor[max(0,y-8):y+9,max(0,x-8):x+9]=True
            precision=float((visible&corridor).sum()/max(1,visible.sum()))
            result[key]={'pixels':int(visible.sum()),'projected_sample_coverage':coverage(visible,points),'pixels_on_expected_route':precision}
            checks[name+'_'+key+'_trace_aligned']=precision>=.9
            checks[name+'_'+key+'_trace_visible']=visible.sum()>=30 and coverage(visible,points)>=.9
        result['controller_pixels']=int((tags==5).sum())
        if require_controller:checks[name+'_controller_visible']=result['controller_pixels']>=10
        if stage=='paint':
            warm=(rgb[:,:,0]>200)&(rgb[:,:,1]>140)&(rgb[:,:,2]<210)&(rgb[:,:,0].astype(float)>rgb[:,:,1]*1.02)&(tags==3)
            cells=[]
            panel=state['extrude'];up=rotate(panel['panel_orientation_xyzw'],[0,panel['lattice_hit_radius_m'],0])
            for cell in panel['visible_cells']:
                if [cell['row'],cell['column']] not in panel['cells']:continue
                p=project(cell['position'],eye);edge=project([a+b for a,b in zip(cell['position'],up)],eye)
                pixels=0
                if p and edge and 0<=p[0]<eye['width'] and 0<=p[1]<eye['height']:
                    radius=max(3,math.ceil(math.dist(p,edge)*1.3));x,y=map(round,p)
                    pixels=int(warm[max(0,y-radius):y+radius+1,max(0,x-radius):x+radius+1].sum())
                cells.append({'cell':[cell['row'],cell['column']],'selected_colour_pixels':pixels})
            result['painted_cells']=cells
            checks[name+'_paint_visible']=len(cells)==3 and all(c['selected_colour_pixels']>=3 for c in cells)
        results[name]=result
    mirror=evidence.get('mirror')
    checks['desktop_submitted_source']=bool(mirror and mirror.get('source')=='submitted_eye_blit_backbuffer')
    if mirror:
        eye=next(e for e in evidence['eyes'] if e['eye']==mirror['eye'])
        source=np.asarray(Image.open(directory/(mirror['eye']+'.png')).convert('RGB')).astype(float)
        desktop=np.asarray(Image.open(directory/'mirror.png').convert('RGB')).astype(float)
        x,y,w,h=mirror['viewport_bottom_up'];y=mirror['height']-y-h
        actual=desktop[y:y+h,x:x+w]
        # Match GL_LINEAR's pixel-centre mapping, without Pillow's downsample filter.
        xs=np.clip((np.arange(w)+.5)*eye['width']/w-.5,0,eye['width']-1)
        ys=np.clip((np.arange(h)+.5)*eye['height']/h-.5,0,eye['height']-1)
        x0=xs.astype(int);y0=ys.astype(int);x1=np.minimum(x0+1,eye['width']-1);y1=np.minimum(y0+1,eye['height']-1)
        a=(xs-x0)[None,:,None];b=(ys-y0)[:,None,None]
        expected=(source[y0[:,None],x0]*(1-a)+source[y0[:,None],x1]*a)*(1-b)+(source[y1[:,None],x0]*(1-a)+source[y1[:,None],x1]*a)*b
        mae=float(np.abs(actual-expected).mean())
        # Require visible paths in the actual desktop pixels, not just similarity
        # between two blank frames. Gold and magenta have distinct colour masks.
        gold=(actual[:,:,0]>180)&(actual[:,:,1]>140)&(actual[:,:,2]<100)
        pink=(actual[:,:,0]>180)&(actual[:,:,1]<120)&(actual[:,:,2]>130)
        results['mirror']={'mean_absolute_rgb_error':mae,'gold_pixels':int(gold.sum()),'magenta_pixels':int(pink.sum()),'viewport':mirror}
        checks['desktop_matches_submitted_eye']=mae<2
        checks['desktop_traces_visible']=gold.sum()>=10 and pink.sum()>=10
    else:
        checks['desktop_matches_submitted_eye']=checks['desktop_traces_visible']=False
    return {'checks':{k:bool(v) for k,v in checks.items()},'measurements':results}
