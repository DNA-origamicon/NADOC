"""Compile reviewed figure traces or compare a registered draft to a native file.

Usage: python -m tools.design_archive.reconstruct_image compile REVIEW.json OUTPUT_DIR
       python -m tools.design_archive.reconstruct_image compare DRAFT.json REFERENCE.json OUTPUT.json
"""
import argparse
import json
from pathlib import Path
from backend.core.image_reconstruction import compile_reviewed_routes, compare_cadnano, expand_reviewed_trace


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    compile_parser = commands.add_parser('compile')
    compile_parser.add_argument('review', type=Path)
    compile_parser.add_argument('output', type=Path)
    compare_parser = commands.add_parser('compare')
    compare_parser.add_argument('draft', type=Path)
    compare_parser.add_argument('reference', type=Path)
    compare_parser.add_argument('output', type=Path)
    args = p.parse_args()
    if args.command == 'compile':
        review = json.loads(args.review.read_text())
        for route in review.get('routes', []):
            if 'vertices' in route:
                if 'sites' in route:
                    raise ValueError('Supply vertices or sites, not both')
                route['sites'] = expand_reviewed_trace(route['vertices'], review['anchors'], order=route['order'])
        result = compile_reviewed_routes(review)
        args.output.mkdir(parents=True, exist_ok=True)
        for name in ('draft.json', 'provenance.json'):
            if (args.output/name).exists():
                raise FileExistsError(f'Refusing to replace {args.output/name}')
        (args.output/'draft.json').write_text(json.dumps(result.pop('cadnano'), indent=2))
        (args.output/'provenance.json').write_text(json.dumps(result, indent=2))
    else:
        if args.output.exists():
            raise FileExistsError(f'Refusing to replace {args.output}')
        result = compare_cadnano(json.loads(args.draft.read_text()), json.loads(args.reference.read_text()))
        args.output.write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
