"""Exercise all six UI-only file menu styles through the real native gallery."""
import json
from copy import deepcopy
from tools.vr_motion.presets import FINAL_PRESETS
from tools.vr_workflows.profile_input import reach_target
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.gallery_pixels import check
from tools.vr_workflows.sweep_view import fullscreen_mirror
from tools.vr_motion.desktop_check import run as desktop_check


def validate(live, output):
    trials = []
    completed = []
    fullscreen_mirror(live, output)
    def control(identifier):
        return next(c for c in live.state['component_gallery']['controls'] if c['id'] == identifier)
    def click(identifier, preset):
        target = control(identifier)['position']
        orientation = live.state['component_gallery']['orientation_xyzw']
        normal = rotate(orientation, [0, 0, .30])
        for attempt in range(3):
            trial = reach_target(live, target, preset, 8120+len(trials),
                target_position=[p+n for p,n in zip(target, normal)],
                acquired=lambda s: next(c for c in s['component_gallery']['controls'] if c['id']==identifier)['hovered'])
            trial.update(control=identifier, preset=preset, attempt=attempt+1)
            trials.append(trial)
            if trial['acquired_with_feedback']: break
        else: raise AssertionError((preset, identifier, 'not acquired'))
        live.button('trigger')
    try:
        for preset in FINAL_PRESETS:
            for variant in range(6):
                click(variant, preset)
                assert live.state['component_gallery']['variant'] == variant
                before = live.state['component_gallery']['clicks']
                click(11, preset)
                assert live.state['component_gallery']['clicks'] == before
                if variant==0: click(20, preset)
                if variant==4: click(22, preset)
                click(30, preset)
                assert live.state['component_gallery']['selected']==0
                if preset=='steady_fast':
                    destination=output/f'style-{variant+1}'
                    evidence,_=live.capture_to(destination,files=['left.png','right.png','mirror.png','evidence.json'],discard_source=True)
                    report=check(destination,evidence)
                    (destination/'pixels.json').write_text(json.dumps(report,indent=2))
                    assert report['passed'],report
                    negative=deepcopy(evidence)
                    for c in negative['state']['component_gallery']['controls']: c['position']=[1000,1000,1000]
                    assert not check(destination,negative)['passed']
                    assert desktop_check(live.bridge.socket_path,destination/'desktop',live=live,reveal=True)['passed']
                if variant==4:
                    click(22,preset)
                    assert not any(c['id']>=30 for c in live.state['component_gallery']['controls'])
                completed.append({'profile': preset, 'style': variant+1})
                print(f'{preset}: style {variant+1} selected and inspected',flush=True)
    finally:
        live.release()
        (output/'trials.json').write_text(json.dumps(trials,indent=2))
        (output/'result.json').write_text(json.dumps({'passed':len(completed)==24, 'completed':completed,
            'reaches':len(trials),'retry_reaches':sum(t['attempt']>1 for t in trials)},indent=2))
        names=['Essential','Folder tiles','Compact list','Detail table','Folder tree','Split inspector']
        cards=''.join(f'<section id="style-{i}"><h2>{i}. {name}</h2><img src="style-{i}/desktop/desktop-client.png" alt="Actual desktop mirror: {name}"></section>' for i,name in enumerate(names,1) if (output/f'style-{i}/desktop/desktop-client.png').exists())
        (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Six VR File menu styles</title>'
            '<style>body{background:#10151c;color:#eee;font:18px system-ui;max-width:1400px;margin:32px auto}img{width:100%}section{margin:40px 0}a{color:#8bd3ff}</style>'
            '<h1>Six VR File menu styles</h1><p>Actual native VR gallery desktop captures. Sample data only; no document writes. '
            'Open Debug → VR Component Gallery → File menus to compare interactively.</p>'+cards)
