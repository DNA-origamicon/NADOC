"""Record or inspect a SteamVR presentation-boundary capture.

The native layer requires a separately prepared, process-scoped compositor
launch. This command never restarts SteamVR or changes installed settings.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, help='Capture directory to inspect')
    parser.add_argument('--record', action='store_true', help='Record the selected duration in a prepared capture process')
    parser.add_argument('--seconds', type=float, default=2)
    parser.add_argument('--validate', action='store_true', help='Require full capture accounting; never infer optical equivalence')
    args = parser.parse_args()
    if args.directory is None:
        print('SteamVR final-output capture needs its process-scoped Vulkan layer.\n'
              'See docs/scrywrite_inspector.md for build, launch, recording, review and rollback.\n'
              'With a prepared runtime: --directory CAPTURE_DIRECTORY --record\n'
              'Captures are classified separately as submitted, composited, presented, and optically observed.')
        return
    if args.record:
        from tools.vr_capture.viewer_record import record
        result = record(args.directory, lambda row: print(json.dumps(row), flush=True), seconds=args.seconds)
        print(json.dumps(result, indent=2))
        if result['status'] != 'saved':
            raise SystemExit(1)
    else:
        from tools.vr_capture.audit import audit_directory
        result = audit_directory(args.directory)
        print(json.dumps(result, indent=2))
        if args.validate and not result['complete_present_capture']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
