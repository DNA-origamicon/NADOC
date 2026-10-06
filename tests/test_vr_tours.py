"""Debug launch catalog and process ownership; never start SteamVR in unit tests."""
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import routes_vr_tours as tours
from tools.vr_workflows.tour_catalog import catalog, arguments


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(tours, '_run', None)
    monkeypatch.setattr(tours, 'ROOT', tmp_path)
    monkeypatch.setattr(tours, '_viewer_active', lambda: False)
    # Keep the actual local-origin policy; only skip workstation capability probing.
    monkeypatch.setattr('backend.api.routes_vr._native_platform_reason', lambda: None)
    return TestClient(app, client=('127.0.0.1', 12345))


def test_catalog_covers_every_tab_and_distinguishes_partial_demo(client):
    import json
    from tools.vr_workflows.tour_catalog import ROOT
    result = client.get('/api/vr/tours').json()
    tabs = json.loads((ROOT/'native/vr_viewer/sidebar_catalog.json').read_text())['tabs']
    assert {f"{t['side']}-{t['key']}" for t in tabs} <= {t['id'] for t in result['tours']}
    assert 'not full coverage' in next(t for t in result['tours'] if t['id']=='quick')['description']
    assert not next(t for t in result['tours'] if t['id']=='authoring')['runnable']
    for tour in catalog()['tours']:
        if tour['module']=='menu_tour':
            assert '--validate' in arguments(tour, True)
            assert '--preset' in arguments(tour)


def test_launch_fixed_arguments_status_and_duplicate_guard(client, monkeypatch):
    process = Mock(pid=987654)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(tours.subprocess, 'Popen', popen)
    result = client.post('/api/vr/tours/start', json={'tour':'right-properties','mode':'validate'})
    assert result.status_code == 200, result.text
    assert result.json()['run']['status']=='running'
    args, kwargs = popen.call_args
    assert args[0][1:7] == ['-m','tools.vr_workflows.menu_tour','--tab','right:properties','--validate','--hold']
    assert kwargs['start_new_session'] and not kwargs.get('shell')
    assert client.post('/api/vr/tours/start',json={'tour':'all'}).status_code==409
    assert client.post('/api/vr/tours/stop/wrong-run').status_code==409
    process.poll.return_value = 1
    assert client.get('/api/vr/tours/status').json()['run']['status']=='failed'


def test_rejects_arbitrary_commands_and_active_viewers(client, monkeypatch):
    assert client.post('/api/vr/tours/start',json={'tour':'../../shell'}).status_code==400
    assert client.post('/api/vr/tours/start',json={'tour':'authoring'}).status_code==400
    assert client.post('/api/vr/tours/start',json={'tour':'all','mode':'shell'}).status_code==422
    monkeypatch.setattr(tours, '_viewer_active', lambda: True)
    assert client.post('/api/vr/tours/start',json={'tour':'all'}).status_code==409
    assert client.post('/api/vr/tours/start',json={'tour':'all'},headers={'Origin':'https://unrelated.example'}).status_code==403


def test_stop_only_signals_owned_group(monkeypatch):
    process = Mock(pid=123456)
    kill = Mock()
    monkeypatch.setattr(tours.os, 'killpg', kill)
    tours._stop_process(process)
    kill.assert_called_once_with(123456, tours.signal.SIGINT)
    process.wait.assert_called_once_with(timeout=15)


def test_shutdown_closes_only_the_owned_live_tour(monkeypatch):
    process = Mock(pid=123456)
    process.poll.return_value = None
    monkeypatch.setattr(tours, '_run', {'process': process, 'stopping': False})
    terminate = Mock()
    monkeypatch.setattr(tours, '_stop_process', terminate)
    tours.shutdown_tours()
    tours.shutdown_tours()
    terminate.assert_called_once_with(process)


@pytest.mark.parametrize("tour", ["representations", "representation-colors"])
def test_representation_launch_snapshots_current_document(client, monkeypatch, tour):
    from backend.api import state
    from pathlib import Path
    design = Mock()
    design.to_json.return_value = '{"unsaved": "current document"}'
    copied = Mock(return_value=(design, 42))
    monkeypatch.setattr(state, 'copy_doc_for_persist', copied)
    process = Mock(pid=987654)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(tours.subprocess, 'Popen', popen)
    response = client.post('/api/vr/tours/start', json={'tour':tour}, headers={'X-NADOC-Doc':'__test_current_tour'})
    assert response.status_code == 200, response.text
    copied.assert_called_once_with('__test_current_tour')
    argv = popen.call_args.args[0]
    source = Path(argv[argv.index('--design')+1])
    assert source.read_text() == design.to_json.return_value
    assert source.name == 'open-design.nadoc'


@pytest.mark.parametrize("tour", ["representations", "representation-colors"])
def test_representation_requires_open_individual_design(client, monkeypatch, tour):
    from backend.api import state
    monkeypatch.setattr(state, 'copy_doc_for_persist', lambda _: (None, 0))
    assert client.post('/api/vr/tours/start', json={'tour':tour}).status_code == 400
    assert client.post('/api/vr/tours/start', json={'tour':tour,'assembly_active':True}).status_code == 400

@pytest.mark.parametrize('mode,flag', [('demo','--demo'),('validate','--validate')])
def test_view_volume_tour_launches_isolated_workflow(client, monkeypatch, mode, flag):
    process=Mock(pid=987654);process.poll.return_value=None
    popen=Mock(return_value=process);monkeypatch.setattr(tours.subprocess,'Popen',popen)
    result=client.post('/api/vr/tours/start',json={'tour':'view-volumes','mode':mode})
    assert result.status_code==200,result.text
    argv=popen.call_args.args[0]
    assert argv[1:4]==['-m','tools.vr_workflows.view_volumes_check',flag]
    assert '--output' in argv and '--design' not in argv
    assert result.json()['run']['tour']=='view-volumes'


def test_fresh_extrude_tour_is_runnable_and_validation_has_no_workspace_reset():
    from tools.vr_workflows.tour_catalog import catalog, arguments
    tour = next(t for t in catalog()['tours'] if t['id'] == 'extrude')
    assert tour['runnable']
    assert arguments(tour, True) == ['-m', 'tools.vr_workflows.extrude_tour', '--validate']
    assert arguments(tour, False) == ['-m', 'tools.vr_workflows.extrude_tour']


def test_existing_slice_extrude_has_a_discoverable_isolated_validation():
    tour = next(t for t in catalog()['tours'] if t['id'] == 'extrude-slice')
    assert tour['runnable'] and tour['group'] == 'authoring'
    assert arguments(tour, True) == ['-m', 'tools.vr_workflows.extrude_tour',
                                     '--slice-reference', '--validate']


def test_move_rotate_has_a_demo_and_full_validation_for_each_scope():
    entries={tour['id']:tour for tour in catalog()['tours']}
    for target in ('cluster','overhang','base'):
        tour=entries['move-'+target]
        assert tour['runnable'] and tour['module']=='move_tour'
        assert arguments(tour)==['-m','tools.vr_workflows.move_tour','--target',target]
        assert arguments(tour,True)[-1]=='--validate'


@pytest.mark.parametrize('mode', ['demo', 'validate'])
def test_end_resize_tour_launches_isolated_workflow(client, monkeypatch, mode):
    process = Mock(pid=987654)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(tours.subprocess, 'Popen', popen)
    result = client.post('/api/vr/tours/start', json={'tour': 'end-resize', 'mode': mode})
    assert result.status_code == 200, result.text
    command = popen.call_args.args[0]
    assert 'tools.vr_workflows.end_resize_tour' in command
    assert ('--validate' in command) == (mode == 'validate')
    assert '--output' in command


@pytest.mark.parametrize('mode', ['demo', 'validate'])
@pytest.mark.parametrize('tool,module', [('twist','twist_tour'), ('bend','bend_tour'), ('ligate','ligation_tour'), ('nick','nick_tour'), ('edit-wheel-history','edit_wheel_history_tour'), ('view-tools','view_tools_tour'), ('share','share_tour'), ('avatar','avatar_tour'), ('presence-ui','presence_ui_tour')])
def test_ligation_tour_launches_isolated_workflow(client, monkeypatch, mode, tool, module):
    process = Mock(pid=987654)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(tours.subprocess, 'Popen', popen)
    result = client.post('/api/vr/tours/start', json={'tour': tool, 'mode': mode})
    assert result.status_code == 200, result.text
    command = popen.call_args.args[0]
    assert 'tools.vr_workflows.' + module in command
    assert ('--validate' in command) == (mode == 'validate')
    assert '--output' in command


def test_gallery_desktop_launch_needs_no_idle_headset(client, monkeypatch):
    monkeypatch.setattr(tours, '_viewer_active', lambda: True)
    process=Mock(pid=987654);process.poll.return_value=None
    popen=Mock(return_value=process);monkeypatch.setattr(tours.subprocess,'Popen',popen)
    response=client.post('/api/vr/tours/start',json={'tour':'thumbwheel-gallery','mode':'desktop'})
    assert response.status_code==200,response.text
    argv=popen.call_args.args[0]
    assert argv[1:3]==['-m','tools.vr_workflows.component_gallery_tour']
    assert '--desktop' in argv and '--validate' not in argv


def test_gallery_modes_are_scoped_and_validation_is_registered(client):
    assert client.post('/api/vr/tours/start',json={'tour':'all','mode':'desktop'}).status_code==400
    tour=next(t for t in catalog()['tours'] if t['id']=='thumbwheel-gallery')
    assert arguments(tour,True)==['-m','tools.vr_workflows.component_gallery_tour','--validate']


def test_button_gallery_has_both_native_modes_and_validation(client, monkeypatch):
    tour=next(t for t in catalog()['tours'] if t['id']=='button-gallery')
    assert arguments(tour,True)==['-m','tools.vr_workflows.component_gallery_tour','--component','buttons','--validate']
    process=Mock(pid=987654);process.poll.return_value=None
    popen=Mock(return_value=process);monkeypatch.setattr(tours.subprocess,'Popen',popen)
    response=client.post('/api/vr/tours/start',json={'tour':'button-gallery','mode':'desktop'})
    assert response.status_code==200,response.text
    argv=popen.call_args.args[0]
    assert argv[argv.index('--component')+1]=='buttons'
    assert '--desktop' in argv


def test_card_gallery_registers_desktop_and_vr():
    from tools.vr_workflows.tour_catalog import catalog
    tour = next(t for t in catalog()['tours'] if t['id'] == 'card-gallery')
    assert tour['group'] == 'components'
    assert tour['module'] == 'component_gallery_tour'
    assert tour['args'] == ['--component', 'cards']


def test_live_menu_tour_respects_assembly_context_without_hiding_missing_tabs():
    from tools.vr_workflows.menu_tour import context_catalog
    source = {'tabs': [
        {'side': 'right', 'key': 'assembly'},
        {'side': 'right', 'key': 'properties'},
        {'side': 'left', 'key': 'share'},
    ]}
    state = {'controls': [{'sidebar': 'right', 'id': 'tab:properties'}]}
    part, skipped = context_catalog(source, state)
    assert [t['key'] for t in part['tabs']] == ['properties', 'share']
    assert skipped == [{'side': 'right', 'tab': 'assembly',
                        'reason': 'assembly_context_unavailable'}]
    assert len(source['tabs']) == 3
    state['controls'].append({'sidebar': 'right', 'id': 'tab:assembly'})
    assembly, skipped = context_catalog(source, state)
    assert assembly == source and not skipped


def test_current_menu_routes_have_a_focused_four_profile_entry():
    tour = next(row for row in catalog()['tours'] if row['id'] == 'menu-actions')
    assert tour['group'] == 'interaction'
    assert arguments(tour, True) == ['-m','tools.vr_workflows.menu_tour',
        '--action-checks','--validate','--hold','0','--exit']
    assert 'all four' in tour['description']


def test_deformation_selection_check_is_discoverable_and_headset_independent(client):
    tour = next(t for t in client.get('/api/vr/tours').json()['tours'] if t['id'] == 'deformation-selection')
    assert tour['group'] == 'authoring'
    assert tour['runnable']
    assert 'No headset required' in tour['description']
    assert arguments(tour, True) == ['-m', 'tools.vr_workflows.deformation_selection_check', '--validate']
