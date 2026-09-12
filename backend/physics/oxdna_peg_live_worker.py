"""Private JSON-line worker: keeps PEG oxpy isolated from the server's stock oxpy."""
import json
import os
import sys


def main():
    # Native oxDNA logs to stdout too. Reserve an independent protocol descriptor.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'w', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.path.insert(0, sys.argv[1])
    from backend.physics.oxdna_live import _OxpyStepper

    stepper = None
    physical = False
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                op = request['op']
                if op == 'open':
                    stepper = _OxpyStepper(request['rundir'], backend=request['backend'])
                    physical = request['physical']
                    stepper.__enter__()
                    stepper._mgr.print_configuration()
                elif op == 'run':
                    stepper.run(request['steps'])
                    stepper._mgr.print_configuration()
                elif op == 'field':
                    # Physical fields contain independently signed DNA and terminal
                    # forces. They are rewritten together on recomposition.
                    if not physical:
                        stepper.set_field(request['force'], request['direction'])
                elif op == 'close':
                    break
                else:
                    raise ValueError(f'Unknown operation: {op}')
                protocol.write(json.dumps({'ok': True, 'backend': stepper.active_backend,
                    'fell_back': stepper.fell_back, 'reason': stepper.fallback_reason}) + '\n')
            except Exception as exc:
                protocol.write(json.dumps({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}) + '\n')
                break
    finally:
        if stepper is not None:
            stepper.__exit__(None, None, None)


if __name__ == '__main__':
    main()
