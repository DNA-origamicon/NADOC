"""Controller navigation through the current sidebars and tool panels."""


def sidebar_click(live, click, identifier, hand=1):
    """Find a sidebar control by identity; retain the caller's input driver."""
    from tools.vr_workflows.menu_tour import scroll_page

    side = 'left' if hand == 0 else 'right'
    if not live.state['sidebars'][hand]['open']:
        live.button('menu', hand=hand)
        live.frame()
    def target():
        return next((c for c in live.state['controls']
                     if c.get('sidebar') == side and c.get('id') == identifier), None)
    if target() is None and identifier.startswith('tab:'):
        # Dedicated tool panels replace the tab strip until Return is selected.
        back = next((c for c in live.state['controls']
                     if c.get('sidebar') == side and c.get('id', '').endswith(':back')), None)
        if back is not None:
            click(back['label'])
    if target() is None:
        while live.state['sidebars'][hand]['offset']:
            scroll_page(live, hand, -1)
    for _ in range(100):
        control = target()
        if control is not None:
            click(control['label'])
            return
        before = live.state['sidebars'][hand]['offset']
        scroll_page(live, hand, 1)
        if before == live.state['sidebars'][hand]['offset']:
            break
    raise RuntimeError('Missing sidebar control: ' + identifier)


def activate_extrude(live, click, output, *, preserve_selection=False):
    before = (live.state.get('selection_kind'), tuple(live.state.get('owner_tokens', [])))
    if preserve_selection and (before[0] != 'end' or not before[1]):
        raise RuntimeError('End extrusion requires an identified selected end')
    hand = live.state['hands'][1]
    live.send('pose', hand=0, position=hand['position'], orientation=hand['orientation_xyzw'])
    live.frame()
    sidebar_click(live, click, 'tab:tools')
    # Inspect resets a paint draft but must not discard a selected end target.
    if not preserve_selection and live.state['tool'] != 'inspect':
        sidebar_click(live, click, 'tool-inspect')
    sidebar_click(live, click, 'tool-extrude')
    live.capture_to(output/f"menu-activated-{live.state['command_sequence']}", discard_source=True)
    if preserve_selection:
        after = (live.state.get('selection_kind'), tuple(live.state.get('owner_tokens', [])))
        if after != before:
            raise RuntimeError('Menu navigation changed the selected end')
    elif not live.state['extrude']['open']:
        raise RuntimeError('Sidebar Extrude did not open the paint tablet')
