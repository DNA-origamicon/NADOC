"""Ordinary menu navigation shared by painted and selected-end authoring."""


def activate_extrude(live, click, output, *, preserve_selection=False):
    before = (live.state.get('selection_kind'), tuple(live.state.get('owner_tokens', [])))
    if preserve_selection and (before[0] != 'end' or not before[1]):
        raise RuntimeError('End extrusion requires an identified selected end')
    hand = live.state['hands'][1]
    live.send('pose', hand=0, position=hand['position'], orientation=hand['orientation_xyzw'])
    live.frame()
    if live.state['menu'] == 'closed':
        live.button('menu', hand=0)
        live.frame()
    labels = {c['label'] for c in live.state['controls']}
    if 'BACK TO TOOLS' in labels:
        click('BACK TO TOOLS')
    elif 'TOOLS' in labels:
        click('TOOLS')
    # Inspect resets the tool for a fresh paint draft, but can discard an end target.
    if not preserve_selection and live.state['tool'] != 'inspect':
        click('INSPECT')
    click('EXTRUDE')
    live.capture_to(output/f"menu-activated-{live.state['command_sequence']}", discard_source=True)
    if preserve_selection:
        after = (live.state.get('selection_kind'), tuple(live.state.get('owner_tokens', [])))
        if after != before:
            raise RuntimeError('Menu navigation changed the selected end')
    elif not live.state['extrude']['open']:
        raise RuntimeError('Menu Extrude did not open the paint tablet')
