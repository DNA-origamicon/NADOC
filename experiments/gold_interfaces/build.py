"""Prepare a bare-gold qualification package; never launch an engine."""

import argparse
import json
from pathlib import Path

from backend.core.namd_gold_package import build_package, config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="JSON with geometry plus optional preparation settings")
    parser.add_argument("output", type=Path, help="New directory, never overwritten")
    args = parser.parse_args()
    options = json.loads(args.spec.read_text())
    geometry = options.pop("geometry")
    manifest = build_package(args.output, geometry, **options)
    (args.output/"example.conf").write_text(config(manifest, minimize=200, steps=2000))
    print(json.dumps({"n_atoms": manifest["n_atoms"], "packing": manifest["packing"]}, indent=2))
