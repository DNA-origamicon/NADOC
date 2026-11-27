"""Replayable plane truncation. Retained bases keep their original geometry."""
import math
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.core.cluster_reconcile import MutationReport
from backend.core.corner_topology import corner_output_id, _sequence_fragments


class BevelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cluster_id: Annotated[str, Field(min_length=1, max_length=256, strict=True)]
    position_bp: Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]
    angle_deg: float = Field(ge=0, lt=90, allow_inf_nan=False)
    direction_deg: float = Field(allow_inf_nan=False)
    trim_end: Literal['start', 'end'] = 'end'


class BevelCommand(BevelRequest):
    proof_version: Literal[1, 2] = Field(default=2, alias='_proof_version')
    operation_id: Annotated[str, Field(min_length=1, max_length=64, strict=True)]


def dependencies(params):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        command = BevelCommand.model_validate(params)
    except (ValueError, TypeError):
        return Dependencies(known=False)
    topology = Resource('part', 'topology')
    return Dependencies(frozenset({topology, Resource('cluster', command.cluster_id)}),
                        frozenset({topology}), barrier=True)


def bevel_guide(design, request):
    from backend.api.corner_guide import bundle_axis_paths
    from backend.core.bevel_plan import intersect_bevel_plane
    try:
        paths, (tangent, right, up) = bundle_axis_paths(
            design, request.cluster_id, request.position_bp, all_members=True)
    except ValueError as error:
        raise ValueError(str(error).replace('Corner', 'Bevel').replace('corner', 'bevel')) from error
    # Use every native duplex station, rather than the viewport's sparse tubes.
    from backend.core.corner_plan import AxisPath
    from backend.core.deformation import deformed_nucleotide_arrays
    exact = []
    for path in paths:
        helix = design.find_helix(path.helix_id).model_copy(update={'loop_skips': []})
        sites = deformed_nucleotide_arrays(helix, design)
        stations, indices = np.unique(sites['bp_indices'], return_index=True)
        axis = AxisPath(helix.id, tuple(stations), tuple(map(tuple, sites['axis_points'][indices])))
        exact.append(axis.clipped(path.stations_bp[0], path.stations_bp[-1]))
    paths = exact
    center = np.mean([p.point(request.position_bp) for p in paths], axis=0)
    theta, azimuth = math.radians(request.angle_deg), math.radians(request.direction_deg)
    normal = math.cos(theta) * tangent + math.sin(theta) * (
        math.cos(azimuth) * right + math.sin(azimuth) * up)
    cuts = []
    for path in paths:
        bps, points = path.arrays()
        bp, point = intersect_bevel_plane(bps, points, center, normal)
        retained = (np.vstack((points[bps < bp], point)) if request.trim_end == 'end'
                    else np.vstack((point, points[bps > bp])))
        cuts.append(dict(helix_id=path.helix_id, cut_bp=bp,
            incoming_nm=point.tolist(), outgoing_nm=point.tolist(),
            incoming_path_nm=retained.tolist(), outgoing_path_nm=[]))
    return dict(center_nm=center.tolist(), plane_normal=normal.tolist(), cuts=cuts)


def build(design, params):
    from backend.api.corner_build import _admit_references
    from backend.core.occupancy import require_unique_occupancy
    command = BevelCommand.model_validate(params)
    if command.proof_version == 1:
        guide = bevel_guide(design, command)
        selected = {row['helix_id'] for row in guide['cuts']}
        limits = {row['helix_id']: (math.floor(row['cut_bp'] + 1e-9)
            if command.trim_end == 'end' else math.ceil(row['cut_bp'] - 1e-9)) for row in guide['cuts']}
        def keep(hid, bp):
            return hid not in limits or (bp <= limits[hid] if command.trim_end == 'end' else bp >= limits[hid])
    else:
        from backend.api.bevel_live import source_axes, retained_sites
        retained = retained_sites(source_axes(design, command.cluster_id), command)
        selected = set(retained)
        def keep(hid, bp):
            return hid not in retained or bp in retained[hid]
    try:
        _admit_references(design, selected, command.cluster_id)
    except ValueError as error:
        raise ValueError(str(error).replace('Corner', 'Bevel')) from error
    if any(ref.helix_id in selected for cluster in design.cluster_transforms for ref in cluster.base_ids):
        raise ValueError('Bevel must resolve base-scoped placement membership before trimming this bundle.')
    marks = {}
    for helix in design.helices:
        for mark in helix.loop_skips:
            key = (helix.id, mark.bp_index)
            marks[key] = marks.get(key, 0) + mark.delta
    strands = []
    for source in design.strands:
        if not any(d.helix_id in selected for d in source.domains):
            strands.append(source)
            continue
        if any(d.overhang_id or d.binds_overhang_id for d in source.domains):
            raise ValueError('Bevel requires duplex strands without attached overhang domains.')
        sequences = _sequence_fragments(source, marks)
        groups, domains, bases = [], [], []
        def flush():
            nonlocal domains, bases
            if domains:
                groups.append((domains, ''.join(bases) if sequences is not None else None))
            domains, bases = [], []
        for index, domain in enumerate(source.domains):
            step = 1 if domain.end_bp >= domain.start_bp else -1
            stations = list(range(domain.start_bp, domain.end_bp + step, step))
            run = []
            def append_run():
                if run:
                    domains.append(domain.model_copy(update={'start_bp': run[0], 'end_bp': run[-1]}))
                    if sequences is not None:
                        bases.extend(sequences[index][bp] for bp in run)
                    run.clear()
            for bp in stations:
                if keep(domain.helix_id, bp):
                    run.append(bp)
                else:
                    append_run()
                    flush()
            append_run()
        flush()
        for index, (domains, sequence) in enumerate(groups):
            strands.append(source.model_copy(update={
                'id': source.id if index == 0 else corner_output_id(command.operation_id, 'bevel-strand', f'{source.id}:{index}'),
                'domains': domains, 'sequence': sequence,
                'routing_seed': source.routing_seed if domains == source.domains else [],
                'name': source.name if index == 0 or not source.name else f'{source.name} ({index + 1})',
            }))
    crossovers = [c for c in design.crossovers if all(keep(half.helix_id, half.index) for half in (c.half_a, c.half_b))]
    ligations = [c for c in design.forced_ligations if all(keep(getattr(c, end + '_helix_id'), getattr(c, end + '_bp'))
                 for end in ('three_prime', 'five_prime'))]
    # Construction axes/deformation frames remain unchanged. Occupied domains
    # determine displayed/exported material, avoiding a bend reparameterization.
    updated = design.copy_with(strands=strands, crossovers=crossovers, forced_ligations=ligations)
    require_unique_occupancy(updated)
    return updated, MutationReport()
