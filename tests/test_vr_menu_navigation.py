from pathlib import Path
import pytest
from tools.vr_workflows.menu_navigation import activate_extrude


class Menu:
    def __init__(self, selected=False, opened=False):
        self.state = {'selection_kind':'end' if selected else 'none',
            'owner_tokens':['end:identified'] if selected else [],
            'hands':[{}, {'position':[1,2,3], 'orientation_xyzw':[0,0,0,1]}],
            'menu':'sidebars', 'tool':'extrude', 'controls':[], 'command_sequence':0,
            'sidebars':[{'open':True}, {'open':opened, 'tab':'properties', 'offset':0}],
            'extrude':{'open':False}}
        self.clicked = []
        self.buttons = []
        if opened:
            self.publish_controls()
    def publish_controls(self):
        self.state['controls'] = [{'sidebar':'right', 'id':identifier, 'label':label}
            for identifier, label in [('tab:tools','RIGHT / Tools'),
                ('tool-inspect','RIGHT / Inspect'), ('tool-extrude','RIGHT / Extrude')]]
    def send(self, action, **kwargs):
        assert action == 'pose' and kwargs['hand'] == 0
    def frame(self):
        self.state['command_sequence'] += 1
    def button(self, button, **kwargs):
        assert button == 'menu' and kwargs['hand'] == 1
        self.buttons.append((button, kwargs['hand']))
        self.state['sidebars'][1]['open'] = True
        self.publish_controls()
    def capture_to(self, *args, **kwargs):
        pass
    def click(self, label):
        self.clicked.append(label)
        if label == 'RIGHT / Tools':
            self.state['sidebars'][1]['tab'] = 'tools'
        if label == 'RIGHT / Inspect':
            self.state.update(selection_kind='none',owner_tokens=[],tool='inspect')
        if label == 'RIGHT / Extrude':
            self.state['tool'] = 'extrude'
            self.state['sidebars'][1]['tab'] = 'extrude'
            self.state['extrude']['open'] = self.state['selection_kind'] == 'none'


@pytest.mark.parametrize('opened', [False, True])
def test_selected_end_survives_sidebar_navigation(opened):
    live = Menu(selected=True, opened=opened)
    activate_extrude(live,live.click,Path('.'),preserve_selection=True)
    assert live.clicked == ['RIGHT / Tools','RIGHT / Extrude']
    assert live.state['owner_tokens'] == ['end:identified']
    assert not live.state['extrude']['open']
    assert live.state['sidebars'][0]['open']
    assert live.buttons == ([] if opened else [('menu',1)])


def test_fresh_paint_resets_tool_and_opens_tablet():
    live = Menu()
    activate_extrude(live,live.click,Path('.'))
    assert live.clicked == ['RIGHT / Tools','RIGHT / Inspect','RIGHT / Extrude']
    assert live.state['extrude']['open']
    assert live.state['sidebars'][1]['tab'] == 'extrude'


def test_end_requires_identity_and_detects_navigation_losing_it():
    live = Menu()
    with pytest.raises(RuntimeError,match='identified selected end'):
        activate_extrude(live,live.click,Path('.'),preserve_selection=True)
    assert live.clicked == []
    live = Menu(selected=True)
    def losing_click(label):
        live.click(label)
        live.state['owner_tokens'] = []
    with pytest.raises(RuntimeError,match='changed the selected end'):
        activate_extrude(live,losing_click,Path('.'),preserve_selection=True)


def test_selected_end_returns_from_tool_panel_before_changing_tabs():
    live = Menu(selected=True, opened=True)
    live.state['sidebars'][1]['tab'] = 'extrude'
    live.state['controls'] = [{'sidebar':'right','id':'extrude:back','label':'RIGHT / Return'}]
    def click(label):
        live.click(label)
        if label == 'RIGHT / Return':
            live.state['sidebars'][1]['tab'] = 'tools'
            live.publish_controls()
    activate_extrude(live,click,Path('.'),preserve_selection=True)
    assert live.clicked == ['RIGHT / Return','RIGHT / Tools','RIGHT / Extrude']
    assert live.state['owner_tokens'] == ['end:identified']
