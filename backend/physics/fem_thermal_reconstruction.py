"""Per-prediction thermal reconstruction; immutable geometry is prepared once.

The full reconstruction remains the oracle and supplies the representative's
orientations/axis. This path emits only the identically aligned backbone XYZ.
"""

from collections import Counter
import math

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.deformation import deformed_nucleotide_positions
from backend.core.geometry import _frame_from_helix_axis, nucleotide_positions
from backend.core.sequences import domain_bp_range


class ThermalReconstruction:
    """Job-local context. Never reuse after changing the design or mesh."""

    def __init__(self, design, mesh, reference_positions):
        coverage, overhangs = set(), set()
        for strand in design.strands:
            for domain in strand.domains:
                keys = {
                    (domain.helix_id, bp, domain.direction.value)
                    for bp in domain_bp_range(domain)
                }
                coverage.update(keys)
                if domain.overhang_id:
                    overhangs.update(keys)
        covered = coverage - overhangs
        by_helix = {}
        for i, node in enumerate(mesh.nodes):
            by_helix.setdefault(node.helix_id, []).append(i)
        self.helices = []
        self.keys = []
        shown_points = []
        seen = Counter()
        for helix in design.helices:
            if helix.id not in by_helix:
                continue
            indices = np.array(
                sorted(by_helix[helix.id], key=lambda i: mesh.nodes[i].global_bp)
            )
            bps = np.array([mesh.nodes[i].global_bp for i in indices], dtype=float)
            start = helix.axis_start.to_array()
            axis = helix.axis_end.to_array() - start
            axis /= np.linalg.norm(axis) or 1.0
            frame = _frame_from_helix_axis(axis)
            straight = list(nucleotide_positions(helix))
            shown = list(deformed_nucleotide_positions(helix, design))
            if len(shown) != len(straight):
                shown = straight
            keep = [
                i
                for i, n in enumerate(straight)
                if (n.helix_id, n.bp_index, n.direction.value) in covered
            ]
            # The winding's reference projection uses the exact scalar arithmetic
            # of the full path, once rather than once per thermal frame.
            xyz = np.asarray([n.position for n in straight]).reshape(-1, 3)[keep]
            axial = np.array([float((p - start) @ axis) for p in xyz])
            perp = xyz - (start + axial[:, None] * axis)
            radii = np.array([float(np.linalg.norm(p)) for p in perp])
            angles = [
                math.atan2(float(p @ frame[:, 1]), float(p @ frame[:, 0])) for p in perp
            ]
            radial_c = radii * np.array([math.cos(a) for a in angles])
            radial_s = radii * np.array([math.sin(a) for a in angles])
            x = helix.bp_start + axial / BDNA_RISE_PER_BP
            left, right = x <= bps[0], x >= bps[-1]
            k = np.clip(np.searchsorted(bps, x) - 1, 0, max(0, len(bps) - 2))
            if len(bps) > 1:
                span = bps[k + 1] - bps[k]
                fraction = np.divide(
                    x - bps[k], span, out=np.zeros_like(x), where=span > 1e-9
                )
                near = np.where(fraction < 0.5, k, k + 1)
                near[left], near[right] = 0, len(bps) - 1
            else:
                fraction, near = np.zeros_like(x), np.zeros(len(x), dtype=int)
            ref_axis = np.array(
                [start + (bp - helix.bp_start) * BDNA_RISE_PER_BP * axis for bp in bps]
            )
            self.helices.append(
                (
                    indices,
                    ref_axis,
                    frame[:, 0],
                    xyz,
                    x,
                    bps,
                    left,
                    right,
                    k,
                    fraction,
                    near,
                    radial_c,
                    radial_s,
                )
            )
            for i in keep:
                n = straight[i]
                key = (n.helix_id, n.bp_index, n.direction.value)
                self.keys.append([*key, seen[key]])
                seen[key] += 1
                shown_points.append(shown[i].position)
        self.target = np.asarray(shown_points).reshape(-1, 3)
        self.core_count = len(self.keys)
        # Passive terminal beads follow their core anchor by an unchanged native
        # offset. Recover that offset from the already computed static result;
        # the predicted anchor displacement cancels exactly in this subtraction.
        anchors = {}
        for strand in design.strands:
            if not strand.id.startswith("polymer-terminal::"):
                continue
            tails = [i for i, d in enumerate(strand.domains) if d.overhang_id]
            if len(tails) != 1:
                continue
            ti = tails[0]
            ci = ti + 1 if ti == 0 else ti - 1
            if not 0 <= ci < len(strand.domains):
                continue
            tail, core = strand.domains[ti], strand.domains[ci]
            core_bps = list(domain_bp_range(core))
            if not core_bps:
                continue
            anchor = (
                core.helix_id,
                core_bps[0] if ti == 0 else core_bps[-1],
                core.direction.value,
                0,
            )
            for bp in domain_bp_range(tail):
                anchors[(tail.helix_id, bp, tail.direction.value, 0)] = anchor
        strands = {s.id: s for s in design.strands}
        for extension in design.extensions:
            strand = strands.get(extension.strand_id)
            if strand is None or not strand.domains:
                continue
            domain = (
                strand.domains[0]
                if extension.end == "five_prime"
                else strand.domains[-1]
            )
            bp = domain.start_bp if extension.end == "five_prime" else domain.end_bp
            anchor = (domain.helix_id, int(bp), domain.direction.value, 0)
            for p in reference_positions[self.core_count :]:
                if p["helix_id"] == f"__ext_{extension.id}":
                    anchors[_key(p)] = anchor
        reference_keys = [_key(p) for p in reference_positions]
        if reference_keys[: self.core_count] != [tuple(k) for k in self.keys]:
            raise ValueError(
                "Thermal reconstruction core identities differ from static reconstruction"
            )
        core_columns = {tuple(k): i for i, k in enumerate(self.keys)}
        self.followers = []
        for p in reference_positions[self.core_count :]:
            key = _key(p)
            anchor_col = core_columns[anchors[key]]
            offset = (
                np.asarray(p["backbone_position"])
                - reference_positions[anchor_col]["backbone_position"]
            )
            self.followers.append((anchor_col, offset))
            self.keys.append(list(key))

    def coordinates(self, u):
        from backend.physics.fem_solver import (
            _rmf_frames,
            _kabsch_transform,
            _apply_transform,
        )

        dofs = np.asarray(u).reshape(-1, 6)
        output = np.empty((len(self.keys), 3))
        cursor = 0
        for (
            indices,
            reference,
            seed,
            straight,
            x,
            bps,
            left,
            right,
            k,
            f,
            near,
            rc,
            rs,
        ) in self.helices:
            if len(indices) < 2:
                wound = straight
            else:
                points = reference + dofs[indices, :3]
                tans, e1, e2 = _rmf_frames(points, seed)
                twist = np.sum(dofs[indices, 3:] * tans, axis=1)
                c, s = np.cos(twist)[:, None], np.sin(twist)[:, None]
                e1, e2 = c * e1 + s * e2, -s * e1 + c * e2
                pos = points[k] * (1 - f[:, None]) + points[k + 1] * f[:, None]
                pos[left] = (
                    points[0] + (x[left] - bps[0])[:, None] * BDNA_RISE_PER_BP * tans[0]
                )
                pos[right] = (
                    points[-1]
                    + (x[right] - bps[-1])[:, None] * BDNA_RISE_PER_BP * tans[-1]
                )
                wound = pos + rc[:, None] * e1[near] + rs[:, None] * e2[near]
            output[cursor : cursor + len(wound)] = wound
            cursor += len(wound)
        core = output[: self.core_count]
        core[:] = _apply_transform(core, *_kabsch_transform(core, self.target))
        for i, (anchor, offset) in enumerate(self.followers, self.core_count):
            output[i] = core[anchor] + offset
        return output


def _key(p):
    return p["helix_id"], int(p["bp_index"]), p["direction"], int(p.get("copy", 0))


def ensemble_statistics(frames, keys, nodes, modal_rmsf):
    """Same ensemble/representative rule, with bounded coordinate temporaries."""
    xyz = frames.reshape(len(frames), -1, 3)
    point_msf = np.empty(xyz.shape[:2])
    for start in range(0, xyz.shape[1], 4096):
        block = xyz[:, start : start + 4096]
        point_msf[:, start : start + 4096] = np.sum(
            (block - np.mean(block, axis=0, keepdims=True)) ** 2, axis=2
        )
    node_columns = {(node.helix_id, node.global_bp): i for i, node in enumerate(nodes)}
    columns = np.array(
        [node_columns.get((k[0], int(k[1])), -1) for k in keys], dtype=int
    )
    keep = columns >= 0
    counts = np.bincount(columns[keep], minlength=len(nodes))
    bp_msf = np.empty((len(frames), len(nodes)))
    for i, row in enumerate(point_msf):
        sums = np.bincount(columns[keep], weights=row[keep], minlength=len(nodes))
        bp_msf[i] = np.divide(
            sums, counts, out=np.asarray(modal_rmsf) ** 2, where=counts > 0
        )
    rmsf = np.sqrt(np.mean(bp_msf, axis=0))
    target = rmsf**2
    scale = np.maximum(target, max(float(np.mean(target)), 1e-12) * 0.05)
    scores = np.mean(((bp_msf - target[None, :]) / scale[None, :]) ** 2, axis=1)
    return rmsf, int(np.argmin(scores))
