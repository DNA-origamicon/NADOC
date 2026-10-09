"""Rebase authored topology onto an edited sweep without replaying routing tools.

Domains use shared half-open cuts, so proportional rounding cannot open gaps at
nicks. Material outside the generated span translates with its end, rather than
scaling. IDs, strand traversal, ligations and downstream feature order survive.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import ClusterRigidTransform, Direction, Vec3

FOLLOW_PREFIX = 'sweep-follow:'


def restore_follow_poses(design, snapshot):
    return [c for c in design.cluster_transforms if not c.id.startswith(FOLLOW_PREFIX)] + [
        c for c in snapshot.cluster_transforms if c.id.startswith(FOLLOW_PREFIX)]


class SweepEdit:
    def __init__(self, created, rebuilt, sweep_id, attachments=(), resized=()):
        self.old = next(o for o in created.deformations if o.id == 'sweep_' + sweep_id)
        self.new = next(o for o in rebuilt.deformations if o.id == self.old.id)
        self.ids = set(self.old.affected_helix_ids)
        if self.ids != set(self.new.affected_helix_ids):
            raise ValueError('Changing the sweep footprint with downstream edits is not supported; keep the cells and edit the path.')
        self.generated_marks = {h.id: {m.bp_index: m.delta for m in h.loop_skips} for h in created.helices if h.id in self.ids}
        self.attachments = attachments
        self.shifts = {}
        for _, source, _, bp, members in attachments:
            if source in self.ids or source in self.shifts:
                shift = self.site(bp) - bp if source in self.ids else self.shifts[source]
                self.shifts.update({hid: shift for hid in members})
        self.resized = resized
        self.warnings = set()

    def cut(self, bp):
        a, b = self.old.plane_a_bp, self.old.plane_b_bp + 1
        c, d = self.new.plane_a_bp, self.new.plane_b_bp + 1
        if bp <= a:
            return c + bp - a
        if bp >= b:
            return d + bp - b
        return c + int(np.floor((bp - a) * (d - c) / (b - a) + .5))

    def site(self, bp):
        # Interior markers follow proportional position; outer endpoints retain
        # their signed distance from the generated blunt end.
        a, b = self.old.plane_a_bp, self.old.plane_b_bp
        c, d = self.new.plane_a_bp, self.new.plane_b_bp
        if bp <= a:
            return c + bp - a
        if bp >= b:
            return d + bp - b
        return c + int(np.floor((bp - a) * (d - c) / max(1, b - a) + .5))

    def map_site(self, hid, bp):
        return self.site(bp) if hid in self.ids else bp + self.shifts.get(hid, 0)

    def parameters(self, value):
        if isinstance(value, list):
            return [self.parameters(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {k: self.parameters(v) for k,v in value.items()}
        hid = value.get('helix_id')
        if hid in self.ids or hid in self.shifts:
            for key in ('bp_index', 'index', 'start_bp', 'end_bp'):
                if isinstance(value.get(key), int):
                    result[key] = self.map_site(hid, value[key])
        if isinstance(value.get('source_bp'), int):
            result['source_bp'] = self.map_site(value.get('ref_helix_id'), value['source_bp'])
        return result

    def deformation(self, op):
        if op.id == self.old.id:
            return self.new
        if op.affected_helix_ids and set(op.affected_helix_ids) <= self.ids:
            return op.model_copy(update={'plane_a_bp': self.site(op.plane_a_bp), 'plane_b_bp': self.site(op.plane_b_bp)})
        shifts = {self.shifts[hid] for hid in op.affected_helix_ids if hid in self.shifts}
        if len(shifts) == 1 and all(hid in self.shifts for hid in op.affected_helix_ids):
            shift = shifts.pop()
            changes = {'plane_a_bp': op.plane_a_bp+shift, 'plane_b_bp': op.plane_b_bp+shift}
            if op.type == 'sweep':
                changes['params'] = op.params.model_copy(update={'warning_bps': [bp+shift for bp in op.params.warning_bps]})
            return op.model_copy(update=changes)
        return op

    def rebase(self, design):
        if not any(o.id == self.old.id for o in design.deformations):
            return design
        pins = {}
        # Explicit terminal resizing keeps its offset from the original end,
        # including a trimmed end inside the generated span.
        for hid, direction, before, after in self.resized:
            if hid in self.ids:
                anchor = pins.get((hid, direction, before), self.cut(before))
                pins[(hid, direction, after)] = anchor + after - before
        # Inline overhangs (and their complements) retain their nucleotide count.
        for strand in design.strands:
            for dom in strand.domains:
                if dom.helix_id in self.ids and (dom.overhang_id or dom.binds_overhang_id):
                    lo, hi = sorted((dom.start_bp, dom.end_bp))
                    if hi >= self.old.plane_b_bp:
                        delta = self.new.plane_b_bp - self.old.plane_b_bp
                    elif lo <= self.old.plane_a_bp:
                        delta = self.new.plane_a_bp - self.old.plane_a_bp
                    else:
                        delta = self.cut(lo) - lo
                    pins[(dom.helix_id, dom.direction, lo)] = lo + delta
                    pins[(dom.helix_id, dom.direction, hi + 1)] = hi + 1 + delta

        def boundary(hid, direction, bp):
            return pins.get((hid, direction, bp), self.cut(bp))

        def endpoint(hid, direction, bp, three_prime):
            if hid not in self.ids:
                return bp + self.shifts.get(hid, 0)
            upper = (direction == Direction.FORWARD) == three_prime
            return boundary(hid, direction, bp + int(upper)) - int(upper)

        def domain(dom):
            if dom.helix_id not in self.ids:
                shift = self.shifts.get(dom.helix_id, 0)
                return dom.model_copy(update={'start_bp': dom.start_bp+shift, 'end_bp':dom.end_bp+shift}) if shift else dom
            lo, hi = sorted((dom.start_bp, dom.end_bp))
            low = boundary(dom.helix_id, dom.direction, lo)
            high = boundary(dom.helix_id, dom.direction, hi + 1) - 1
            if high < low:
                raise ValueError(f'Sweep shortening collapses a domain on {dom.helix_id} at {lo}–{hi} bp. Lengthen the path or remove that conflicting edit first.')
            return dom.model_copy(update={'start_bp': low if dom.direction == Direction.FORWARD else high,
                                          'end_bp': high if dom.direction == Direction.FORWARD else low})

        strands = []
        for strand in design.strands:
            domains = [domain(d) for d in strand.domains]
            if strand.sequence is not None and domains != strand.domains:
                self.warnings.add('Assigned sequences were retained; changed domain lengths require sequence review.')
            strands.append(strand.model_copy(update={'domains': domains,
                'routing_seed': None if strand.routing_seed is None else [domain(d) for d in strand.routing_seed]}))
        helices = []
        for h in design.helices:
            if h.id not in self.ids:
                shift = self.shifts.get(h.id, 0)
                if shift:
                    from backend.core.deformation import effective_helix_for_geometry
                    h = effective_helix_for_geometry(h, design)
                    h = h.model_copy(update={'bp_start': h.bp_start+shift,
                        'loop_skips': [m.model_copy(update={'bp_index':m.bp_index+shift}) for m in h.loop_skips]})
                helices.append(h)
                continue
            lo, hi = self.cut(h.bp_start), self.cut(h.bp_start + h.length_bp) - 1
            # Coverage may include pinned, shortened strand ends.
            spans = [d for s in strands for d in s.domains if d.helix_id == h.id]
            if spans:
                lo = min(min(d.start_bp, d.end_bp) for d in spans)
                hi = max(max(d.start_bp, d.end_bp) for d in spans)
            start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
            axis = np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z]) - start
            axis /= max(np.linalg.norm(axis), 1e-12)
            def at(bp):
                return Vec3(**dict(zip('xyz', start + axis * (bp - h.bp_start) * RISE)))
            marks = {}
            for mark in h.loop_skips:
                bp = self.site(mark.bp_index)
                if bp in marks:
                    self.warnings.add(f'Loop/skip marks collide on {h.id} at {bp} bp; review curvature encoding.')
                marks[bp] = mark.model_copy(update={'bp_index': bp})
            helices.append(h.model_copy(update={'bp_start': lo, 'length_bp': hi-lo+1,
                'axis_start': at(lo), 'axis_end': at(hi),
                'phase_offset': h.phase_offset + (lo-h.bp_start)*h.twist_per_bp_rad,
                'loop_skips': list(marks.values())}))
        crossovers = []
        for xo in design.crossovers:
            halves = {name: half.model_copy(update={'index': self.map_site(half.helix_id, half.index)})
                      for name, half in [('half_a', xo.half_a), ('half_b', xo.half_b)]}
            if any(halves[k] != getattr(xo, k) for k in halves):
                self.warnings.add('Crossovers moved proportionally; review helical register and junction geometry.')
            crossovers.append(xo.model_copy(update=halves))
        ligations = []
        for fl in design.forced_ligations:
            changes = {}
            for label, three in [('three_prime', True), ('five_prime', False)]:
                changes[label+'_bp'] = endpoint(getattr(fl,label+'_helix_id'), getattr(fl,label+'_direction'), getattr(fl,label+'_bp'), three)
            ligations.append(fl.model_copy(update=changes))
        ops = [self.deformation(op) for op in design.deformations]
        out = design.copy_with(helices=helices, strands=strands, crossovers=crossovers,
                               forced_ligations=ligations, deformations=ops)
        # Recompute automatic curvature marks against the retained routing,
        # preserving explicitly changed marks as authored overrides.
        if self.new.params.auto_loop_skips:
            from backend.core.sweep_loop_skips import generated_sweep_loop_skips
            authored, removed = {}, {}
            for h in design.helices:
                if h.id not in self.ids:
                    continue
                original = self.generated_marks.get(h.id, {})
                current = {m.bp_index: m.delta for m in h.loop_skips}
                authored[h.id] = [m.model_copy(update={'bp_index': self.site(m.bp_index)}) for m in h.loop_skips
                                  if original.get(m.bp_index) != m.delta]
                removed[h.id] = {self.site(bp) for bp in original.keys() - current.keys()}
            marks, warnings = generated_sweep_loop_skips(out, self.new, existing=authored)
            self.warnings.update(warnings)
            updated = []
            for h in out.helices:
                if h.id in self.ids:
                    merged = {m.bp_index:m for m in marks.get(h.id, []) if m.bp_index not in removed.get(h.id,set())}
                    merged.update({m.bp_index:m for m in authored.get(h.id,[])})
                    h = h.model_copy(update={'loop_skips': [merged[bp] for bp in sorted(merged)]})
                updated.append(h)
            out = out.copy_with(helices=updated)
        return self.follow_attachments(design, out)

    def follow_attachments(self, before, after):
        from backend.core.sweep import _site_frame
        moving = set(self.ids)
        for key, source, end, source_bp, members in self.attachments:
            if source not in moving or before.find_helix(source) is None or after.find_helix(source) is None:
                continue
            members = [hid for hid in members if after.find_helix(hid)]
            if not members:
                continue
            p, a = _site_frame(before, before.find_helix(source), end, bp=source_bp)
            q, b = _site_frame(after, after.find_helix(source), end, bp=self.map_site(source, source_bp))
            rotation = b @ a.T
            offset = q - rotation @ p
            cid = FOLLOW_PREFIX + key
            previous = next((c for c in after.cluster_transforms if c.id == cid), None)
            old_r = Rotation.from_quat(previous.rotation).as_matrix() if previous else np.eye(3)
            old_t = np.asarray(previous.translation) if previous else np.zeros(3)
            pose = ClusterRigidTransform(id=cid, name='Sweep attachment', auto_created=True,
                helix_ids=members, rotation=Rotation.from_matrix(rotation @ old_r).as_quat().tolist(),
                translation=(rotation @ old_t + offset).tolist())
            after = after.copy_with(cluster_transforms=[c for c in after.cluster_transforms if c.id != cid] + [pose])
            moving.update(members)
        if any((f.three_prime_helix_id in moving) != (f.five_prime_helix_id in moving) for f in after.forced_ligations):
            self.warnings.add('Connections to stationary geometry were retained; review their span after moving the sweep.')
        return after
