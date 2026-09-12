"""Persistent PEG Live transport and display. No stock oxpy is imported here."""
from pathlib import Path
import json
import os
import selectors
import shutil
import subprocess
import sys
import threading

from backend.physics.oxdna_interface import read_configuration_full, oxdna_backbone_site


def peg_live_available():
    path = Path(os.environ.get('NADOC_PEG_OXPY_PATH',
        str(Path.home() / '.local/share/nadoc/engines/oxdna-peg/build-live/python')))
    available = (path / 'oxpy/core.so').is_file()
    return {'available': available, 'path': str(path.resolve()),
            'reason': 'PEG Live bindings ready' if available else
            'Build PEG Live bindings: bash scripts/build-oxdna-peg-live.sh'}


class PegLiveStepper:
    def __init__(self, rundir, *, backend, spec, physical=False):
        self.rundir = Path(rundir)
        self.backend = self.active_backend = backend
        self.spec = spec
        self.physical = physical
        self.fell_back = False
        self.fallback_reason = None
        self._process = None
        self._log = None
        self._cancelled = threading.Event()

    def __enter__(self):
        capability = peg_live_available()
        if not capability['available']:
            raise RuntimeError(capability['reason'])
        self._log = (self.rundir / 'worker.log').open('w')
        try:
            self._process = subprocess.Popen(
                [sys.executable, '-m', 'backend.physics.oxdna_peg_live_worker', capability['path']],
                cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self._log, text=True, bufsize=1,
            )
            self._request({'op': 'open', 'rundir': str(self.rundir.resolve()),
                           'backend': self.backend, 'physical': self.physical})
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _request(self, request):
        if self._cancelled.is_set():
            raise RuntimeError('PEG Live stopped')
        proc = self._process
        proc.stdin.write(json.dumps(request) + '\n')
        proc.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=45):
                self.cancel()
                raise RuntimeError('PEG Live worker timed out')
        line = proc.stdout.readline()
        if not line:
            with (self.rundir / 'worker.log').open('rb') as stream:
                stream.seek(max(0, stream.seek(0, 2) - 4096))
                detail = stream.read().decode(errors='replace')
            raise RuntimeError(f'PEG Live worker exited: {detail or "no diagnostic output"}')
        response = json.loads(line)
        if not response['ok']:
            raise RuntimeError(response['error'])
        self.active_backend = response['backend']
        self.fell_back = response['fell_back']
        self.fallback_reason = response['reason']

    def run(self, steps):
        self._request({'op': 'run', 'steps': int(steps)})

    def set_field(self, force, direction):
        self._request({'op': 'field', 'force': float(force), 'direction': list(direction)})

    def configuration(self, design):
        return read_configuration_full(self.rundir / 'last_conf.dat', design,
            n_trailing_extra=int(self.spec['built']['n_beads']))

    def configuration_map(self, design):
        return self.configuration(design)

    def snapshot_seed(self):
        target = self.rundir / 'reconfig_seed.dat'
        shutil.copyfile(self.rundir / 'last_conf.dat', target)
        return target

    def cancel(self):
        self._cancelled.set()
        proc = self._process
        if proc and proc.poll() is None:
            proc.kill()

    def __exit__(self, *args):
        proc = self._process
        if proc:
            if proc.poll() is None:
                try:
                    proc.stdin.write('{"op":"close"}\n')
                    proc.stdin.flush()
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait(timeout=2)
            proc.stdin.close()
            proc.stdout.close()
            self._process = None
        if self._log:
            self._log.close()
            self._log = None
        return False


def peg_frame_builder(design, spec):
    """Raw simulation coordinates: grafted surfaces must not rotate with DNA alignment."""
    def build(session):
        full = read_configuration_full(session.stepper.rundir / 'last_conf.dat', design,
            n_trailing_extra=int(spec['built']['n_beads']),
            trailing_extra_strand_length=int(spec['segments']) + 1)
        result = []
        for (hid, bp, direction), value in full.items():
            cm, a1, a3 = value['backbone_position'], value['a1'], value['a3']
            peg = hid.startswith('cap') and bp >= 1_000_000
            result.append({'helix_id': hid, 'bp_index': bp, 'direction': direction,
                'cm_position': cm.tolist(),
                'backbone_position': (cm if peg else oxdna_backbone_site(cm, a1, a3)).tolist(),
                'nx': float(a1[0]), 'ny': float(a1[1]), 'nz': float(a1[2])})
        return result
    return build


def validate_peg_continuation(spec, requested, topology_path):
    """Live inherits particles; it cannot build or resize a coating in place."""
    from backend.physics.oxdna_peg import PegParameters
    PegParameters.model_validate(spec)
    built = spec.get('built') or {}
    count = int(built.get('n_beads', 0))
    traps = built.get('trap_particles') or []
    if count <= 0 or not traps or count != len(traps) * (int(spec['segments']) + 1):
        raise ValueError('Prepare a PEG job with built coating particles before starting Live')
    if not Path(topology_path).is_file():
        raise ValueError('Prepared PEG topology is missing; prepare the job again')
    rows = Path(topology_path).read_text().splitlines()
    total = int(rows[0].split()[0])
    length = int(spec['segments']) + 1
    if (total != len(rows) - 1 or total <= count
            or traps != list(range(total - count, total, length))
            or any(row.split()[1] != '500' for row in rows[-count:])):
        raise ValueError('Prepared PEG topology and coating metadata disagree; prepare the job again')
    if built.get('terminal_particles') != [p + length - 1 for p in traps]:
        raise ValueError('Prepared PEG terminal indices are missing or inconsistent')
    for key in ('material', 'segments', 'bondLengthNm', 'beadDiameterNm', 'terminalChargeE',
                'shape', 'sizeNm', 'densityPerUm2', 'offsetXNm', 'offsetYNm', 'seed'):
        if key in (requested or {}) and requested[key] != spec.get(key):
            raise ValueError(f'PEG {key} differs from the prepared job; create a new job to change the coating')
