"""Native numerical force/torque gradients and CPU/CUDA parity on existing frames."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from tools.oxdna_hybrid.bias import BiasSpec, force_text
from tools.oxdna_umbrella.native import digest, execute, input_text, scratch_root


def validate(inputs, binary, probe, output, old_binary=None):
    root, binary, probe, output = map(lambda p: Path(p).resolve(), (inputs, binary, probe, output))
    reports = []
    with tempfile.TemporaryDirectory(dir=scratch_root(), prefix='hybrid-parity-') as tmp:
        for frame in ('conf.dat', 'boundary.dat', 'unbound.dat'):
            for coordinate, weight, radius in [('hb_cutoff', .7, .5), ('mixed', .7, .5),
                                                ('mixed', 0., .5), ('mixed', .7, 1.5)]:
                spec = BiasSpec(coordinate=coordinate, mixed_weight=weight, contact_radius=radius)
                if radius == 1.5:
                    spec = BiasSpec(coordinate=coordinate, mixed_weight=weight,
                                    contact_radius=radius, minimum=-.375, maximum=8.125)
                potential = .2*spec.grid**2 if radius == 1.5 else spec.grid*2
                values = {}
                cases = [('CPU', binary), ('CUDA', binary)]
                if old_binary:
                    cases.append(('old_CUDA', Path(old_binary).resolve()))
                for backend, engine in cases:
                    directory = Path(tmp)/f'{frame}-{coordinate}-{weight}-{radius}-{backend}'
                    text = input_text(root, root/frame, backend.replace('old_', ''), 2, 100, 70, .3,
                                      list(range(8)), list(range(8, 16)), dt=.001,
                                      output_every=1, trajectory_every=1, thermostat='no', refresh_vel=False)
                    execute(engine, directory, text, force_text(spec, potential, root/'vmmc_op.txt',
                                                                list(range(8)), list(range(8, 16))))
                    values[backend] = np.loadtxt(directory/'last_conf.dat', skiprows=3)[:, 9:15]
                    if backend == 'CPU':
                        result = subprocess.run([str(probe), 'input.txt'], cwd=directory,
                                                capture_output=True, text=True)
                        if result.returncode:
                            raise RuntimeError(result.stdout+result.stderr)
                        gradient = json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
                errors = {key: float(np.max(abs(value-values['CPU']))) for key, value in values.items() if key != 'CPU'}
                # Mixed-precision native trajectories include physical-force roundoff.
                if errors['CUDA'] > 5e-6:
                    raise ValueError(f'CPU/GPU force/torque parity failed: {frame}, {coordinate}, weight={weight}, radius={radius}: {errors}')
                reports.append({'frame': frame, 'frame_sha256': digest(root/frame),
                                'coordinate': coordinate, 'mixed_weight': weight,
                                'contact_radius': radius,
                                'grid_domain': [spec.minimum, spec.maximum],
                                'velocity_and_angular_momentum_max_error': errors,
                                'numerical_derivatives': gradient})
    library = binary.parent.parent/'src/liboxdna_common.so'
    if not library.exists():
        library = binary.parent.parent/'lib/liboxdna_common.so'
    report = {'passed': True, 'library_sha256': digest(library),
              'probe_sha256': digest(probe), 'cases': reports,
              'trajectory_tolerance': 5e-6, 'gradient_tolerance': 1e-4,
              'radial_boundary_jump_tolerance': 1e-5}
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('inputs', 'binary', 'probe', 'output'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--old-binary')
    validate(**vars(parser.parse_args()))
