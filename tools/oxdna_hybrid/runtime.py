"""Bounded native worker ownership and duplex-only input preparation."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

from tools.oxdna_umbrella.native import digest, input_text


def simulation_input(root, conf, spec, backend, seed, temperature, salt, cadence, dt=.005):
    # Pairing is taken from the already validated export, not inferred here.
    from backend.core.oxdna_vmmc import duplex_pairs

    pairs = duplex_pairs(root/'topology.top')
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    text = input_text(root, conf, backend, 1, seed, temperature, salt, a, b,
                      dt=dt, output_every=cadence, trajectory_every=5*cadence)
    text = text.split('data_output_1 =')[0]
    if spec.coordinate == 'com':
        cv = ("type = distance\nPBC = true\nparticle_1 = " + ','.join(map(str, a))
              + '\nparticle_2 = ' + ','.join(map(str, b)))
    else:
        cv = f"type = coordination\nop_file = {root/'vmmc_op.txt'}\n" + spec.settings
    text += f'''data_output_1 = {{
name = samples.dat
print_every = {cadence}
col_1 = {{ type = step }}
col_2 = {{
id = hybrid_cv
{cv}
}}
col_3 = {{
id = hybrid_q
type = hb_list
only_count = true
op_file = {root/'vmmc_op.txt'}
}}
col_4 = {{
type = force_energy
print_group = hybrid
per_particle = false
}}
col_5 = {{ type = potential_energy }}
}}
'''
    return text, a, b


class Worker:
    def __init__(self, directory, oxpy_path, library):
        self.directory = Path(directory)
        self.log = (self.directory/'native.log').open('w')
        read_fd, write_fd = os.pipe()
        package_root = str(Path(__file__).resolve().parents[2])
        environment = {**os.environ, 'HYBRID_RESPONSE_FD': str(write_fd),
                       'PYTHONPATH': os.pathsep.join([package_root, str(oxpy_path)]),
                       'LD_LIBRARY_PATH': str(Path(library).parent),
                       'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        self.process = subprocess.Popen([sys.executable, '-m', 'tools.oxdna_hybrid.worker'],
                                        cwd=directory, env=environment, stdin=subprocess.PIPE,
                                        stdout=self.log, stderr=subprocess.STDOUT,
                                        text=True, pass_fds=(write_fd,))
        os.close(write_fd)
        self.read_fd = read_fd
        self.buffer = b''
        self.started = time.monotonic()

    def receive(self, deadline):
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'Worker deadline exceeded: {self.directory}')
            readable, _, _ = select.select([self.read_fd], [], [], min(remaining, 30))
            if readable:
                chunk = os.read(self.read_fd, 65536)
                if not chunk:
                    raise RuntimeError(f'Worker exited: {self.directory}; see native.log')
                self.buffer += chunk
        line, self.buffer = self.buffer.split(b'\n', 1)
        value = json.loads(line)
        if 'error' in value:
            raise RuntimeError(value['error'])
        return value

    def send(self, value):
        self.process.stdin.write(json.dumps(value, allow_nan=False)+'\n')
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        os.close(self.read_fd)
        self.log.close()


def check_runtime(response, library):
    if response.get('libraries') != [str(Path(library).resolve())]:
        raise ValueError(f'Unexpected native library: {response}')
    return {'library': str(library), 'sha256': digest(library), 'oxpy': response['oxpy']}
