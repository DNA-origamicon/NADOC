"""Measure partial pressure through actual native input and the rendered key pose."""
import json
import numpy as np


def verify(live, output, preset, acquire, click, control, wait, review, keys):
    identifier='routing:file-key-d'
    acquire(identifier, preset)
    before=control('routing-help')['label']
    reference=np.array(control(identifier)['position'])
    normal=np.cross(control(identifier)['hit_half_right'],control(identifier)['hit_half_up'])
    normal/=np.linalg.norm(normal)
    scale=live.state['routing_popup'][1]['scale']
    rows=[]
    key_checks_passed=False;partial_activation=False
    def sample(value):
        live.send('trigger_value',hand=1,value=value)
        for _ in range(4):live.frame()
        popup=live.state['routing_popup'][1]
        actual=popup['keyboard_pressure'].get(identifier,0)
        travel=float(np.dot(reference-np.array(control(identifier)['position']),normal))
        assert abs(actual-value)<.001, (preset,value,actual)
        assert abs(travel-.006*scale*value)<.00003, (preset,value,travel)
        rows.append({'trigger':value,'rendered_pressure':actual,'travel_m':travel})
    try:
        for pressure in (0,.25,.5,.75,.85):
            sample(pressure)
            partial_activation |= control('routing-help')['label']!=before
            assert not partial_activation, 'partial trigger entered text'
            if pressure in (0,.5,.85):review(preset+'-pressure-'+str(int(pressure*100)), keys+['routing-help'])
        live.send('trigger_value',hand=1,value=1)
        wait(lambda s: control(identifier)['enabled'] and ' / d [' in control('routing-help')['label'])
        sample(1)
        review(preset+'-pressure-100',keys+['routing-help'])
        sample(.7)  # Held above the existing release threshold: no second character.
        assert ' / d [' in control('routing-help')['label'], 'held trigger repeated a key'
        sample(0)
        key_checks_passed=True
    finally:
        live.send('trigger_value',hand=1,value=0);live.frame()
        (output/(preset+'-pressure.json')).write_text(json.dumps({'passed':False,'key_checks_passed':key_checks_passed,'samples':rows,'partial_activation':partial_activation},indent=2))
    click('routing:file-key-delete',preset)
    wait(lambda s: control('routing-help')['label']==before)
    # Cancel is also a raised keycap. Half pressure must not close the editor.
    cancel='routing:file-button-0';acquire(cancel,preset)
    origin=np.array(control(cancel)['position'])
    try:
        live.send('trigger_value',hand=1,value=.5)
        for _ in range(4):live.frame()
        assert live.state['routing_popup'][1]['open']
        travel=float(np.dot(origin-np.array(control(cancel)['position']),normal))
        assert abs(travel-.003*scale)<.00003
    finally:live.send('trigger_value',hand=1,value=0);live.frame()
    (output/(preset+'-pressure.json')).write_text(json.dumps({'passed':True,'samples':rows,'partial_activation':partial_activation,'cancel_half_travel_m':travel},indent=2))
