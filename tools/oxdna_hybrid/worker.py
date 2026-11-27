"""Persistent oxpy process. JSON commands use stdin; responses use a separate FD.

Never mixes the native engine's stdout with control messages. A worker owns only
its simulation directory and receives immutable bias tables from the controller.
"""
import json
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np


def main():
    import oxpy

    response = os.fdopen(int(os.environ['HYBRID_RESPONSE_FD']), 'w', buffering=1)

    def send(value):
        response.write(json.dumps(value, allow_nan=False) + '\n')

    try:
        with oxpy.Context():
            manager = oxpy.OxpyManager('input.txt')
            info = manager.config_info()
            actual_libraries = sorted({line.split()[-1] for line in Path('/proc/self/maps').read_text().splitlines()
                                       if 'liboxdna_common.so' in line})
            send({'ready': True, 'libraries': actual_libraries, 'oxpy': oxpy.__file__})
            for line in sys.stdin:
                command = json.loads(line)
                if command['action'] == 'stop':
                    manager.print_configuration()
                    send({'stopped': True, 'step': info.current_step})
                    break
                bias = command['bias']
                for force in info.forces:
                    if force.group_name == 'hybrid':
                        force.potential_grid = bias
                before = info.current_step
                started = time.monotonic()
                manager.run(int(command['steps']))
                elapsed = time.monotonic() - started
                if info.current_step - before != command['steps']:
                    raise RuntimeError('Native simulation stopped before requested step')
                manager.update_observable_data()
                cv = float(info.get_observable_by_id('hybrid_cv').get_output_string(info.current_step))
                q = float(info.get_observable_by_id('hybrid_q').get_output_string(info.current_step))
                if not np.isfinite([cv, q]).all():
                    raise ValueError('Nonfinite endpoint')
                if command.get('checkpoint', False):
                    manager.print_configuration()
                send({'step': info.current_step, 'cv': cv, 'q': q, 'native_seconds': elapsed})
            del manager
    except BaseException:
        send({'error': traceback.format_exc()})
        raise


if __name__ == '__main__':
    main()
