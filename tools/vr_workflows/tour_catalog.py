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
        {'id': 'view-volumes', 'label': 'View Volumes', 'description': 'Create and manage square/hex volumes, trigger-grab, resize, and save.'},
        {'id': 'authoring', 'label': 'Tools · Authoring', 'description': 'Modeling tools, end edits, scissors and edit history.'},
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
        'Switch the open design between all eleven desktop representations, including Hull, Surface, mrDNA and oxDNA. Reuses cached exports for unchanged designs. Validation tests all four controller profiles.', module='representation_tour')
    add('representation-colors', 'right', 'Representation colors',
        'Quick pass through all eleven styles and both coloring pages. Checks enabled/gray controls and rendered pixels; not the full switching matrix.', ['--cycle'], module='representation_tour')
    add('focus', 'interaction', 'Trackpad, pointer, cards & scrollbars',
        'Check bounded columns and lateral navigation, focus gray controls, activate triggers, collapse cards, scroll, and return to pointing.', ['--focus-checks'])
    add('grips', 'interaction', 'Move & resize menu borders',
        'Acquire both menu frames, reposition them and resize with two controllers.', ['--grip-checks'])
    add('dimensions', 'dimensions', 'Place & manage dimensions',
        'Pin and recall endpoints away from menus; test icons and model movement/scaling.', ['--dimension-checks'])
    add('persistence', 'dimensions', 'Save & reopen dimensions',
        'Use an isolated demo document to save measurements, reload its file and verify native endpoints.', module='dimensions_persistence_check')
    add('view-volumes', 'view-volumes', 'View volumes',
        'Isolated demo part: create square and hex volumes, show/hide, enable/delete, trigger move/rotate, two-hand resize, and grip the scene. Validation runs all four motion profiles.', module='view_volumes_check')
    add('extrude', 'authoring', 'Extrude a 6HB and inspect a volume',
        'Creates a new isolated part; paints a honeycomb ring, zooms the lattice with interior grips, moves/resizes its window, and uses the length wheel. Compares local volume representations. Validation covers honeycomb and square parts with all four motion profiles.', module='extrude_tour')
    add('view-tools', 'right', 'Left-hand view tools',
        'Equip the two-column desktop-icon panel with the left quiver gesture and exercise every view toggle in native stereo.', module='view_tools_tour')
    add('nick', 'authoring', 'Nick with scissors, Undo and Redo',
        'Equip/stow scissors with a behind-head reach, close them with analog trigger pressure, preview the glowing bond, click to nick, then use radial Undo and Redo. Validation uses all four motion profiles.', module='nick_tour')
    add('ligate', 'authoring', 'Ligate ends with the radius wheel',
        'Select Ligate through the four-volume wheel, stretch a preview from either end polarity, reject incompatible ends, release to create a forced ligation and verify Undo. Validation uses all four motion profiles.', module='ligation_tour')
    add('end-resize', 'authoring', 'Resize selected ends',
        'Trigger grab the selected end arrow, pull to resize, release to save, and verify one-step desktop Undo. Validation uses all four controller profiles.', module='end_resize_tour')
    for target in ('cluster','overhang','base'):
        add('move-'+target, 'authoring', 'Move / Rotate '+target,
            'Generated isolated part: trigger translate/rotate, exact target persistence and Undo. Validation uses all four controller profiles.',
            ['--target',target], module='move_tour')
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
    elif tour['module'] == 'view_volumes_check':
        args += ['--validate'] if validate else ['--demo']
    elif tour['module'] in ('dimensions_persistence_check', 'representation_tour', 'extrude_tour', 'move_tour', 'end_resize_tour', 'ligation_tour', 'nick_tour', 'view_tools_tour'):
        if validate:
            args += ['--validate']
    return args


def command(tour, validate=False):
    args = ['uv', 'run', 'python', *arguments(tour, validate)]
    return shlex.join(args)
