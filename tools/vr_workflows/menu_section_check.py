"""Exercise desktop card titles through both real VR input routes."""
from .menu_focus_check import pad, seek, capture
from .menu_tour import click, scroll_page


def run(live, catalog, output, preset, trials):
    checks = {}
    for hand, key in ((0, 'feature-log'), (1, 'visualization')):
        click(live, hand, 'tab:' + key, preset, trials)
        while live.state['sidebars'][hand]['offset']:
            scroll_page(live, hand, -1)
        tab = next(t for t in catalog['tabs'] if t['key'] == key)
        header = next(r for r in tab['rows'] if r['kind'] == 'section'
                      and any(r['id'] in child.get('parents', []) for child in tab['rows']))
        # Both Surface presets share one native row; the detail alias is never rendered.
        children = {r['id'] for r in tab['rows'] if header['id'] in r.get('parents', [])
                    and r['id'] != 'menu-view-surface-detail'}
        original = live.state['sidebars'][hand]['total']
        other = dict(live.state['sidebars'][1-hand])
        before = {k: live.state.get(k) for k in ('tool_sequence', 'scene_revision', 'representation')}
        if hand == 1:
            head = live.state['head_position']
            live.send('pose', hand=hand, position=[head[0], head[1]-.2, head[2]], orientation=[0, 1, 0, 0])
            pad(live, hand)
            seek(live, hand, header['id'])
            live.button('trigger', hand=hand)
            state = live.state['sidebars'][hand]
            assert header['id'] in state['collapsed_sections']
            assert state['total'] == original-len(children)
            assert state['focus_id'] == header['id']
            assert not children.intersection(c['id'] for c in live.state['controls'] if c.get('sidebar') == tab['side'])
            assert live.state['sidebars'][1-hand]['collapsed_sections'] == other['collapsed_sections']
            capture(live, output, f'{hand}-card-collapsed')
            live.button('trigger', hand=hand)
            assert live.state['sidebars'][hand]['total'] == original
            assert header['id'] not in live.state['sidebars'][hand]['collapsed_sections']
            capture(live, output, f'{hand}-card-expanded')
            pad(live, hand)  # Return to pointing before the profile-driven reaches.
        click(live, hand, header['id'], preset, trials)
        assert header['id'] in live.state['sidebars'][hand]['collapsed_sections']
        click(live, hand, header['id'], preset, trials)
        assert live.state['sidebars'][hand]['total'] == original
        assert before == {k: live.state.get(k) for k in before}
        checks[f'{hand}_card_pointer' + ('_and_trackpad' if hand else '')] = True
    # Leave the established focus checks at their initial tabs.
    click(live, 0, 'tab:feature-log', preset, trials)
    click(live, 1, 'tab:properties', preset, trials)
    return checks
