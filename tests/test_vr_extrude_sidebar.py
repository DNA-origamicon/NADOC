from types import SimpleNamespace
import pytest
from tools.vr_workflows.extrude_sidebar import SidebarControls


def test_control_search_reaches_late_visualization_pages(monkeypatch,tmp_path):
    live=SimpleNamespace(state={'controls':[], 'sidebars':[{}, {'offset':0}]})
    def scroll(_live,hand,direction):
        assert hand==1
        panel=live.state['sidebars'][1]
        panel['offset']=max(0,min(80,panel['offset']+8*direction))
        live.state['controls']=[{'id':'volume-title'}] if panel['offset']==72 else []
    clicks=[]
    monkeypatch.setattr('tools.vr_workflows.extrude_sidebar.scroll_page',scroll)
    monkeypatch.setattr('tools.vr_workflows.extrude_sidebar.click',lambda *args:clicks.append(args[2]))
    SidebarControls(live,tmp_path,'steady_fast').click('volume-title')
    assert clicks==['volume-title']
    assert live.state['sidebars'][1]['offset']==72


def test_missing_control_stops_at_end_of_menu(monkeypatch,tmp_path):
    live=SimpleNamespace(state={'controls':[], 'sidebars':[{}, {'offset':0}]})
    monkeypatch.setattr('tools.vr_workflows.extrude_sidebar.scroll_page',lambda *args:None)
    with pytest.raises(RuntimeError,match='Missing sidebar control'):
        SidebarControls(live,tmp_path,'steady_fast').click('missing')
