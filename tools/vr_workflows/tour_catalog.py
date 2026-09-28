"""Named, fixed VR tour entry points shared by Debug and command-line users."""
import json
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def catalog():
    groups = [
        {'id': 'overview', 'label': 'Overview', 'description': 'Both controllers and every sidebar tab.'},
        {'id': 'left', 'label': 'Left sidebar', 'description': 'One complete scrolling tour per desktop tab.'},
        {'id': 'right', 'label': 'Right sidebar', 'description': 'One complete scrolling tour per desktop tab.'},
        {'id': 'interaction', 'label': 'Controls & layout', 'description': 'Trackpad, pointer, cards, scrollbars and menu grips.'},
        {'id': 'dimensions', 'label': 'Properties · Dimensions', 'description': 'Placement, pinning, model transforms and desktop persistence.'},
        {'id': 'authoring', 'label': 'Tools · Authoring', 'description': 'Established desktop-to-VR and VR-first authoring demos.'},
    ]
    tours = []
    def add(identifier, group, title, description, args=(), module='menu_tour', runnable=True):
        tours.append(dict(id=identifier, group=group, title=title, description=description,
                          module=module, args=list(args), runnable=runnable))
    add('all', 'overview', 'Complete sidebar tour', 'Open every tab, scroll every page, and check controls and rendered pixels.')
    add('quick', 'overview', 'Quick tab overview', 'Show the first page of every tab. A short demo, not full coverage.', ['--quick'])
    for tab in json.loads((ROOT/'native/vr_viewer/sidebar_catalog.json').read_text())['tabs']:
        add(f"{tab['side']}-{tab['key']}", tab['side'], tab['label'] + ' menu',
            f"Tour every page of the {tab['side']} {tab['label']} tab; check disabled controls and pixels.",
            ['--tab', f"{tab['side']}:{tab['key']}"])
    add('representations', 'right', 'Visualization',
        'Switch the open design between Full, Cylinders, Ball & Stick and Stick. Reuses cached exports for unchanged designs. Validation tests all four controller profiles.', module='representation_tour')
    add('focus', 'interaction', 'Trackpad, pointer, cards & scrollbars',
        'Focus enabled and gray controls, activate triggers, collapse cards, scroll, and return to pointing.', ['--focus-checks'])
    add('grips', 'interaction', 'Move & resize menu borders',
        'Acquire both menu frames, reposition them and resize with two controllers.', ['--grip-checks'])
    add('dimensions', 'dimensions', 'Place & manage dimensions',
        'Pin and recall endpoints away from menus; test icons and model movement/scaling.', ['--dimension-checks'])
    add('persistence', 'dimensions', 'Save & reopen dimensions',
        'Use an isolated demo document to save measurements, reload its file and verify native endpoints.', module='dimensions_persistence_check')
    add('authoring', 'authoring', 'Desktop → VR and VR-first demo',
        'Requires the established owned idle viewer launch record. Replaces review parts only in the marked workspace/VR Testing folder. Run from a terminal.',
        module='demo', runnable=False)
    for tour in tours:
        tour['command'] = command(tour)
    return {'groups': groups, 'tours': tours}


def arguments(tour, validate=False):
    args = ['-m', 'tools.vr_workflows.'+tour['module'], *tour['args']]
    if tour['module'] == 'menu_tour':
        args += ['--validate', '--hold', '0', '--exit'] if validate else ['--preset', 'steady_fast']
    elif tour['module'] in ('dimensions_persistence_check', 'representation_tour'):
        if validate:
            args += ['--validate']
    return args


def command(tour, validate=False):
    args = ['uv', 'run', 'python', *arguments(tour, validate)]
    return shlex.join(args)
