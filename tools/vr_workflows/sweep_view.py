"""Eye-relative Sweep tour presentation through ordinary controller operations."""
import json
import subprocess
import numpy as np
from scipy.spatial.transform import Rotation
from PIL import Image
from tools.vr_motion.visual_checks import project


def capture_tracked(live, directory, wait_ready):
    """One retained retry for tracking loss outside held/measured gestures."""
    files = ['left.png', 'right.png', 'mirror.png', 'evidence.json']
    evidence, _ = live.capture_to(directory, files=files, discard_source=True)
    if evidence['state']['view_state_flags'] & 15 == 15:
        return evidence
    state = evidence['state']
    held = any(hand.get('trigger') or hand.get('grip') for hand in state.get('hands', []))
    if held:
        raise AssertionError('Headset tracking lost during a held gesture; do not retry motion')
    rejected = directory.with_name(directory.name+'-untracked')
    directory.rename(rejected)
    print('Tracking lost at review boundary; retained '+str(rejected), flush=True)
    wait_ready(rejected)
    evidence, _ = live.capture_to(directory, files=files, discard_source=True)
    assert evidence['state']['view_state_flags'] & 15 == 15, 'Headset tracking did not recover for capture'
    return evidence


def dismiss_dashboard(output):
    """Use SteamVR's shipped command once; never change runtime preferences."""
    from scripts.vr_atomistic_diagnostics import _find_vrcmd
    from tools.vr_capture.launch_compositor import process_ids
    output.mkdir(parents=True, exist_ok=True)
    report = {'operation': 'vrcmd --hidedashboard', 'settings_changed': False}
    if not process_ids('vrserver'):
        report['skipped'] = 'SteamVR is not running; do not launch it during cleanup'
        (output/'dashboard-dismissal.json').write_text(json.dumps(report, indent=2))
        return report
    try:
        command = _find_vrcmd(None)
        result = subprocess.run([str(command), '--hidedashboard'], capture_output=True,
                                text=True, timeout=5, check=False)
        report.update(command=str(command), returncode=result.returncode,
                      stdout=result.stdout[-2000:], stderr=result.stderr[-2000:])
    except (OSError, subprocess.TimeoutExpired) as error:
        report['error'] = str(error)
    (output/'dashboard-dismissal.json').write_text(json.dumps(report, indent=2))
    # Command success is not readiness; the caller still observes tracked focus.
    return report


def check_draft_pixels(directory, evidence):
    """Each fitted knot must be in frame with colored Sweep pixels in both eyes."""
    points = evidence['state']['sweep']['points_world']
    assert len(points) >= 2, 'No fitted Sweep knots'
    rows = []
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB')).astype(int)
        for index, point in enumerate(points):
            pixel = project(point, eye)
            count = 0
            if pixel is not None:
                x, y = map(int, pixel)
                if 12 <= x < eye['width']-12 and 12 <= y < eye['height']-12:
                    patch = rgb[y-12:y+13, x-12:x+13]
                    # Green knots, yellow selection, cyan section, red warning.
                    count = int(((patch.max(axis=2)>130) & (np.ptp(patch, axis=2)>60)).sum())
            rows.append({'eye': eye['eye'], 'knot': index, 'colored_pixels': count})
    assert len(evidence['eyes']) == 2 and all(row['colored_pixels'] >= 3 for row in rows), ('Sweep knots not visible', rows)
    return {'passed': True, 'knots': rows}


def sidebar_wrist(head, eye_orientation, wrist_position, wrist_orientation, panel_position, panel_orientation):
    """Invert the observed wrist-to-panel transform, including production tilt."""
    wrist = Rotation.from_quat(wrist_orientation)
    panel = Rotation.from_quat(panel_orientation)
    facing = Rotation.from_quat(eye_orientation)
    local_offset = wrist.inv().apply(np.asarray(panel_position)-wrist_position)
    desired = facing * (wrist.inv()*panel).inv()
    center = np.asarray(head)+facing.apply([.27, 0, -.65])
    return (center-desired.apply(local_offset)).tolist(), desired.as_quat().tolist()


def open_sidebar_in_view(live, output, calibration=None):
    """Fresh tracked eyes, observed panel placement, then normal menu reopening."""
    output.mkdir(parents=True, exist_ok=False)
    anchor, _ = live.capture_to(output/'eyes', files=['evidence.json'], discard_source=True)
    assert anchor['state']['view_state_flags'] & 15 == 15, 'Cannot place menus without tracked eyes'
    q = anchor['eyes'][0]['orientation_xyzw']
    head = np.mean([eye['position'] for eye in anchor['eyes']], axis=0)
    if live.state['sidebars'][1]['open']:
        live.button('menu', hand=1)
    if calibration is None:
        calibration = {}
    calibrated_now = not calibration
    if calibrated_now:
        position = (head+Rotation.from_quat(q).apply([.27, 0, -.25])).tolist()
        live.send('pose', hand=1, position=position, orientation=q); live.frame()
        live.button('menu', hand=1); live.frame()
        panel = live.state['sidebars'][1]
        # Learn production tilt/offset once. Subsequent openings go straight to
        # the final pose, rather than flashing near then moving away each time.
        control = next(c for c in live.state['controls'] if c.get('sidebar') == 'right')
        right = np.asarray(control['hit_half_right']); right = right/np.linalg.norm(right)
        up = np.asarray(control['hit_half_up']); up = up/np.linalg.norm(up)
        orientation = Rotation.from_matrix(np.column_stack([right, up, np.cross(right, up)])).as_quat()
        calibration.update(wrist_position=position, wrist_orientation=q,
                           panel_position=panel['position'], panel_orientation=orientation.tolist())
        live.button('menu', hand=1)
    position, orientation = sidebar_wrist(head, q, **calibration)
    live.send('pose', hand=1, position=position, orientation=orientation); live.frame()
    live.button('menu', hand=1); live.frame()
    (output/'placement.json').write_text(json.dumps({
        'head': head.tolist(), 'eye_orientation': q, 'wrist': position,
        'wrist_orientation': orientation, 'panel': live.state['sidebars'][1],
        'calibrated_now': calibrated_now,
        'method': 'ordinary menu reopening; observed wrist-to-panel transform'}, indent=2))
    return head, q


def fullscreen_mirror(live, output):
    """Request fullscreen for only the owned X11 mirror, then verify WM state."""
    import ctypes as c
    import ctypes.util
    import time
    from tools.vr_motion.desktop_check import viewer_window, reveal_viewer
    window = int(viewer_window(live), 16)
    x = c.CDLL(ctypes.util.find_library('X11'))
    x.XOpenDisplay.argtypes = [c.c_char_p]; x.XOpenDisplay.restype = c.c_void_p
    x.XDefaultRootWindow.argtypes = [c.c_void_p]; x.XDefaultRootWindow.restype = c.c_ulong
    x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]; x.XInternAtom.restype = c.c_ulong
    class Data(c.Union):
        _fields_ = [('b', c.c_char*20), ('s', c.c_short*10), ('l', c.c_long*5)]
    class Message(c.Structure):
        _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                    ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                    ('format', c.c_int), ('data', Data)]
    class Event(c.Union):
        _fields_ = [('client', Message), ('pad', c.c_long*24)]
    x.XSendEvent.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(Event)]
    x.XSync.argtypes = [c.c_void_p, c.c_int]; x.XCloseDisplay.argtypes = [c.c_void_p]
    display = x.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Cannot open desktop display for fullscreen mirror')
    try:
        event = Event(); event.client.type = 33; event.client.send_event = 1
        event.client.display = display; event.client.window = window; event.client.format = 32
        event.client.message_type = x.XInternAtom(display, b'_NET_WM_STATE', False)
        event.client.data.l[0] = 1  # add, not toggle
        event.client.data.l[1] = x.XInternAtom(display, b'_NET_WM_STATE_FULLSCREEN', False)
        event.client.data.l[3] = 2  # application requesting on behalf of the user
        x.XSendEvent(display, x.XDefaultRootWindow(display), False, (1<<20)|(1<<19), c.byref(event))
        x.XSync(display, 0)
    finally:
        x.XCloseDisplay(display)
    reveal_viewer(live)
    deadline = time.monotonic()+3
    while True:
        state = subprocess.check_output(['xprop', '-id', hex(window), '_NET_WM_STATE'], text=True, timeout=3)
        if '_NET_WM_STATE_FULLSCREEN' in state:
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Window manager did not fullscreen the headset mirror')
        time.sleep(.1)
    live.frame()
    (output/'mirror-window.json').write_text(json.dumps({'window': hex(window), 'state': state,
        'geometry': subprocess.check_output(['xwininfo', '-id', hex(window)], text=True, timeout=3)}, indent=2))


def enlarge_sidebar(live, output):
    """Declared presentation setup: ordinary two-hand border resize, once."""
    panel = live.state['sidebars'][1]
    if panel['scale'] >= .649:
        return
    before = panel['scale']
    scene = live.state['presentation']['model_to_tracking_rows']
    positions = [np.asarray(p) for p in panel['grip_targets'][:2]]
    midpoint = (positions[0]+positions[1])*.5
    try:
        for hand in (0, 1):
            live.send('pose', hand=hand, position=(positions[hand]+[0,0,.12]).tolist(), orientation=[0,0,0,1])
        live.frame()
        for hand in (0, 1):
            live.send('button', hand=hand, button='grip', pressed=True); live.frame()
        assert live.state['sidebars'][1]['grip_state'] == 'resizing'
        for hand in (0, 1):
            position = midpoint+(positions[hand]-midpoint)*(.65/before)
            live.send('pose', hand=hand, position=(position+[0,0,.12]).tolist(), orientation=[0,0,0,1])
        live.frame()
    finally:
        for hand in (0, 1):
            live.send('button', hand=hand, button='grip', pressed=False)
        live.frame()
    assert abs(live.state['sidebars'][1]['scale']-.65) < .002
    assert live.state['presentation']['model_to_tracking_rows'] == scene
    (output/'resize.json').write_text(json.dumps({'method': 'ordinary two-hand border resize before measured reaches',
        'before_scale': before, 'after_scale': live.state['sidebars'][1]['scale'],
        'scene_unchanged': True}, indent=2))
