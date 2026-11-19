"""Reconstruct a legacy bundle recipe using the real editor commands.

Snapshots identify old selections only. They never supply the new geometry.
Unsupported operations, ambiguous selections, or molecular differences refuse
publication. The original file is retained, and a machine-readable receipt maps
its complete command history to the newly recorded, independently audited recipe.
"""
import argparse
import hashlib
import json
from pathlib import Path

from backend.api import headless_build as hb, state, crud
from backend.api.routes_scaffold_routing import route_for_polymerization_endpoint
from backend.core.models import Design
from backend.core.design_diff import apply_child_diff_forward
from backend.core.positional_refs import to_positional, resolve
from scripts.agent_structure_guard import audit, publish
from backend.core.part_history_proof import command_rows


def molecular_value(design):
    """Compare all molecular content of the supported undeformed bundle recipes.

Fresh command IDs, frame ownership, routing-seed bookkeeping and display labels
can differ. Domains, sequence, junction directionality, periodic identity, helix
geometry and cluster poses cannot. Refuse other authoring features rather than
silently dropping them during a reconstruction.
"""
    supported = {'helices', 'strands', 'crossovers', 'forced_ligations',
                 'cluster_transforms', 'metadata', 'lattice_frames',
                 'group_organization', 'lattice_type', 'dimensions', 'tm_settings'}
    from backend.core.part_history_contract import FIELD_ROLES
    empty = Design(lattice_type=design.lattice_type)
    for key, role in FIELD_ROLES.items():
        if role in {'authoring', 'physical'} and key not in supported:
            if getattr(design, key) != getattr(empty, key):
                raise ValueError(f'AGENT_PROCESS_REQUIRED: unsupported populated field {key}')

    def ordered(items):
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))

    poses = []
    for cluster in design.cluster_transforms:
        if cluster.domain_ids or cluster.parent_cluster_id or cluster.overhang_duplex_driver_id:
            raise ValueError('AGENT_PROCESS_REQUIRED: unsupported cluster ownership')
        poses.append(dict(helix_ids=sorted(cluster.helix_ids), translation=cluster.translation,
                          rotation=cluster.rotation, pivot=cluster.pivot))
    return dict(
        helices=ordered([h.model_dump(mode='json', exclude={'lattice_frame_id', 'label'})
                         for h in design.helices]),
        strands=ordered([s.model_dump(mode='json', exclude={'id', 'color', 'name', 'notes', 'routing_seed'})
                         for s in design.strands]),
        crossovers=ordered([x.model_dump(mode='json', exclude={'id'}) for x in design.crossovers]),
        ligations=ordered([x.model_dump(mode='json', exclude={'id'}) for x in design.forced_ligations]),
        poses=ordered(poses), lattice_type=design.lattice_type.value,
        dimensions=design.dimensions, tm_settings=design.tm_settings.model_dump(mode='json'),
    )


def verify_equivalence(source, rebuilt):
    a, b = molecular_value(source), molecular_value(rebuilt)
    def equal(x, y):
        if isinstance(x, dict) and isinstance(y, dict):
            return x.keys() == y.keys() and all(equal(x[k], y[k]) for k in x)
        if isinstance(x, list) and isinstance(y, list):
            return len(x) == len(y) and all(equal(i, j) for i, j in zip(x, y))
        if isinstance(x, float) and isinstance(y, float):
            return abs(x-y) <= 1e-12
        return x == y
    differences = [key for key in a if not equal(a[key], b[key])]
    if differences:
        for key in differences:
            old = {json.dumps(v, sort_keys=True) for v in a[key]}
            new = {json.dumps(v, sort_keys=True) for v in b[key]}
            print('difference', key, 'old', sorted(old-new)[:2], 'new', sorted(new-old)[:2], flush=True)
        raise ValueError('AGENT_PROCESS_REQUIRED: reconstructed molecular content differs: '
                         + ', '.join(differences))
    return {'molecular_content_equal': True, 'float_absolute_tolerance': 1e-12, 'compared': list(a)}


def strand_key(s):
    return tuple((d.helix_id, d.start_bp, d.end_bp, d.direction.value)
                 for d in s.domains)


def counts(d):
    return dict(helices=len(d.helices), strands=len(d.strands),
                crossovers=len(d.crossovers), ligations=len(d.forced_ligations))


def reconstruct_scaffold(row):
    """Express a saved scaffold layout as explicit editor selections.

Modern automatic end-clearance decisions differ from old files. Preserve the
known layout using Resize Ends, Nick and Place Crossovers; do not change the
modern router or claim that a modern auto-route made the historical choices.
"""
    from backend.core.seamed_router import _nick_bp, _HC_SCAF_BOW_RIGHT, _SQ_SCAF_BOW_RIGHT
    target = state.decode_design_snapshot(row.post_state_gz_b64)
    if target.forced_ligations:
        raise ValueError('AGENT_PROCESS_REQUIRED: scaffold reconstruction has forced ligations')
    coverage = {}
    for strand in target.strands:
        if strand.is_scaffold:
            for domain in strand.domains:
                coverage.setdefault(domain.helix_id, []).extend([domain.start_bp, domain.end_bp])
    # Preserve the recorded axis-end convention with the editor's explicit helix
    # extension before moving strand handles. Resize then sees matching bounds.
    for helix in target.helices:
        crud.extend_helix_bounds(helix.id, crud.HelixExtendRequest(
            lo_bp=helix.bp_start, hi_bp=helix.bp_start+helix.length_bp-1))
    entries = []
    for strand in state.get_or_404().strands:
        if not strand.is_scaffold:
            continue
        if len(strand.domains) != 1:
            raise ValueError('AGENT_PROCESS_REQUIRED: scaffold seed is not a single domain')
        domain = strand.domains[0]
        lo, hi = min(coverage[domain.helix_id]), max(coverage[domain.helix_id])
        start, end = (lo, hi) if domain.direction.value == 'FORWARD' else (hi, lo)
        for side, delta in [('5p', start-domain.start_bp), ('3p', end-domain.end_bp)]:
            if delta:
                entries.append(crud.StrandEndResizeEntry(strand_id=strand.id,
                    helix_id=domain.helix_id, end=side, delta_bp=delta))
    crud.strand_end_resize(crud.StrandEndResizeRequest(entries=entries))
    # Install the already-recorded interior terminus before joining the scaffold,
    # so the crossover sequence cannot choose an arbitrary opening in a cycle.
    for strand in target.strands:
        if strand.is_scaffold:
            end = strand.domains[-1]
            if end.end_bp not in (min(coverage[end.helix_id]), max(coverage[end.helix_id])):
                crud.add_nick(crud.NickRequest(helix_id=end.helix_id,
                    bp_index=end.end_bp, direction=end.direction))
    honeycomb = target.lattice_type.value == 'HONEYCOMB'
    period, bows = (21, _HC_SCAF_BOW_RIGHT) if honeycomb else (32, _SQ_SCAF_BOW_RIGHT)
    placements = [crud.PlaceCrossoverRequest(
        half_a=crud.HalfCrossoverRequest(**x.half_a.model_dump()),
        half_b=crud.HalfCrossoverRequest(**x.half_b.model_dump()),
        nick_bp_a=_nick_bp(x.half_a.index, x.half_a.strand, period, bows),
        nick_bp_b=_nick_bp(x.half_b.index, x.half_b.strand, period, bows),
        process_id=x.process_id,
    ) for x in target.crossovers]
    crud.place_crossover_batch(crud.PlaceCrossoverBatchRequest(placements=placements))


def rebuild(source):
    molecular_value(source)  # Fail before construction for unsupported inputs.
    if not source.feature_log or source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise ValueError('AGENT_PROCESS_REQUIRED: complete active source history required')
    with hb.scratch_session(source.lattice_type):
        for row in source.feature_log:
            kind = getattr(row, 'op_kind', None)
            p = getattr(row, 'params', {})
            if kind == 'bundle-create':
                crud.create_bundle(crud.BundleRequest.model_validate(p))
            elif kind == 'auto-scaffold-seamed':
                reconstruct_scaffold(row)
            elif kind == 'full-autostaple':
                hb.full_autostaple(**p)
            elif kind == 'route-for-polymerization':
                route_for_polymerization_endpoint()
            elif kind == 'assign-scaffold-sequence':
                hb.assign_scaffold_sequence(**p)
            elif kind == 'assign-staple-sequences':
                hb.assign_staple_sequences()
            elif row.feature_type == 'routing-cluster':
                legacy = state.decode_design_snapshot(row.pre_state_gz_b64)
                for child in row.children:
                    command = child.op_subtype
                    args = child.params
                    live = state.get_or_404()
                    if command == 'nick':
                        crud.add_nick(crud.NickRequest.model_validate(args))
                    elif command == 'crossover-delete-batch':
                        positions = to_positional(command, {**args, '_proof_version': 1}, legacy)
                        resolved = resolve(command, positions, live)
                        crud.batch_delete_crossovers(crud.BatchDeleteCrossoversRequest(
                            crossover_ids=resolved['crossover_ids']))
                    elif command == 'strand-delete-batch':
                        before = {s.id: s for s in legacy.strands}
                        by_key = {}
                        for s in live.strands:
                            by_key.setdefault(strand_key(s), []).append(s.id)
                        ids = []
                        for identity in args['strand_ids']:
                            candidates = by_key.get(strand_key(before[identity]), [])
                            if len(candidates) != 1:
                                raise ValueError(f'AGENT_PROCESS_REQUIRED: selection {identity}: {len(candidates)} matches')
                            ids.append(candidates[0])
                        crud.delete_strands_batch(crud.StrandBatchDeleteRequest(strand_ids=ids))
                    else:
                        raise ValueError(f'AGENT_PROCESS_REQUIRED: unsupported {command}')
                    legacy, warnings = apply_child_diff_forward(legacy, child.diff_added_b64,
                        child.diff_removed_b64, child.diff_modified_b64)
                    if warnings:
                        raise ValueError(warnings)
                    print(command, counts(state.get_or_404()), flush=True)
            else:
                raise ValueError(f'AGENT_PROCESS_REQUIRED: unsupported {kind}')
            current = state.get_or_404()
            print(kind or row.feature_type, counts(current), flush=True)
        # A successful probe is still in memory. Publication requires full semantic
        # equivalence and an independent command audit, not matching counts.
        print('original', counts(source), 'rebuilt', counts(current), flush=True)
        print('equivalence', verify_equivalence(source, current), flush=True)
        print('audit', audit(current), flush=True)
        return current


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.destination.exists() or args.destination.with_suffix('.rebuild.json').exists():
        parser.error('Destination or reconstruction receipt already exists')
    raw = args.source.read_bytes()
    source = Design.model_validate_json(raw)
    result = rebuild(source)
    proof = publish(result, args.destination)
    reopened = Design.model_validate_json(args.destination.read_text())
    receipt = dict(source=str(args.source), source_sha256=hashlib.sha256(raw).hexdigest(),
                   source_preserved=args.source.read_bytes() == raw,
                   source_history=[row.model_dump(mode='json') for row in source.feature_log],
                   reconstructed_history=[dict(id=i, kind=k, params=p) for i,k,p in command_rows(result, 2000)],
                   publication=proof, reopened_audit=audit(reopened),
                   equivalence=verify_equivalence(source, reopened))
    args.destination.with_suffix('.rebuild.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k:v for k,v in receipt.items() if 'history' not in k}, indent=2))
