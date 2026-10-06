"""Pointer scrolling for the left sidebar, whose pad now selects scope."""
import time
from tools.vr_motion.metrics import norm
from .profile_input import aim_orientation


def at_fraction(live, hand, fraction, identifier='scrollbar'):
    side = 'left' if hand == 0 else 'right'
    control = next(c for c in live.state['controls'] if c.get('sidebar') == side and c['id'] == identifier)
    # The endpoints clamp through the ordinary scrollbar hit/drag handler.
    target = [p + u * (.98 - 1.96 * fraction) for p, u in zip(control['position'], control['hit_half_up'])]
    origin = live.state['hands'][1]['position']
    live.send('pose', hand=1, position=origin, orientation=aim_orientation(origin, target))
    live.frame()
    live.button('trigger', hand=1)
    live.frame()


def page(live, hand, direction):
    state = live.state['sidebars'][hand]
    rows, total = state['page_rows'], state['total']
    if total <= rows:
        return
    last = (total - 1) // rows
    wanted = max(0, min(last, (state['offset'] // rows) + direction))
    side = 'left' if hand == 0 else 'right'
    control = next(c for c in live.state['controls'] if c.get('sidebar') == side and c['id'] == 'scrollbar')
    height = 2 * norm(control['hit_half_up']) / state['scale']
    thumb = max(.085 / height, rows / total)
    fraction = .5 + (wanted / last - .5) * (1 - thumb)
    at_fraction(live, hand, (.5 + (fraction - .5) / .98))
    time.sleep(.25)
    live.frame()
    assert live.state['sidebars'][hand]['offset'] == wanted * rows


def reveal_result(live, target):
    """Find a result through its own rail; job and view counts are independent."""
    views = target.startswith('sim:v:')
    rail = 'sim:scroll:views' if views else 'sim:scroll:jobs'
    prefix = 'sim:v:' if views else 'sim:j:'
    wanted = int(target.split(':')[2])
    low, high = 0., 1.
    for _ in range(16):
        if any(c['id'] == target for c in live.state['controls']):
            return
        fraction = (low + high) / 2
        at_fraction(live, 0, fraction, rail)
        indices = [int(c['id'].split(':')[2]) for c in live.state['controls']
                   if c['id'].startswith(prefix)]
        if not indices:
            break
        if wanted < min(indices):
            high = fraction
        elif wanted > max(indices):
            low = fraction
        else:
            break
    if not any(c['id'] == target for c in live.state['controls']):
        raise RuntimeError('Result control missing: ' + target)
