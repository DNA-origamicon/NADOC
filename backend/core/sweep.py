"""Sweep authoring: canonical lattice topology plus one persisted spline overlay."""
import math
import uuid
from typing import Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import DeformationOp, Direction, ClusterRigidTransform
from backend.core.sweep_model import SweepParams
from backend.core.sweep_path import path_table, sample_path, rotation_between


class SweepRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sweep_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    cells: list[tuple[StrictInt, StrictInt]] = Field(min_length=1, max_length=16641)
    points_nm: list[tuple[float, float, float]] = Field(min_length=2, max_length=256)
    plane: Literal['XY', 'XZ', 'YZ'] = 'XY'
    strand_filter: Literal['both', 'scaffold', 'staples'] = 'both'
    ligate_adjacent: bool = True
    source_helix_id: str | None = None
    source_end: Literal['start', 'end'] = 'end'
    expected_design_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def validate_path(self):
        if any(abs(v) > 10000 for cell in self.cells for v in cell):
            raise ValueError('Sweep lattice coordinates must be within ±10000')
        if len(set(self.cells)) != len(self.cells):
            raise ValueError('Sweep cells must be unique')
        if any(not math.isfinite(v) or abs(v) > 10000 for p in self.points_nm for v in p):
            raise ValueError('Sweep coordinates must be finite and within ±10000 nm')
        if self.points_nm[0] != (0, 0, 0):
            raise ValueError('The first sweep point is the fixed origin (0, 0, 0)')
        if self.expected_revision is not None and self.expected_design_id is None:
            raise ValueError('A revision guard requires a design ID')
        return self


def _site_frame(design, helix, end):
    from backend.core.deformation import deformed_nucleotide_arrays, effective_helix_for_geometry
    from backend.core.geometry import nucleotide_positions_arrays
    effective = effective_helix_for_geometry(helix, design)
    rest = nucleotide_positions_arrays(effective)
    world = deformed_nucleotide_arrays(helix, design)
    bp = helix.bp_start + (helix.length_bp - 1 if end == 'end' else 0)
    candidates = np.flatnonzero((world['bp_indices'] == bp) & (world['directions'] == 1))
    # Array directions are 0 (forward) and 1 (reverse).
    if not len(candidates):
        candidates = np.flatnonzero(world['bp_indices'] == bp)
    if not len(candidates):
        raise ValueError('The selected end has no geometric site')
    i = int(candidates[0])
    j = int(np.flatnonzero((rest['bp_indices'] == bp) & (rest['directions'] == world['directions'][i]))[0])
    def basis(arr, k):
        t = arr['axis_tangents'][k]
        r = arr['radial_hats'][k]
        return np.column_stack([r, np.cross(t, r), t])
    return world['axis_points'][i], basis(world, i) @ basis(rest, j).T


def sweep_source(design, body):
    """Resolve an actual helix end, never infer attachment by spatial proximity."""
    from backend.core.lattice import _lattice_position
    normal = np.eye(3)[{'XY': 2, 'XZ': 1, 'YZ': 0}[body.plane]]
    if body.source_helix_id is None:
        from backend.core.lattice_occupancy import require_vacant_lattice_cells
        require_vacant_lattice_cells(design, body.cells, body.plane)
        coords = [_lattice_position(r, c, design.lattice_type) for r, c in body.cells]
        xy = np.mean(coords, axis=0)
        origin = np.array({'XY': [*xy, 0], 'XZ': [xy[0], 0, xy[1]], 'YZ': [0, *xy]}[body.plane])
        return dict(origin=origin, rotation=np.eye(3), normal=normal, sources={}, bp=0,
                    direction=1, clusters=[])
    ref = design.find_helix(body.source_helix_id)
    if ref is None or ref.grid_pos is None:
        raise ValueError('Select a lattice helix end')
    if ref.grid_pos not in body.cells:
        raise ValueError('The footprint must include the selected source helix')
    plane = next((f.plane for f in design.lattice_frames if f.id == ref.lattice_frame_id), None)
    if plane is None:
        import re
        match = re.match(r'h_(XY|XZ|YZ)_', ref.id)
        plane = match[1] if match else body.plane
    if plane != body.plane:
        raise ValueError('Sweep plane must match the source lattice plane')
    bp = ref.bp_start + (ref.length_bp - 1 if body.source_end == 'end' else 0)
    from backend.core.deformation import _arm_helices_for, _clusters_for_helix
    clusters = _clusters_for_helix(design, ref.id)
    cluster_ids = {c.id for c in clusters}
    members = [h for h in _arm_helices_for(design, ref.id)
               if h.lattice_frame_id == ref.lattice_frame_id
               and {c.id for c in _clusters_for_helix(design, h.id)} == cluster_ids]
    ref_site, rotation = _site_frame(design, ref, body.source_end)
    right, up = {'XY': ([1,0,0], [0,1,0]), 'XZ': ([1,0,0], [0,0,1]), 'YZ': ([0,1,0], [0,0,1])}[body.plane]
    ref_xy = np.asarray(_lattice_position(*ref.grid_pos, design.lattice_type))
    sources, sites = {}, []
    for cell in body.cells:
        matches = [h for h in members if h.grid_pos == cell
                   and h.bp_start + (h.length_bp - 1 if body.source_end == 'end' else 0) == bp]
        if len(matches) > 1:
            raise ValueError(f'Cell {cell} has ambiguous ends on the selected cross-section')
        delta = np.asarray(_lattice_position(*cell, design.lattice_type)) - ref_xy
        site = ref_site + rotation @ (np.asarray(right) * delta[0] + np.asarray(up) * delta[1])
        if matches:
            h = matches[0]
            actual, pose = _site_frame(design, h, body.source_end)
            if not np.allclose(pose, rotation, atol=1e-5) or not np.allclose(actual, site, atol=1e-5):
                raise ValueError('Selected ends do not share one cross-section frame')
            sources[cell] = h
        elif any(h.grid_pos == cell and h.bp_start <= bp < h.bp_start + h.length_bp for h in members):
            raise ValueError(f'Cell {cell} is occupied through the selected cross-section')
        sites.append(site)
    return dict(origin=np.mean(sites, axis=0), rotation=rotation, normal=normal,
                sources=sources, bp=bp, direction=1 if body.source_end == 'end' else -1,
                clusters=clusters)


def sweep_preview(design, body, *, include_geometry=False):
    source = sweep_source(design, body)
    initial = source['rotation'] @ source['normal'] * source['direction'] if body.source_helix_id else None
    points = tuple(body.points_nm)
    table = path_table(points, None if initial is None else tuple(initial))
    length = float(table[2][-1])
    steps = max(1, round(length / RISE))
    count = steps if body.source_helix_id else steps + 1
    if count * len(body.cells) > 200_000:
        raise ValueError('Sweep exceeds 200000 base-pair cells')
    positions, _, _ = sample_path(points, np.linspace(0, length, min(1025, max(65, steps + 1))),
                                  None if initial is None else tuple(initial))
    right, up = {'XY': ([1, 0, 0], [0, 1, 0]), 'XZ': ([1, 0, 0], [0, 0, 1]), 'YZ': ([0, 1, 0], [0, 0, 1])}[body.plane]
    from backend.core.lattice import _lattice_position
    xy = np.mean([_lattice_position(r, c, design.lattice_type) for r, c in body.cells], axis=0)
    right, up = source['rotation'] @ right, source['rotation'] @ up
    frame = dict(grid_origin=(source['origin'] - right * xy[0] - up * xy[1]).tolist(),
                 frame_right=right.tolist(), frame_up=up.tolist(),
                 axis_dir=(source['rotation'] @ source['normal']).tolist())
    geometry = {}
    if include_geometry:
        # Bound the ghost mesh payload independently of the persisted DNA size.
        samples = min(513, max(2, 20000 // len(body.cells)), max(65, steps + 1))
        distances = np.linspace(length / steps if body.source_helix_id else 0, length, samples)
        centers, transported, _ = sample_path(points, distances, None if initial is None else tuple(initial))
        align = rotation_between(source['rotation'] @ source['normal'] * source['direction'], table[3][0])
        offsets = np.asarray([right * (c[0] - xy[0]) + up * (c[1] - xy[1])
                              for c in [_lattice_position(r, c, design.lattice_type) for r, c in body.cells]])
        axes = centers[None, :, :] + source['origin'] + np.einsum('nij,kj->kni', transported @ align, offsets)
        geometry = dict(helix_paths_nm=axes.tolist(), point_rotation=np.eye(3).tolist())
    return dict(**geometry, source_frame=frame, origin_nm=source['origin'].tolist(), path_nm=(positions + source['origin']).tolist(),
                points_nm=(np.asarray(points) + source['origin']).tolist(), length_nm=length,
                length_bp=count, direction=source['direction']), source


def _join_sources(design, bundle, sources, body):
    """Extend only strand terminals at the selected end, retaining traversal order.

    These domain boundaries are ordinary backbone continuations. The sweep's
    attachment metadata and the authored domain adjacency identify them across
    helix/frame records; creating ForcedLigation records would change their meaning.
    """
    by_new = {h.id: sources.get(tuple(cell)) for h, cell in zip(bundle.helices, body.cells)}
    additions = {}
    remaining = []
    for strand in bundle.strands:
        dom = strand.domains[0]
        parent = by_new[dom.helix_id]
        if parent is None:
            remaining.append(strand)
            continue
        bp = parent.bp_start + (parent.length_bp - 1 if body.source_end == 'end' else 0)
        append = (dom.direction == Direction.FORWARD) == (body.source_end == 'end')
        matches = []
        for old in design.strands:
            if old.is_reference or not old.domains:
                continue
            terminal = old.domains[-1] if append else old.domains[0]
            if (terminal.helix_id == parent.id and terminal.direction == dom.direction
                    and (terminal.end_bp if append else terminal.start_bp) == bp):
                matches.append(old)
        if len(matches) > 1:
            raise ValueError('Ambiguous strand terminal at sweep source')
        if matches:
            additions.setdefault(matches[0].id, []).append((append, dom))
        else:
            remaining.append(strand)
    result = []
    for old in design.strands:
        domains = list(old.domains)
        sequence = old.sequence
        if sequence is not None and old.id in additions:
            from backend.core.sequences import strand_sequence_length
            sequence = sequence.ljust(strand_sequence_length(design, old), 'N')
        for append, dom in additions.get(old.id, []):
            domains = domains + [dom] if append else [dom] + domains
            if sequence is not None:
                padding = 'N' * (abs(dom.end_bp - dom.start_bp) + 1)
                sequence = sequence + padding if append else padding + sequence
        result.append(old.model_copy(update={'domains': domains, 'sequence': sequence}) if old.id in additions else old)
    if not additions:
        raise ValueError('Selected ends have no open strand terminals to continue')
    return result + remaining


def build_sweep(design, body):
    from backend.core.lattice import make_bundle_design, ligate_new_strands
    preview, source = sweep_preview(design, body)
    count = preview['length_bp']
    direction = source['direction']
    start_bp = source['bp'] + 1 if direction == 1 and body.source_helix_id else source['bp'] - count if direction == -1 else 0
    token = str(body.sweep_id)
    if any(f.id == token for f in design.lattice_frames):
        raise ValueError('This sweep has already been created')
    bundle = make_bundle_design(body.cells, count, plane=body.plane,
        offset_nm=start_bp * RISE, id_suffix='_'+token,
        strand_filter=body.strand_filter, lattice_type=design.lattice_type)
    # Explicit grid identity is needed for every plane and for continuation.
    helices = [h.model_copy(update={'grid_pos': cell}) for h, cell in zip(bundle.helices, body.cells)]
    bundle = bundle.copy_with(helices=helices)
    strands = _join_sources(design, bundle, source['sources'], body) if body.source_helix_id else [*design.strands, *bundle.strands]
    origin, rotation = source['origin'], source['rotation']
    points = np.asarray(body.points_nm)
    clusters = list(design.cluster_transforms)
    new_ids = [h.id for h in helices]
    if source['clusters']:
        # Inherit rigid ownership while storing the new spline in that rest frame.
        from backend.core.deformation import _apply_cluster_transforms_to_point
        ref = design.find_helix(body.source_helix_id)
        transform = lambda p: np.asarray(_apply_cluster_transforms_to_point(p, source['clusters'], ref, design))
        offset = transform(np.zeros(3))
        rigid = np.column_stack([transform(v) - offset for v in np.eye(3)])
        origin = rigid.T @ (origin - offset)
        rotation = rigid.T @ rotation
        points = points @ rigid
        owners = {c.id for c in source['clusters']}
        clusters = [c.model_copy(update={'helix_ids': [*c.helix_ids, *new_ids]}) if c.id in owners else c for c in clusters]
    else:
        clusters.append(ClusterRigidTransform(id='sweep_cluster_'+token, name='Sweep', helix_ids=new_ids, auto_created=False))
    params = SweepParams(points_nm=points.tolist(), origin_nm=origin.tolist(),
        initial_rotation=rotation.ravel().tolist(),
        initial_tangent=(rotation @ source['normal'] * direction).tolist() if body.source_helix_id else None,
        preceding_op_ids=[o.id for o in design.deformations],
        direction=direction, start_step=1 if body.source_helix_id else 0,
        steps=count if body.source_helix_id else count-1, path_length_nm=preview['length_nm'])
    op = DeformationOp(id='sweep_'+token, type='sweep', params=params, plane_a_bp=start_bp,
        plane_b_bp=start_bp + count-1, affected_helix_ids=new_ids)
    # Legacy unscoped overlays must not silently deform freshly authored material.
    old_ids = [h.id for h in design.helices]
    ops = [o if o.affected_helix_ids else o.model_copy(update={'affected_helix_ids': old_ids}) for o in design.deformations]
    from backend.core.lattice_frame_model import LatticeFrame
    owner = next(c.id for c in clusters if new_ids[0] in c.helix_ids)
    frame = LatticeFrame(id=token, plane=body.plane, placement_cluster_id=owner)
    helices = [h.model_copy(update={'lattice_frame_id': frame.id}) for h in helices]
    result = design.copy_with(lattice_frames=[*design.lattice_frames, frame],
                              helices=[*design.helices, *helices], strands=strands,
                              cluster_transforms=clusters, deformations=[*ops, op])
    if body.ligate_adjacent:
        old_strands = {s.id for s in design.strands}
        result = ligate_new_strands(result, {s.id for s in result.strands if s.id not in old_strands})
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    return reconcile_cluster_membership(design, result, sweep_mutation_report(design, result, body))


def sweep_mutation_report(before, after, body):
    from backend.core.cluster_reconcile import MutationReport
    old_ids = {h.id for h in before.helices}
    source = sweep_source(before, body)['sources'] if body.source_helix_id else {}
    return MutationReport(new_helix_origins={h.id: source[h.grid_pos].id if h.grid_pos in source else body.source_helix_id
                                            for h in after.helices if h.id not in old_ids})
