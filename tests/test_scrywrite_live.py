"""MCP framing, fail-closed validation, and actual native viewer IPC/Extrude tests.

The optional native harness executes production application handlers, without GL
or an OpenXR runtime. It must never be presented as physical headset evidence.
"""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scrywrite_mcp", ROOT / "frontend/scrywrite/mcp_bridge.py")
mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcp)


def test_discovery_and_offline_error(tmp_path):
    bridge = mcp.Bridge(tmp_path / "offline.sock")
    tools = mcp.dispatch(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(tools["result"]["tools"]) == 12
    reply = mcp.dispatch(bridge, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "scrywrite_observe"}})
    assert reply["result"]["isError"] is True
    assert mcp.dispatch(bridge, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.dispatch(bridge, [])['error']['code'] == -32600


@pytest.mark.parametrize("updates", [
    {"hand": True}, {"position": [0, float("nan"), 1]},
    {"orientation": [0, 0, 0, 0]}, {"orientation": [0, 0, 1]},
    {"session": "1-2\nobserve"}, {"expected_sequence": -1}, {"extra": "unexpected"},
])
def test_invalid_actions_never_connect(tmp_path, updates):
    args = {"session": "1-2", "expected_sequence": 0, "hand": 1,
            "position": [0, 1, -0.3], "orientation": [0, 0, 0, 1], **updates}
    with pytest.raises(ValueError):
        mcp.Bridge(tmp_path / "absent").call("scrywrite_pose", args)


def test_stdio_discovery_without_viewer(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    result = subprocess.run([sys.executable, str(ROOT / "frontend/scrywrite/mcp_bridge.py"), "--socket", str(tmp_path / "none")],
                            input="\n".join(map(json.dumps, messages)) + "\n", text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    replies = list(map(json.loads, result.stdout.splitlines()))
    assert [r['id'] for r in replies] == [1, 2, 3]
    assert replies[0]['result']['protocolVersion'] == '2025-11-25'
    assert replies[1]['result']['tools'][0]['name'] == 'scrywrite_observe'


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get("SCRYWRITE_LIVE_TEST_BIN")
    if not binary:
        pytest.skip("set SCRYWRITE_LIVE_TEST_BIN to the CMake application harness")
    # Unix-domain paths have a 108-byte limit; pytest's long names can exceed it.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="scry-ipc-") as directory:
        endpoint = Path(directory) / "viewer.sock"
        process = subprocess.Popen([binary, str(ROOT / "native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr"), "--serve", str(endpoint)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not endpoint.exists():
                if process.poll() is not None:
                    pytest.fail(process.stderr.read().decode())
                assert time.monotonic() < deadline
                time.sleep(0.01)
            yield mcp.Bridge(endpoint, tmp_path / "trace.jsonl")
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stderr.close()


def test_native_transport_extrude_and_stale_command(native):
    state = native.call('scrywrite_observe', {})
    assert state['runtime_connected'] is False

    def call(name, **args):
        nonlocal state
        state = native.call('scrywrite_' + name, {
            'session': state['session'], 'expected_sequence': state['command_sequence'], **args})
        assert 'error' not in state, state
        return state

    call('pose', hand=1, position=[0, 1, -0.3], orientation=[0, 0, 0, 1])
    call('activate', tool='extrude')
    assert state['extrude']['open']
    assert not state['extrude']['commit_supported']
    target = next(cell for cell in state['extrude']['visible_cells'] if cell['row'] == 0 and cell['column'] == 0)
    # Controller origin chosen along world +Z; aim is resolved by production math.
    position = list(target['position'])
    position[2] += 0.5
    call('pose', hand=1, position=position, orientation=[0, 0, 0, 1])
    call('aim_lattice', hand=1, row=target['row'], column=target['column'])
    native.wait(state['session'], lambda s: s['extrude']['hover'] == [target['row'], target['column']])
    call('button', hand=1, button='trigger', pressed=True)
    native.wait(state['session'], lambda s: [target['row'], target['column']] in s['extrude']['cells'])
    call('button', hand=1, button='trigger', pressed=False)
    native.wait(state['session'], lambda s: s['frame'] > state['frame'] + 1)
    call('button', hand=1, button='trigger', pressed=True)
    native.wait(state['session'], lambda s: s['extrude']['cells'] == [])
    call('release')
    duplicate = native.request(f"{state['session']} {state['command_sequence']} button 1 trigger 1")
    assert duplicate['error'] == 'stale_session_or_sequence'
    assert native.call('scrywrite_observe', {})['command_sequence'] == state['command_sequence']


def test_native_partial_client_does_not_stop_frame_progress(native):
    state = native.request('observe')
    with socket.socket(socket.AF_UNIX) as stalled:
        stalled.connect(native.socket_path)
        stalled.sendall(b'observ')
        time.sleep(0.1)
        stalled.sendall(b'e\n')
        stalled.settimeout(2)
        reply = json.loads(stalled.recv(1024 * 1024))
    assert reply['frame'] > state['frame'] + 10


def test_native_malformed_request_then_recovery(native):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(native.socket_path)
        connection.sendall(b'observe\nobserve\n')
        connection.settimeout(2)
        assert json.loads(connection.recv(4096))['error'] == 'invalid_framing'
    assert native.request('observe')['protocol'] == 1


def test_native_control_lease_releases_buttons_without_losing_pose(native):
    state = native.request('observe')
    session = state['session']
    native.request(f'{session} 1 pose 1 0 1 -0.3 0 0 0 1')
    native.request(f'{session} 2 button 1 trigger 1')
    native.wait(session, lambda s: s['hands'][1]['trigger'])
    released = native.wait(session, lambda s: not s['hands'][1]['trigger'], timeout_ms=3500)
    assert released['hands'][1]['valid']
    assert released['command_sequence'] == 2


def test_backend_discovery_reconnects_without_retargeting_old_actions(native, tmp_path):
    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({'scrywrite_live': 'transactions', 'scrywrite_socket': native.socket_path}))
    state_file.chmod(0o600)
    bridge = mcp.Bridge(state_path=state_file)
    session = bridge.request('observe')['session']
    assert bridge.request('observe')['session'] == session
    # An offline/replaced endpoint is re-read, not cached or blindly replayed.
    state_file.write_text(json.dumps({'scrywrite_live': 'off'}))
    with pytest.raises(ValueError, match='no agent-enabled'):
        bridge.request('observe')
    state_file.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        bridge.request('observe')


def test_capture_without_submitted_frames_fails_and_recovers(native):
    state = native.request('observe')
    result = native.call('scrywrite_capture', {
        'session': state['session'], 'expected_sequence': 0,
    })
    assert result['capture'] == {'status': 'failed', 'error': 'no_submitted_frame', 'command_sequence': 1}
    assert mcp.tool_result(result, capture=True)['isError']
    assert not mcp.tool_result(native.request('observe'))['isError']
    assert native.request('observe')['command_sequence'] == 1
