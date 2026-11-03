#!/usr/bin/env python3
"""Reproduce illustrative native router checks; not an exhaustive validity audit."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.screen_yggdnasil import load_atlas
from backend.core.lattice import make_bundle_design
from backend.core.models import LatticeType
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.sequences import strand_nucleotide_count
from backend.core.topology_integrity import domain_order_errors, occupancy_errors, junction_errors
from backend.core.scaffold_invariants import scaffold_routing_invariants


def main():
    atlas = load_atlas(7249)
    examples = []
    for lattice, helices in [('honeycomb', 6), ('square', 4)]:
        entry = next(e for e in atlas['entries'] if e['lattice'] == lattice and e['helices'] == helices)
        for length in (100, entry['maxLength']):
            for mode, router in [('seamless', auto_scaffold_seamless), ('seamed', auto_scaffold_seamed)]:
                design = make_bundle_design([(p['row'], p['col']) for p in entry['points']], length,
                                            lattice_type=LatticeType[lattice.upper()])
                routed, result = router(design)
                scaffolds = routed.scaffolds()
                counts = [strand_nucleotide_count(s, routed) for s in scaffolds]
                errors = (domain_order_errors(routed) + occupancy_errors(routed) + junction_errors(routed)
                          + scaffold_routing_invariants(routed, require_seams=mode == 'seamed'))
                examples.append(dict(lattice=lattice, helices=helices, paired_length_bp=length,
                                     mode=mode, router_valid=result.valid, scaffold_strands=len(scaffolds),
                                     routed_nt=counts, exceeds_7249=any(c > 7249 for c in counts),
                                     integrity_errors=errors, warnings=result.warnings))
    destination = ROOT / 'analysis/yggdnasil/route_examples.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({'scope': 'Illustrative native router runs only; not extrapolated to the complete atlas.',
                                      'examples': examples}, indent=2) + '\n')
    print(destination)


if __name__ == '__main__':
    main()
