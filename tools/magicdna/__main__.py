"""CLI: python -m tools.magicdna {import,export,restore,reimport,validate} ..."""

import argparse
import json
from pathlib import Path

from backend.core.models import Design
from scripts.agent_structure_guard import publish
from tools.magicdna.convert import import_bundle, read_export, write_export
from tools.magicdna.routing import inventory, read_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    imp = sub.add_parser(
        "import",
        help="Reconstruct straight MagicDNA caDNAno through native editor operations",
    )
    imp.add_argument("source", type=Path)
    imp.add_argument("destination", type=Path)
    imp.add_argument("--lattice", choices=["HONEYCOMB", "SQUARE"], required=True)
    imp.add_argument("--name", default="MagicDNA bundle")
    exp = sub.add_parser(
        "export", help="Write routing plus portable upstream-history package"
    )
    exp.add_argument("source", type=Path)
    exp.add_argument("destination", type=Path)
    restore = sub.add_parser(
        "restore", help="Restore an unchanged package with its original process"
    )
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    reimport = sub.add_parser(
        "reimport",
        help="Reconstruct native MagicDNA output while preserving its upstream package",
    )
    reimport.add_argument("package", type=Path)
    reimport.add_argument("source", type=Path)
    reimport.add_argument("destination", type=Path)
    validate = sub.add_parser(
        "validate", help="Validate a routing file before loading it into MATLAB"
    )
    validate.add_argument("source", type=Path)
    validate.add_argument("--lattice", choices=["HONEYCOMB", "SQUARE"], required=True)
    args = parser.parse_args()
    if args.action == "validate":
        data, walks, _ = read_graph(args.source.read_bytes(), args.lattice)
        result = inventory(data, walks)
    elif args.action == "export":
        result = write_export(
            Design.model_validate_json(args.source.read_bytes()), args.destination
        )
    else:
        if args.action == "import":
            # NADOC-origin packages must retain upstream history, even when a
            # caller accidentally selects the contained routing file directly.
            if (args.source.parent / "manifest.json").exists():
                raise ValueError(
                    "Use restore on this package to preserve upstream construction"
                )
            design, result = import_bundle(
                args.source.read_bytes(), args.lattice, name=args.name
            )
        elif args.action == "reimport":
            upstream = read_export(args.package)
            design, result = import_bundle(
                args.source.read_bytes(),
                upstream.lattice_type,
                name=upstream.metadata.name + " (MagicDNA round trip)",
                upstream=upstream,
            )
        else:
            design, result = read_export(args.source), {}
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        result["publication"] = publish(design, args.destination)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
