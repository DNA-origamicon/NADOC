"""Build a standard HC bundle through recorded commands for browser review.

Use an isolated test workspace; every saved part passes the publication guard.
"""
import argparse
import json
from pathlib import Path

from backend.api import headless_build as hb
from backend.core.models import LatticeType
from scripts.agent_structure_guard import publish


def build(count, destination):
    if count == 6:
        cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    else:
        source = Path(__file__).resolve().parents[1] / 'Examples/cadnano/Honeycomb_18hb_test1.json'
        cells = [(h['row'], h['col']) for h in json.loads(source.read_text())['vstrands']]
    with hb.scratch_session():
        hb.create_bundle(cells, 168, lattice=LatticeType.HONEYCOMB,
                         name=f'__e2e__autostaple_{count}hb')
        hb.auto_scaffold()
        design = hb.full_autostaple()
        return publish(design, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('count', type=int, choices=[6, 18])
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.count, args.destination)))
