"""Live Extrude paint/wheel trials. Default steady_fast; --final uses all four.

Requires an isolated control-mode viewer with --controller-path PATH_FILE.
A semantic activate command opens Extrude; radial-menu acquisition is not tested.
"""
import argparse
import json
from pathlib import Path
import time
from .validate_interface import Probe
from .metrics import rotate, pose_error, distribution
from .model import Profile, reach, multiply
from .path_preview import export_path
from .presets import PRESETS, INITIAL_PRESET, FINAL_PRESETS


def add(a, b):
    return [x+y for x, y in zip(a, b)]


def cellset(state):
    return {tuple(c) for c in state['extrude']['cells']}


def path_trace(points, q, preset, ideal=False):
    duration, profile = PRESETS[preset]
    if ideal:
        profile = Profile(position_sigma_m=0, rotation_sigma_deg=0,
                          overshoot_fraction=0, reaction_s=profile.reaction_s)
    samples = []
    elapsed = 0
    for i, (a, b) in enumerate(zip(points, points[1:])):
        trace = reach(a, b, start_q=q, target_q=q, duration_s=duration,
                      rate_hz=20, seed=42+i, profile=profile)
        for s in trace['samples'][int(i > 0):]:
            samples.append({**s, 't': s['t']+elapsed})
        elapsed += trace['samples'][-1]['t']
    return {**trace, 'samples': samples}


def install_path(probe, file, trace):
    generation = probe.state['controller_path_generation']
    tmp = file.with_suffix('.pending')
    tmp.write_text(export_path(trace)); tmp.replace(file)
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        probe.frame()
        if probe.state['controller_path_generation'] > generation:
            return
        time.sleep(.03)
    raise RuntimeError('viewer did not load new intended path; verify --controller-path')


def put(probe, position, q):
    probe.send('pose', hand=1, position=position, orientation=q)
    probe.frame()


def drag(probe, trace, intended):
    rows = []
    started = time.monotonic()
    for sample, ideal in zip(trace['samples'], intended['samples'], strict=True):
        time.sleep(max(0, started+sample['t']-time.monotonic()))
        lag = time.monotonic()-started-sample['t']
        if lag > .15:
            raise TimeoutError(f'Extrude motion late by {lag:.3f}s')
        desired = sample['hands']['right']
        put(probe, desired['position'], desired['orientation'])
        state = probe.state
        rows.append({'t': sample['t'], 'frame': state['frame'], 'lag_s': lag,
            'intended': ideal['hands']['right'], 'desired': desired, 'actual': state['hands'][1],
            'intended_deviation_mm':pose_error(ideal['hands']['right'],state['hands'][1])['position_mm'],
            'extrude': {k: state['extrude'][k] for k in ('hover','cells','length_bp','wheel_hovered','wheel_dragging')},
            **pose_error(desired, state['hands'][1])})
    # Hold the observed endpoint still before release: this tests a controlled
    # drag, not a flick. Repeat poses renew the lease while wheel velocity decays.
    last = trace['samples'][-1]['hands']['right']
    for _ in range(12):
        put(probe, last['position'], last['orientation'])
        time.sleep(.025)
    return rows


def capture(probe, name, rows, stage, preview=None):
    from .visual_checks import check_capture
    destination = probe.output/name
    evidence,_=probe.capture_to(destination, files=('left.png','right.png','mirror.png',
        'left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','objects.json','evidence.json'), discard_source=True)
    result=check_capture(destination,evidence,rows,stage)
    (destination/'visual-checks.json').write_text(json.dumps(result,indent=2)+'\n')
    if preview:preview(destination,evidence,stage)
    # Review dwell is outside timed motion. Renew the pose lease, keeping the
    # controller and completed trace visible without injecting additional motion.
    held=probe.state['hands'][1]
    until=time.monotonic()+4
    while time.monotonic()<until:
        put(probe,held['position'],held['orientation_xyzw'])
        time.sleep(.1)
    retained=probe.output/(name+'-retained')
    proof,_=probe.capture_to(retained,files=('left.png','right.png','mirror.png',
        'left.classes.u8','right.classes.u8','evidence.json'),discard_source=True)
    persistent=check_capture(retained,proof,rows,stage)
    result['checks']['visible_after_4s']=all(persistent['checks'].values())
    result['retained']=persistent
    (destination/'visual-checks.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def trial(probe, path_file, preset, origin_pose, *, preview=None, review_only=False):
    probe.send('release')
    put(probe, origin_pose['position'], origin_pose['orientation_xyzw'])
    # Clear the preceding draft through the existing tool lifecycle so every
    # preset starts with zero length and an empty footprint.
    probe.send('activate', tool='move_rotate'); probe.frame()
    probe.send('activate', tool='extrude'); probe.frame()
    if probe.state['extrude']['length_bp'] != 0 or cellset(probe.state):
        raise RuntimeError('Extrude draft did not reset between presets')
    state = probe.state; ex = state['extrude']; q = ex['panel_orientation_xyzw']
    visible = {(c['row'],c['column']): c['position'] for c in ex['visible_cells']}
    keys = [(0,0), (0,1), (0,2)]
    if not all(c in visible for c in keys):
        raise RuntimeError('required paint cells unavailable')
    offset = rotate(q, [0,0,.18])
    points = [add(visible[c], offset) for c in keys]
    result = {'preset': preset, 'seed':42, 'expected_cells':keys,
              'cell_hit_radius_m':ex['lattice_hit_radius_m'], 'checks':{}, 'stages':{}}
    for name, route in ([('paint', points)] if review_only else [('paint', points), ('erase', list(reversed(points)))]):
        intended = path_trace(route, q, preset, ideal=True)
        actual = path_trace(route, q, preset)
        put(probe, route[0], q)
        install_path(probe, path_file, intended)
        acquired = probe.state['extrude']['hover']
        before = cellset(probe.state)
        probe.send('button', hand=1, button='trigger', pressed=True); probe.frame()
        rows = drag(probe, actual, intended)
        held = cellset(probe.state)
        probe.send('button', hand=1, button='trigger', pressed=False); probe.frame()
        after = cellset(probe.state)
        target = set(keys) if name == 'paint' else set()
        result['checks'][name+'_exact_cells'] = after == target
        result['checks'][name+'_release_stable'] = held == after
        result['stages'][name] = {'acquired_hover':acquired,'before':sorted(before),'after':sorted(after),
            'missing':sorted(target-after), 'unexpected':sorted(after-target), 'samples':rows,
            'intended_deviation_mm':distribution([r['intended_deviation_mm'] for r in rows]),
            'position_error_mm':distribution([r['position_mm'] for r in rows])}
        visual=capture(probe,preset+'-'+name,rows,name,preview)
        result['stages'][name]['visual']=visual
        result['checks'].update({name+'_'+k:v for k,v in visual['checks'].items()})
        result['checks'][name+'_path_applied']=all(r['position_mm']<1 and r['angle_deg']<.1 and r['actual']['valid'] for r in rows)
        (probe.output/(preset+'-'+name+'-intended.json')).write_text(json.dumps(intended))
        (probe.output/(preset+'-'+name+'-input.json')).write_text(json.dumps(actual))
    if review_only:
        result['passed']=all(result['checks'].values())
        return result
    wheel = next(c for c in probe.state['controls'] if c['label']=='EXTRUDE LENGTH WHEEL')
    up = wheel['hit_half_up']; length = sum(v*v for v in up)**.5
    unit_up = [v/length for v in up]
    center = add(wheel['position'], offset)
    notch = probe.state['extrude']['wheel_notch_travel_m']
    travel = 3.5*notch  # mid-bin margin: exactly three intended detents
    for name, sign in [('wheel-up',1),('wheel-down',-1)]:
        endpoint = add(center, [sign*travel*v for v in unit_up])
        intended = path_trace([center,endpoint], q, preset, ideal=True)
        actual = path_trace([center,endpoint], q, preset)
        put(probe, center, q)
        install_path(probe, path_file, intended)
        before = probe.state['extrude']['length_bp']; cells_before = cellset(probe.state)
        probe.send('button', hand=1, button='trigger', pressed=True); probe.frame()
        acquired = probe.state['extrude']['wheel_dragging']
        rows = drag(probe, actual, intended)
        probe.send('button', hand=1, button='trigger', pressed=False); probe.frame()
        after = probe.state['extrude']['length_bp']
        expected = sign*3*probe.state['extrude']['base_pairs_per_detent']
        result['checks'][name+'_acquired'] = acquired
        result['checks'][name+'_detents'] = after-before == expected
        result['checks'][name+'_no_paint'] = cellset(probe.state) == cells_before
        result['checks'][name+'_released'] = not probe.state['extrude']['wheel_dragging']
        result['stages'][name] = {'before_bp':before,'after_bp':after,'expected_delta_bp':expected,
            'actual_delta_bp':after-before,'travel_m':travel, 'wheel_width_m':2*sum(v*v for v in wheel['hit_half_right'])**.5,
            'wheel_height_m':2*length,'intended_deviation_mm':distribution([r['intended_deviation_mm'] for r in rows]),'samples':rows}
        visual=capture(probe,preset+'-'+name,rows,name,preview)
        result['stages'][name]['visual']=visual
        result['checks'].update({name+'_'+k:v for k,v in visual['checks'].items()})
        result['checks'][name+'_path_applied']=all(r['position_mm']<1 and r['angle_deg']<.1 and r['actual']['valid'] for r in rows)
        (probe.output/(preset+'-'+name+'-intended.json')).write_text(json.dumps(intended))
        (probe.output/(preset+'-'+name+'-input.json')).write_text(json.dumps(actual))
    result['passed'] = all(result['checks'].values())
    return result


def framed_origin(probe, eye, activate=None):
    """Use production placement feedback to face the tablet toward the real eye.

    Correct the wrist pose rather than changing the HMD, default tablet tilt or
    hit geometry. Position the lattice beside the settings panel within the view.
    """
    q=eye['orientation_xyzw']
    origin={'position':add(eye['position'],rotate(q,[0,-.18,-.55])), 'orientation_xyzw':q}
    def open_at_origin():
        put(probe,origin['position'],origin['orientation_xyzw'])
        if activate is not None:
            activate()
        else:
            probe.send('activate',tool='move_rotate');probe.frame()
            probe.send('activate',tool='extrude');probe.frame()
    open_at_origin()
    panel=probe.state['extrude']['panel_orientation_xyzw']
    origin['orientation_xyzw']=multiply(multiply(q,[-panel[0],-panel[1],-panel[2],panel[3]]),q)
    open_at_origin()
    target=add(eye['position'],rotate(q,[.27,0,-.70]))
    current=probe.state['extrude']['panel_position']
    origin['position']=add(origin['position'],[a-b for a,b in zip(target,current)])
    return origin


def run(socket, path_file, output, final=False, *, cancel=None, progress=None, expected_session=None, preview=None, review_only=False, preset=None):
    if preset is not None and (preset not in PRESETS or final):
        raise ValueError("choose one known preset or the final matrix")
    output.mkdir(parents=True,exist_ok=False)
    probe = Probe(socket,output,cancel=cancel)
    if expected_session is not None and probe.session != expected_session:
        raise RuntimeError('viewer session changed before profile run')
    report = {'schema':'nadoc-extrude-probe-1','session':probe.session,'trials':[],
        'scope':'Live draft paint and controlled wheel drags; semantic Extrude activation bypasses radial acquisition; no browser commit; synthetic profiles.'}
    try:
        probe.send('release')
        anchor,_ = probe.capture('anchor')
        eye = anchor['eyes'][0]
        # Same world anchor, targets and seed for every preset; only profile varies.
        origin = framed_origin(probe,eye)
        for preset in (FINAL_PRESETS if final else [preset or INITIAL_PRESET]):
            if progress:
                progress(preset)
            result = trial(probe,path_file,preset,origin,preview=preview,review_only=review_only)
            report['trials'].append(result)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({'preset':preset,'passed':result['passed'],'checks':result['checks']}),flush=True)
        if review_only:
            from .visual_checks import check_capture
            probe.release()
            directory=output/'released-review'
            evidence,_=probe.capture_to(directory,files=('left.png','right.png','mirror.png',
                'left.classes.u8','right.classes.u8','evidence.json'),discard_source=True)
            retained=check_capture(directory,evidence,report['trials'][-1]['stages']['paint']['samples'],'paint',require_controller=False)
            report['released_review']=retained
            report['trials'][-1]['checks']['paint_trace_retained_after_release']=all(retained['checks'].values())
            report['trials'][-1]['passed']=all(report['trials'][-1]['checks'].values())
        report['completed'] = True
        report['passed'] = all(t['passed'] for t in report['trials'])
    except Exception as error:
        report['error'] = repr(error)
        report['failed_operation']=getattr(probe,'last_operation',None)
        raise
    finally:
        try:
            probe.release()
        finally:
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            from .extrude_report import write_report
            write_report(output)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket');parser.add_argument('path_file',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--final',action='store_true')
    parser.add_argument('--preset',choices=list(PRESETS),help='Explicit single-profile diagnostic rerun; not a full final matrix')
    parser.add_argument('--review',action='store_true',help='Paint only; retain painted cells and trace for human review')
    args=parser.parse_args()
    report=run(args.socket,args.path_file,args.output,args.final,review_only=args.review,preset=args.preset)
    raise SystemExit(0 if all(t['passed'] for t in report['trials']) else 1)


if __name__=='__main__':
    main()
