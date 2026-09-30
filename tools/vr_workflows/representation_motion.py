"""Real grip motion and stereo geometry evidence, outside loading intervals."""
import json
import math
import time
import numpy as np
from tools.vr_workflows.profile_input import reach_target


def check(live, output, preset):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(preset=preset, motions=[])
    open_sides = [i for i, menu in enumerate(live.state['sidebars']) if menu['open']]
    try:
        for side in open_sides:
            live.button('menu', hand=side)
        head = live.state['head_position']
        home = [head[0]+.3, head[1]-.35, head[2]-.35]
        live.send('pose', hand=1, position=home, orientation=[0,0,0,1])
        live.frame()
        before = live.state['presentation']['model_to_tracking_rows']
        live.send('button', hand=1, button='grip', pressed=True)
        live.frame()
        for index, target in enumerate(([home[0]+.12, home[1], home[2]], home)):
            angle = .2 if index == 0 else 0
            start = time.time()*1000
            pending=dict(start_ms=start)
            report['motions'].append(pending)
            trial = reach_target(live, target, preset, 9321+index,
                                 target_position=target,
                                 target_orientation=[0,math.sin(angle/2),0,math.cos(angle/2)])
            trial.update(start_ms=start, end_ms=time.time()*1000,
                         model=live.state['presentation']['model_to_tracking_rows'])
            pending.update(trial)
            if index == 0:
                assert np.max(np.abs(np.array(trial['model'])-before)) > .01, 'Grip did not move model'
        live.send('button', hand=1, button='grip', pressed=False)
        live.frame()
        live.capture_to(output/'stereo', files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','evidence.json'], discard_source=True)
        for eye in ('left','right'):
            classes=np.fromfile(output/'stereo'/(eye+'.classes.u8'),np.uint8)
            ids=np.fromfile(output/'stereo'/(eye+'.ids.u32'),np.uint32)
            assert ((classes==1)&(ids>0)).sum()>100, 'Model not visible after grip movement'
        report['passed']=True
    except Exception as error:
        report['error']=str(error)
        if report['motions']:report['motions'][-1].setdefault('end_ms',time.time()*1000)
        raise
    finally:
        (output/'motion.json').write_text(json.dumps(report,indent=2))
        live.send('button', hand=1, button='grip', pressed=False)
        live.frame()
        for side in open_sides:
            if not live.state['sidebars'][side]['open']:
                live.button('menu', hand=side)
