"""Named, fixed VR tour entry points shared by Debug and command-line users."""
import json
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def catalog():
    groups = [
        {'id': 'components', 'label': 'Component evaluations', 'description': 'Shared desktop and native VR component gallery.'},
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
    add('card-gallery', 'components', 'Cards and lists',
        'Six expandable card and list styles with selectable children.', ['--component', 'cards'], module='component_gallery_tour')
    add('button-gallery', 'components', 'Button styles',
        'Six button surfaces inspired by MRTK, visionOS, Material and Blender. Compare hover, press travel, selected and disabled states in the same desktop/VR gallery.', ['--component','buttons'], module='component_gallery_tour')
    add('thumbwheel-gallery', 'components', 'Ridged thumbwheels',
        'Compare 20%, 35% and 50% exposed wheels for ranges 0-10, 0-100 and 0-1000. Interactive desktop needs no headset; VR uses the same mesh and inertia. Play demo, reset, or grab any wheel.', module='component_gallery_tour')
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
    add('simulations', 'left', 'Simulation results · 2hb_1xT',
        'Desktop engine tabs, touchpad job/result navigation and existing static visualizations for 2hb_1xT. Copies job metadata/caches into a temporary workspace; trajectories are excluded. Validation runs all four motion profiles.', module='simulation_tour')
    add('backend-lifetime', 'interaction', 'Backend shutdown closes VR',
        'Launch an isolated backend and empty VR viewer; terminate only that backend and require viewer exit and sidecar cleanup.', module='backend_lifecycle_check')
    add('tool-frame-audit', 'authoring', 'Tools across representations · frame audit',
        'Long isolated campaign: existing authoring fixtures in Full, Stick, Ball & Stick and Quick Surface. Records failed cases, CPU calculation counts and compositor timing. Validation uses all four motion profiles. Desktop drawing defaults off with browser trace evidence (--desktop-rendering on overrides it); Move workflows also check the Desktop 3D during VR toggle and automatic desktop restoration.', module='tool_frame_audit')
    add('frame-audit', 'interaction', 'VR frame calculation audit',
        'Private 24HB: Full, Stick, Ball & Stick and Quick Surface idle/grip CPU phases, submission cadence and compositor timing. Validation uses all four motion profiles; authoring tools are separate.', module='frame_audit_tour')
    add('representation-motion', 'interaction', 'Detailed representations · grip motion',
        'Real Stick and Ball & Stick loads, then whole-model broadside inspection at 10x scale, grip translation/rotation, and 30/60/120 degree-per-second yaw sweeps. Retains input cadence and submitted stereo geometry; speed sweeps are separate from the four unchanged validation profiles. Verifies background desktop rendering yields to native VR while synchronization continues. Head tracking is never overridden.', ['--motion'], module='browser_representation_tour')
    add('loading-performance', 'interaction', 'Representation loading frame delivery',
        'Real browser/controller loads with native CPU phases and read-only SteamVR compositor timing. Checks p99 cadence, long frame gaps and dropped-frame rate; validation covers all four motion presets. Uses the optional openvr Python binding through uv. Private test documents are cleaned up.', ['--profile'], module='browser_representation_tour')
    add('browser-representations', 'interaction', 'Browser-to-headset representation loading',
        'Open the current part in an automated browser, launch VR through its UI, select all eleven representations with ScryWrite, and require 100% plus visible model pixels in both eyes. Validation repeats Full/Surface/Cylinders under all four motion presets. Also checks one-row touchpad scrolling and captures nested menu indentation. Stick and Ball & Stick use the shared shadow renderer. Retains native CPU phase timings and loading samples for loading_profile; checks actual activation after budgeted GPU uploads. No mocked desktop responder.', module='browser_representation_tour')
    add('representation-loading', 'interaction', 'Full startup, loading visibility and representation progress',
        'Start with Full, select other representations with real controller inputs, and verify loading progress plus retained model pixels in both eyes, including the point fallback. Validation uses all four motion profiles and covers Surface to Stick.', ['--representations'], module='startup_tour')
    add('startup', 'interaction', 'Cold startup and headset loading progress',
        'Launch a read-only private copy of 24HB through the normal launch route. Capture loading and first model stereo frames and verify advancing headset frames during natural-only export (no Quick Expand).', module='startup_tour')
    add('menu-depth', 'interaction', 'Menu blur and controller depth',
        'Move the controller stick and sphere in front of and behind a menu. Check sharp foreground pixels and behind-menu occlusion in both eyes, across all four motion profiles.', ['--depth-checks'])
    add('room-ui', 'interaction', 'Frosted menus & SteamVR floor',
        'Barely visible white glass, subtle button tints and stereo background blur, a calibrated floor grid and SteamVR play-area outline. Checks native pixels and all four motion profiles.', ['--room-checks'])
    add('focus', 'interaction', 'Trackpad, pointer, cards & scrollbars',
        'Check bounded columns and lateral navigation, focus gray controls, activate triggers, collapse cards, scroll, and return to pointing.', ['--focus-checks'])
    add('remote-borders', 'interaction', 'Menu controls · distant trigger grab & resize',
        'Hold a border with a fixed controller-to-border ray; move and rotate, then hold the other trigger on the border to resize. Also checks double-trigger resize and stereo feedback.', ['--remote-checks'])
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
    add('presence-ui', 'left', 'VR menus and tools in guest view',
        'Real guest receives native menu labels, desktop icons, controller guides and scissors; checks closing panels and hiding presence.', module='presence_ui_tour')
    add('avatar', 'left', 'VR presenter model',
        'Real local guest sees tracked headset, estimated arms, gestures, inverse model scaling and the Show VR model toggle. No public hosting.', module='avatar_tour')
    add('qr-calibration', 'left', 'Calibrate QR code · Vive camera',
        'Real edge-filtered camera preview and cancellation through Share controls. Software validates QR pose and origin snapping separately; physical target alignment requires on-site review.', ['--qr-checks'])
    add('share', 'left', 'Share presenter controls',
        'Control a desktop-started presentation from the left menu. Isolated simulated hosting; creates no public link. All four controller profiles in validation.', module='share_tour')
    add('view-tools', 'right', 'Left-hand view tools',
        'Equip the two-column desktop-icon panel with the left quiver gesture and exercise the ten supported view toggles in native stereo; Quick Expand is excluded.', module='view_tools_tour')
    add('nick', 'authoring', 'Nick with scissors, Undo and Redo',
        'Equip/stow scissors with a behind-head reach, close them with analog trigger pressure, preview the glowing bond, click to nick, then use radial Undo and Redo. Validation uses all four motion profiles.', module='nick_tour')
    add('ligate', 'authoring', 'Ligate ends with the radius wheel',
        'Select Ligate through the four-volume wheel, stretch a preview from either end polarity, reject incompatible ends, release to create a forced ligation and verify Undo. Validation uses all four motion profiles.', module='ligation_tour')
    add('twist', 'authoring', 'Twist between two planes',
        'Isolated part: plane picking, rotation handle, signed amount wheel, unit conversion, Confirm, save/reopen and Undo. Tests all four motion profiles.', module='twist_tour')
    add('bend', 'authoring', 'Bend between two planes',
        'Isolated part: trigger-held plane picking, both end handles, angle/direction/radius wheels, Confirm, desktop feature log, save/reopen and Undo. Validation runs all four motion profiles in one viewer session.', module='bend_tour')
    add('end-resize', 'authoring', 'Resize selected ends',
        'Trigger grab the selected end arrow, pull to resize, release to save, and verify one-step desktop Undo. Validation uses all four controller profiles.', module='end_resize_tour')
    add('move-preview-renderer', 'authoring', 'Move / Rotate · renderer regression',
        'No headset required: compare packed previews with the original rebuild, including boundary bonds, highlights, Cancel, commit, Undo and style changes. Saved-scene timing is available through --scene-dir on the command line.', module='move_preview_check')
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
    elif tour['module'] in ('tool_frame_audit', 'frame_audit_tour', 'component_gallery_tour', 'browser_representation_tour', 'startup_tour', 'simulation_tour', 'dimensions_persistence_check', 'representation_tour', 'extrude_tour', 'bend_tour', 'twist_tour', 'move_tour', 'end_resize_tour', 'ligation_tour', 'nick_tour', 'view_tools_tour', 'share_tour', 'avatar_tour', 'presence_ui_tour'):
        if validate:
            args += ['--validate']
    return args


def command(tour, validate=False):
    args = ['uv', 'run', 'python', *arguments(tour, validate)]
    return shlex.join(args)
