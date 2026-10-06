"""Measured interior/border grip ownership and depth sweep; no fixture edits."""
import json
import math
from tools.vr_motion.metrics import rotate, dot, sub
from tools.vr_workflows.menu_grip_check import move
from tools.vr_workflows.demo_view import hold


def zoom_lattice(live, output, preset, factor):
    """Declared observation condition using the ordinary two-grip zoom gesture."""
    output.mkdir(parents=True, exist_ok=False)
    before=json.loads(json.dumps(live.state['extrude']))
    scene=live.state['presentation']['model_to_tracking_rows']
    trials=[]
    def targets(half_width):
        return {hand:[a+b for a,b in zip(before['panel_position'],
            rotate(before['panel_orientation_xyzw'],[sign*half_width*before['panel_scale'],0,0]))]
            for hand,sign in ((0,-1),(1,1))}
    try:
        move(live,targets(.12),preset,trials)
        for hand in (0,1):live.send('button',hand=hand,button='grip',pressed=True)
        live.frame()
        assert live.state['extrude']['grid_scaling'], 'lattice zoom grips not acquired'
        move(live,targets(.12*factor),preset,trials)
    finally:
        for hand in (0,1):live.send('button',hand=hand,button='grip',pressed=False)
        live.frame()
        after=live.state['extrude']
        (output/'zoom.json').write_text(json.dumps({'scope':'explicit observation zoom; original auto-fit is a separate condition',
            'preset':preset,'requested_factor':factor,'actual_factor':after['lattice_zoom']/before['lattice_zoom'],
            'before':before,'after':after,'trials':trials},indent=2)+'\n')
    assert after['cells']==before['cells']
    assert after['panel_position']==before['panel_position'] and after['panel_scale']==before['panel_scale']
    assert live.state['presentation']['model_to_tracking_rows']==scene
    live.capture_to(output/'view',discard_source=True)


def run(live, output, preset):
    trials, checks = [], []
    output.mkdir(parents=True, exist_ok=True)
    cells = live.state['extrude']['cells']
    wheels = [(w['position'],w['orientation_xyzw'],w['scale'])
              for w in live.state['extrude'].get('wheels',[])]

    def save():
        (output/'grips.json').write_text(json.dumps({'profile': preset, 'checks': checks, 'trials': trials}, indent=2))

    def point(x, y=0, depth=0):
        panel = live.state['extrude']
        offset = rotate(panel['panel_orientation_xyzw'], [x*panel['panel_scale'], y*panel['panel_scale'], depth])
        return [a+b for a,b in zip(panel['panel_position'], offset)]

    def buttons(pressed):
        for hand in (0, 1):
            live.send('button', hand=hand, button='grip', pressed=pressed)
        live.frame()

    def motion(targets):
        move(live, targets, preset, trials)
        trials[-1]['extrude_after'] = live.state['extrude']
        save()

    try:
        # Same profile and production tolerance for every depth. Outside samples
        # deliberately exceed the acquisition band and must stay unclaimed.
        for depth in (0, -.04, .04, -.07, .07, -.13, .13):
            buttons(False)
            before = json.loads(json.dumps(live.state['extrude']))
            scene = live.state['presentation']['model_to_tracking_rows']
            motion({0: point(-.09, depth=depth), 1: point(.09, depth=depth)})
            actual = list(live.state['extrude']['grid_grip_nearby'])
            panel = live.state['extrude']
            normal = rotate(panel['panel_orientation_xyzw'], [0, 0, 1])
            measured_depths = [dot(sub(h['position'], panel['panel_position']), normal)
                               for h in live.state['hands']]
            buttons(True)
            active = live.state['extrude']['grid_scaling']
            expected = abs(depth) <= .07
            check = {'requested_depth_m': depth, 'nearby': actual, 'scaling': active, 'expected': expected,
                     'measured_depths_m': measured_depths,
                     'candidate_depth_accepts_both': {
                         str(band): all(abs(d) <= band for d in measured_depths)
                         for band in (.05, .075, .09)}}
            checks.append(check);save()
            assert active == expected, check
            if expected:
                motion({0: point(-.125, depth=depth), 1: point(.125, depth=depth)})
                after = live.state['extrude']
                check['zoom_ratio'] = after['lattice_zoom']/before['lattice_zoom']
                assert check['zoom_ratio'] > 1.12, check
                assert after['panel_position'] == before['panel_position']
                assert after['panel_scale'] == before['panel_scale']
                assert live.state['presentation']['model_to_tracking_rows'] == scene
                if depth == 0:
                    live.capture_to(output/'grid-scaling', discard_source=True)
                    hold(live, 'Two grips inside zoom the lattice; the window stays fixed')
                # Return near the starting zoom with a real profiled pinch.
                motion({0: point(-.09, depth=depth), 1: point(.09, depth=depth)})
            buttons(False)
            assert not live.state['extrude']['grid_scaling']
            assert live.state['extrude']['cells'] == cells
        # Border gestures remain window-owned, with zoom unchanged.
        zoom = live.state['extrude']['lattice_zoom']
        before = live.state['extrude']['panel_position']
        motion({0: point(-.29), 1: point(.29)})
        live.send('button', hand=0, button='grip', pressed=True);live.frame()
        assert live.state['extrude']['window_moving']
        motion({0: point(-.29, .05)})
        assert math.dist(before, live.state['extrude']['panel_position']) > .015
        motion({1: point(.29)})
        live.send('button', hand=1, button='grip', pressed=True);live.frame()
        assert live.state['extrude']['window_resizing']
        scale = live.state['extrude']['panel_scale']
        motion({0: point(-.34), 1: point(.34)})
        assert live.state['extrude']['panel_scale'] > scale*1.04
        assert live.state['extrude']['lattice_zoom'] == zoom
        assert live.state['extrude']['cells'] == cells
        assert [(w['position'],w['orientation_xyzw'],w['scale'])
                for w in live.state['extrude'].get('wheels',[])] == wheels
        live.capture_to(output/'window-resizing', discard_source=True)
        hold(live, 'Border grips move and resize the painter; length wheels stay in the main menu')
        checks.append({'border_move_resize': True,'main_menu_wheels_stationary':True});save()
    finally:
        buttons(False)
        save()
