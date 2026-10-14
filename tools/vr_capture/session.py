"""Control a prepared compositor capture without changing SteamVR configuration.

A successful file capture is not proof of optical output or of one sample for
all display refreshes. The report keeps those verdicts separate.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import time
from pathlib import Path


def require_live_layer(directory: Path) -> None:
    for path in directory.glob('events-*.jsonl'):
        try:
            with path.open() as stream:
                first = json.loads(stream.readline())
            pid = int(first['pid'])
            if (first.get('event') == 'layer_start' and Path(f'/proc/{pid}').exists()
                    and time.time() - path.stat().st_mtime < 3):
                return
        except (OSError, ValueError, KeyError):
            continue
    raise RuntimeError('No live, recently writing capture layer found in this directory')


def arm(directory: Path, seconds: float, *, delay: float = 2.0) -> dict:
    if not math.isfinite(seconds) or not 0 < seconds <= 10:
        raise ValueError('capture seconds must be finite and in (0, 10]')
    if not math.isfinite(delay) or not 0 <= delay <= 30:
        raise ValueError('delay must be finite and in [0, 30]')
    directory = directory.resolve(strict=True)
    require_live_layer(directory)
    token = time.monotonic_ns()
    request = {'status': 'queued_not_acknowledged', 'token': token, 'duration_seconds': seconds, 'delay_seconds': delay,
               'requested_wall_time_ns': time.time_ns(), 'directory': str(directory)}
    (directory / f'request-{token}.json').write_text(json.dumps(request, indent=2) + '\n')
    if delay:
        time.sleep(delay)
    require_live_layer(directory)
    temporary = directory / f'control-{token}.tmp'
    temporary.write_text(f'{token} {seconds:.9f}\n')
    os.replace(temporary, directory / 'control.txt')
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record', help='Arm the already loaded capture layer')
    record.add_argument('--directory', type=Path, required=True)
    record.add_argument('--seconds', type=float, default=5)
    record.add_argument('--delay', type=float, default=2)
    args = parser.parse_args()
    if args.command == 'record':
        print(json.dumps(arm(args.directory, args.seconds, delay=args.delay), indent=2))


if __name__ == '__main__':
    main()
