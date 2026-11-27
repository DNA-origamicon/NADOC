"""Read-only D003 seam census and current Full-view bond evidence.

Does not author structures, change geometry, or issue approval receipts.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from scipy.spatial.transform import Rotation
from backend.core.models import Design
from backend.core.design_bond_review import _realized_edges, _position_lookup, _edge_description
from backend.core.part_history_proof import command_rows
from scripts.agent_bond_review import bond_report


def review(source, output):
    raw = source.read_bytes()
    design = Design.model_validate_json(raw)
    original = design.model_dump_json()
    report = bond_report(design)
    positions = _position_lookup(design)
    edges, nodes, matched = _realized_edges(design)
    labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
    clusters = [c for c in design.cluster_transforms if c.helix_ids]
    membership = {h: c.name for c in clusters for h in c.helix_ids}
    if len(membership) != len(design.helices):
        raise ValueError('Cluster census is incomplete')
    commands = list(command_rows(design, 2000))
    counts = Counter()
    records = []
    for index, r in enumerate(design.forced_ligations):
        first, second = r.three_prime_helix_id, r.five_prime_helix_id
        pair = tuple(sorted((membership[first], membership[second])))
        counts[pair] += 1
        feature_ids = [feature for feature, kind, params in commands if r.id in json.dumps(params)]
        records.append({'id': r.id, 'from_helix': labels[first], 'from_bp': r.three_prime_bp,
                        'to_helix': labels[second], 'to_bp': r.five_prime_bp,
                        'cluster_pair': pair, 'insert_sequence': r.extra_bases,
                        'realized': index in matched, 'referencing_features': feature_ids})
    measured = []
    for edge in edges:
        if not edge['interhelix']:
            continue
        first, second = positions.get(edge['first']), positions.get(edge['second'])
        if first is None or second is None:
            raise ValueError('Current junction geometry remains unmeasured')
        measured.append({**_edge_description(edge,nodes,labels),
                         'distance_nm':math.dist(first,second),
                         'junction_insert':edge['first'][0]=='__xb__' or edge['second'][0]=='__xb__'})
    inserted = [e for e in measured if e['junction_insert']]
    census = {'source_sha256':hashlib.sha256(raw).hexdigest(), 'design_sha256':report['design_sha256'],
              'clusters':[{'name':c.name,'helix_labels':[labels[h] for h in c.helix_ids],
                           'rotation_xyzw':c.rotation,'translation_nm':c.translation,
                           'posed_axis':Rotation.from_quat(c.rotation).apply([0,0,1]).tolist()} for c in clusters],
              'cluster_pair_counts':[{'pair':pair,'records':n} for pair,n in sorted(counts.items())],
              'forced_records':records, 'interhelix_edges':measured,
              'newly_measured_insert_segments':len(inserted),
              'newly_measured_long_insert_segments':sum(e['distance_nm']>1.2 for e in inserted),
              'structure_modified':False, 'approval_issued':False}
    assert design.model_dump_json()==original
    output.mkdir(parents=True,exist_ok=True)
    (output/'bond-report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'seam-census.json').write_text(json.dumps(census,indent=2)+'\n')
    print(json.dumps({'pairs':census['cluster_pair_counts'], 'new_segments':len(inserted),
                      'new_long_segments':census['newly_measured_long_insert_segments'],
                      'unmatched_records':len(design.forced_ligations)-len(matched),
                      'records_without_feature_reference':sum(not r['referencing_features'] for r in records)},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    review(args.source,args.output)
