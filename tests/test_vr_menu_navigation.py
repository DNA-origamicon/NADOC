from pathlib import Path
import pytest
from tools.vr_workflows.menu_navigation import activate_extrude


class Menu:
    def __init__(self, selected=False):
        self.state = {'selection_kind':'end' if selected else 'none',
            'owner_tokens':['end:identified'] if selected else [],
            'hands':[{}, {'position':[1,2,3], 'orientation_xyzw':[0,0,0,1]}],
            'menu':'closed', 'tool':'extrude', 'controls':[], 'command_sequence':0,
            'extrude':{'open':False}}
        self.clicked = []
    def send(self, action, **kwargs):
        assert action == 'pose' and kwargs['hand'] == 0
    def frame(self):
        self.state['command_sequence'] += 1
    def button(self, button, **kwargs):
        assert button == 'menu'
        self.state.update(menu='options',controls=[{'label':'TOOLS'}])
    def capture_to(self, *args, **kwargs):
        pass
    def click(self, label):
        self.clicked.append(label)
        if label == 'INSPECT':
            self.state.update(selection_kind='none',owner_tokens=[],tool='inspect')
        if label == 'EXTRUDE':
            self.state.update(tool='extrude',menu='tool_config')
            self.state['extrude']['open'] = self.state['selection_kind'] == 'none'


def test_selected_end_survives_ordinary_menu_navigation():
    live = Menu(selected=True)
    activate_extrude(live,live.click,Path('.'),preserve_selection=True)
    assert live.clicked == ['TOOLS','EXTRUDE']
    assert live.state['owner_tokens'] == ['end:identified']
    assert not live.state['extrude']['open']


def test_fresh_paint_resets_tool_and_opens_tablet():
    live = Menu()
    activate_extrude(live,live.click,Path('.'))
    assert live.clicked == ['TOOLS','INSPECT','EXTRUDE']
    assert live.state['extrude']['open']


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
