"""Wait for the already running timing owner, then execute bounded validation."""
import os
from pathlib import Path
import time

from experiments.peg_chudoba.benchmark_scheduling import DEFAULT, execute, read, write, digest
from experiments.peg_chudoba.serialize_existing import alive, process
from experiments.peg_chudoba.validate_narrow import SPECIFICATION


def main():
    out = DEFAULT
    status = out/'bounded_driver.json'
    if status.exists() and alive(read(status)['owner']):
        raise RuntimeError('A bounded validation driver is already alive')
    state = read(out/'lease.json')
    owner = state['owner']
    if alive(owner) and '--benchmark-only' not in owner['command']:
        raise RuntimeError('Unexpected live lease owner; refusing concurrent production')
    scope_hash = digest(SPECIFICATION)
    record = dict(owner=process(os.getpid()), specification=str(SPECIFICATION),
                  specification_sha256=scope_hash, started_unix=time.time(),
                  status='waiting for existing matched benchmark')
    write(status,record)
    print(record['status'],flush=True)
    deadline = time.monotonic()+7200
    try:
        while alive(owner):
            if time.monotonic() >= deadline:
                raise RuntimeError('Existing benchmark exceeded two-hour transition limit')
            time.sleep(5)
        if read(out/'lease.json')['status'] != 'restored':
            raise RuntimeError('Benchmark lease not restored; inspect recovery state')
        if len(read(out/'benchmarks.json')['batches']) != 26 or not (out/'selection.json').exists():
            raise RuntimeError('Matched timing incomplete; cannot choose production strategy')
        if digest(SPECIFICATION) != scope_hash:
            raise RuntimeError('Bounded specification changed while waiting')
        record.update(status='running bounded validation',production_started_unix=time.time())
        write(status,record)
        print(record['status'],flush=True)
        execute(out,read(out/'plan.json'))
        record.update(status=read(out/'validation.json')['status'],finished_unix=time.time())
    except Exception as error:
        record.update(status='stopped; validation incomplete',error=str(error),finished_unix=time.time())
        raise
    finally:
        write(status,record)


if __name__ == '__main__':
    main()
