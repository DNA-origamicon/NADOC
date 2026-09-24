"""Shared session ownership, frame barriers and capture lifecycle for live tools."""
import json
from pathlib import Path
import shutil


class LiveSession:
    def __init__(self, bridge, *, physical=False, allow_transactions=False, cancel=None):
        self.bridge = bridge
        self.cancel = cancel
        self.state = bridge.call('scrywrite_observe', {})
        if 'error' in self.state:
            raise RuntimeError(str(self.state))
        self.session = self.state['session']
        mode = self.state.get('mode')
        if mode not in ('inspect', 'control', 'transactions') or not self.state.get('focused'):
            raise ValueError('live session requires a focused inspect/control/transactions viewer')
        if mode == 'transactions' and not allow_transactions:
            raise ValueError('browser transactions require explicit opt-in')
        if physical and not self.state.get('runtime_connected'):
            raise ValueError('requires physical-runtime viewer')

    def checked(self, result, sequence, *, focus=True):
        if ('error' in result or result.get('session') != self.session
                or result.get('command_sequence') != sequence
                or (focus and not result.get('focused'))):
            raise RuntimeError('session/sequence/focus ownership changed: '+str(result))
        self.state = result
        return result

    def send(self, operation, **args):
        if self.cancel and self.cancel.is_set() and operation != 'release':
            raise InterruptedError('profile run cancelled')
        sequence = self.state['command_sequence']+1
        self.last_operation={"operation":operation,"sequence":sequence,"frame":self.state.get("frame")}
        return self.checked(self.bridge.call('scrywrite_'+operation, {
            'session':self.session, 'expected_sequence':sequence-1, **args}),
            sequence, focus=operation != 'release')

    def frame(self):
        self.last_operation={'operation':'frame_wait','sequence':self.state['command_sequence'],'frame':self.state['frame']}
        return self.checked(self.bridge.call('scrywrite_wait', {'session':self.session,
            'field':'frame','value':self.state['frame']+1,'comparison':'at_least',
            'timeout_ms':1000}), self.state['command_sequence'])

    def button(self, button, hand=None):
        if hand is None:
            hand = int(button != 'menu')
        for pressed in (True, False):
            self.send('button', hand=hand, button=button, pressed=pressed)
            self.frame()

    def release(self):
        state = self.bridge.call('scrywrite_observe', {})
        if state.get('session') != self.session:
            raise RuntimeError('original viewer unavailable for release; input lease must expire')
        self.state = state
        return self.send('release')

    def capture_to(self, destination, *, files=None, discard_source=False):
        """Copy only requested evidence; validate session/path before reading it."""
        result = self.send('capture').get('capture', {})
        if result.get('status') != 'complete':
            raise RuntimeError('capture failed: '+str(result))
        source = Path(result['directory']).resolve()
        socket_parent = Path(self.bridge.socket_path).resolve().parent
        if source.parent != socket_parent or not source.name.startswith('capture-'):
            raise ValueError('capture outside pinned session directory')
        evidence = json.loads((source/'evidence.json').read_text())
        if (evidence['state']['session'] != self.session
                or not evidence.get('xr_end_frame_succeeded')
                or evidence.get('capture_command_sequence') != self.state['command_sequence']):
            raise RuntimeError('capture does not match submitted session/command')
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        names = files or [p.name for p in source.iterdir() if p.is_file()]
        for name in names:
            if Path(name).name != name:
                raise ValueError('invalid capture file')
            shutil.copy2(source/name, destination/name)
        if discard_source:
            shutil.rmtree(source)
        return evidence, source
