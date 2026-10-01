"""Whole-model broadside framing and faster grip sweeps through ScryWrite.

Framing is an observation adjustment, outside measured motion. The speed sweep
is separate from the unchanged human-profile acceptance matrix. It never drives
head tracking; input sample cadence is reported and is not headset scanout proof.
"""
import json
import math
import time
import numpy as np
from tools.vr_motion.playback import play_live
from tools.vr_motion.model import validate_trace, summary


def frame_broadside(live, reference):
    """Use normal grip transforms to place the normalized part broadside, 10x."""
    live.release()
    for hand in range(2):
        if live.state['sidebars'][hand]['open']:
            live.button('menu', hand=hand)
    model = np.array(live.state['presentation']['model_to_tracking_rows'])
    initial = np.array(reference['presentation']['model_to_tracking_rows'])
    center = (model @ np.array([0, 0, -1.3, 1]))[:3]
    scale = np.linalg.norm(model[:3, 0])
    desired_scale = min(20., np.linalg.norm(initial[:3, 0])*10)
    factor = desired_scale/scale
    for hand, sign in ((0, -1), (1, 1)):
        live.send('pose', hand=hand, position=(center+[sign*.05,0,0]).tolist(), orientation=[0,0,0,1])
    live.frame()
    for hand in range(2):
        live.send('button',hand=hand,button='grip',pressed=True)
        live.frame()
    for hand, sign in ((0, -1), (1, 1)):
        live.send('pose',hand=hand,position=(center+[sign*.05*factor,0,0]).tolist(),orientation=[0,0,0,1])
    live.frame()
    for hand in range(2):
        live.send('button',hand=hand,button='grip',pressed=False)
        live.frame()
    # Rotation required from the currently displayed basis to initial broadside.
    current = np.array(live.state['presentation']['model_to_tracking_rows'])
    base = initial[:3,:3]/np.linalg.norm(initial[:3,0])
    side = np.array([[0.,0.,1.],[0.,1.,0.],[-1.,0.,0.]])
    rotation = base @ side @ (current[:3,:3]/np.linalg.norm(current[:3,0])).T
    from scipy.spatial.transform import Rotation
    q = Rotation.from_matrix(rotation).as_quat().tolist()
    head = np.array(reference['head_position'])
    forward = (initial @ np.array([0,0,-1.3,1]))[:3]-head
    target = head+forward/np.linalg.norm(forward)*8.
    center = (current @ np.array([0,0,-1.3,1]))[:3]
    live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
    live.send('button',hand=1,button='grip',pressed=True);live.frame()
    live.send('pose',hand=1,position=target.tolist(),orientation=q);live.frame()
    live.send('button',hand=1,button='grip',pressed=False);live.frame()
    actual = np.array(live.state['presentation']['model_to_tracking_rows'])
    assert np.allclose(actual[:3,:3],base@side*desired_scale,atol=.002), 'Broadside rotation/scale not applied'
    assert np.allclose((actual@np.array([0,0,-1.3,1]))[:3],target,atol=.002), 'Broadside position not applied'
    return dict(scale=desired_scale,distance_m=8,orientation='right',model=actual.tolist())


def speed_trace(home, speed_deg_s, rate_hz=20):
    """Four seconds of +/-8 degree yaw; peak speeds 30/60/120 deg/s.

    The live RPC transport cannot sustain display-rate input. Use the existing
    20 Hz diagnostic cadence; this measures delivery under fast model motion,
    not the visual smoothness of physical tracking at the headset refresh rate.
    """
    amplitude=math.radians(8)
    omega=math.radians(speed_deg_s)/amplitude
    samples=[]
    # A stationary lead-in ensures the grip edge uses the home pose.
    for i in range(1+round(5*rate_hz)):
        t=i/rate_hz
        a=amplitude*math.sin(omega*min(4.,max(0,t-.3)))
        if t>4.3: a*=max(0.,(4.8-t)/.5)
        samples.append(dict(t=t,hands={'right':dict(position=list(home),
            orientation=[0,math.sin(a/2),0,math.cos(a/2)],valid=True)}))
    trace=dict(schema='nadoc-motion-1',space='OpenXR_LOCAL',units='meters',quaternion_order='xyzw',
        provenance=dict(kind='diagnostic_speed_sweep',peak_yaw_deg_s=speed_deg_s,rate_hz=rate_hz),
        samples=samples,events=[dict(t=.15,hand='right',button='grip',pressed=True),
                               dict(t=5.,hand='right',button='grip',pressed=False)])
    validate_trace(trace,playable=True)
    return trace


def sweep(live, output):
    output.mkdir(parents=True,exist_ok=False)
    report=[]
    head=live.state['head_position'];home=[head[0]+.3,head[1]-.35,head[2]-.35]
    try:
        for speed in (30,60,120):
            trace=speed_trace(home,speed)
            (output/f'{speed}-input.json').write_text(json.dumps(trace))
            row=dict(speed_deg_s=speed,input_summary=summary(trace),start_ms=time.time()*1000)
            report.append(row)
            try:
                row['delivery']=play_live(trace,live.bridge,allow_transactions=True)
            except Exception as error:
                row['error']=str(error)
                raise
            finally:
                row['end_ms']=time.time()*1000
                live.state=live.bridge.call('scrywrite_observe',{})
        live.capture_to(output/'stereo',files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
    finally:
        (output/'speeds.json').write_text(json.dumps(report,indent=2))
        live.release()
