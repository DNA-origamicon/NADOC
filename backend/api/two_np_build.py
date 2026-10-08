"""Materialize the temporary generator through NADOC's ordinary DNA operations.

All work is isolated; callers commit recorded commands only after placement succeeds.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.headless_build import scratch_session, full_autostaple
from backend.api.crud import (
    _build_nick,
    NickRequest,
    _build_overhang_extrude,
    OverhangExtrudeRequest,
)
from backend.api.overhang_patch import _build_overhang_patch, OverhangPatchRequest
from backend.api.routes_nanoparticles import _set_np_version_applied, _surface_owner
from backend.core.models import (
    Design,
    Direction,
    StrandType,
    OverhangSpec,
    ClusterRigidTransform,
    NanoparticleConnectionVersion,
    _backfill_dropped_junctions,
)
from backend.core.nanoparticle import build_thiol_conjugation, replace_gold_nanosphere
from backend.core.conjugate_strands import assign_conjugate_group
from backend.core.crossover_positions import crossover_neighbor
from backend.core.design_geometry import fitting_geometry
from backend.core.duplex_cluster import materialize_duplex_cluster
from backend.core.protein import resolve_overhang_anchor, _rotation_between
from backend.core.sequences import assign_staple_sequences
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.two_np_generator import (
    gold_particles,
    pair_frame,
    GeneratorSettings,
    RodCandidate,
)


def _params(history, key, defaults, editable=()):
    return history.params(key, defaults, editable) if history else defaults


def _record(history, before, after, kind, label, params, key, editable=()):
    if history:
        history.record(before, after, kind, label, params, key, editable)


def _handles(source, rod, particles, settings, history=None):
    """Copy particle-owned handles after detaching old connections in this copy."""
    ids = {p.id for p in particles}
    detached = source.model_copy(deep=True)
    for v in list(detached.nanoparticle_connection_versions):
        if v.applied and v.nanoparticle_id in ids:
            detached = _set_np_version_applied(detached, v.id, False)
    conjugations = [
        c for c in detached.nanoparticle_conjugations if c.nanoparticle_id in ids
    ]
    strand_ids = {r.strand_id for c in conjugations for r in c.surface_strands}
    helix_ids = {r.helix_id for c in conjugations for r in c.surface_strands}
    before = rod
    rod = rod.copy_with(
        nanoparticles=particles,
        nanoparticle_conjugations=conjugations,
        strands=[*rod.strands, *(s for s in detached.strands if s.id in strand_ids)],
        helices=[*rod.helices, *(h for h in detached.helices if h.id in helix_ids)],
        overhangs=[
            *rod.overhangs,
            *(o for o in detached.overhangs if o.strand_id in strand_ids),
        ],
        staple_groups=[
            *rod.staple_groups,
            *(
                g.model_copy(
                    update={
                        "strand_ids": [sid for sid in g.strand_ids if sid in strand_ids]
                    }
                )
                for g in detached.staple_groups
                if strand_ids.intersection(g.strand_ids)
            ),
        ],
    )
    # An applied handle's saved unbound helix can predate a particle move.
    # Rebuild its free radial carrier at the current body pose before rebinding.
    for particle in particles:
        rod = replace_gold_nanosphere(rod, particle.id, pose=particle.pose.values)
    if rod != before:
        _record(
            history,
            before,
            rod,
            "nanoparticle-strand-bind",
            "Prepare existing nanoparticle handles",
            {},
            "prepare-handles",
        )
    selected = []
    for index, particle in enumerate(particles):
        compatible = []
        for c in rod.nanoparticle_conjugations:
            if c.nanoparticle_id != particle.id:
                continue
            for record in c.surface_strands:
                s = rod.find_strand(record.strand_id)
                if (
                    s
                    and s.sequence
                    and 12 <= len(s.sequence) <= 60
                    and set(s.sequence.upper()) <= set("ACGT")
                    and len(s.domains) == 1
                    and record.overhang_id
                    and s.domains[0].helix_id == record.helix_id
                    and abs(s.domains[0].end_bp - s.domains[0].start_bp) + 1
                    == len(s.sequence)
                ):
                    compatible.append((c, record, s))
        if compatible:
            c, record, s = compatible[0]
            selected.append((c, record, s.sequence, True))
            continue
        # Deterministic, mixed-base prototype sequence; not a thermodynamic
        # sequence optimizer. Different particles get different handles.
        motif = (
            "ACGTGACTCAGTACGATC",
            "GTCAGATCGTACAGTCGA",
            "TCGATGACCTAGTCAGAC",
            "CATGTCAGGATCTACGTC",
        )[index]
        length = _params(
            history,
            f"overhang:{index}",
            {"length_bp": settings.duplex_bp},
            ("length_bp",),
        )["length_bp"]
        if not isinstance(length, int) or not 12 <= length <= 60:
            raise ValueError(
                "Generated duplex length must be an integer from 12 to 60 bp."
            )
        hp = _params(
            history,
            f"handle:{index}",
            {"sequence": (motif * 4)[:length], "spacer_nm": 0.7},
            ("sequence", "spacer_nm"),
        )
        seq = hp["sequence"]
        if (
            not isinstance(seq, str)
            or not 12 <= len(seq) <= 60
            or set(seq.upper()) - set("ACGT")
        ):
            raise ValueError("A generated handle needs 12–60 defined A/C/G/T bases.")
        c, hs, ss = build_thiol_conjugation(
            particle,
            scheme="direct_thiol",
            sequence=seq,
            count=1,
            spacer_nm=hp["spacer_nm"],
        )
        ss, group = assign_conjugate_group(rod, ss, prefix="NP", fallback="NP")
        record = c.surface_strands[0]
        spec = OverhangSpec(
            id=record.overhang_id,
            helix_id=record.helix_id,
            strand_id=record.strand_id,
            sequence=seq,
            label=ss[0].name,
            auxiliary_endpoint=True,
        )
        before = rod
        rod = rod.copy_with(
            helices=[*rod.helices, *hs],
            strands=[*rod.strands, *ss],
            overhangs=[*rod.overhangs, spec],
            nanoparticle_conjugations=[*rod.nanoparticle_conjugations, c],
            staple_groups=[*rod.staple_groups, group],
        )
        _record(
            history,
            before,
            rod,
            "nanoparticle-conjugate",
            f"Create thiol handle for nanoparticle {index + 1}",
            hp,
            f"handle:{index}",
            ("sequence", "spacer_nm"),
        )
        selected.append((c, record, seq, False))
    return rod, selected


def _add_root(
    design, rod_ids, target_z, length, five_prime, history=None, index=0, target_x=None
):
    """Choose a legal outward crossover phase near the target axial position."""
    pinned = _params(history, f"nick:{index}", {}, ("bp_index",)).get("bp_index")
    hs = [h for h in design.helices if h.id in rod_ids]
    occupied = {tuple(h.grid_pos) for h in hs}
    # Each connection needs an independently posed carrier. Reusing a carrier
    # at another Z site would couple the two duplex cluster transforms.
    overhang_carriers = {o.helix_id for o in design.overhangs}
    occupied.update(
        tuple(h.grid_pos)
        for h in design.helices
        if h.id in overhang_carriers and h.grid_pos is not None
    )
    candidates = []
    for h in hs:
        row, col = h.grid_pos
        center = h.axis_start.to_array()
        desired = int(round((target_z - center[2]) / BDNA_RISE_PER_BP))
        for bp in range(max(5, desired - 32), min(h.length_bp - 5, desired + 33)):
            if pinned is not None and bp != pinned:
                continue
            neighbor = crossover_neighbor(design.lattice_type, row, col, bp)
            if neighbor is None or neighbor in occupied:
                continue
            # Both anchors face +local Y; favor the uppermost exterior helices.
            from backend.core.lattice import honeycomb_position, square_position

            pos = (
                honeycomb_position
                if design.lattice_type.value == "HONEYCOMB"
                else square_position
            )
            delta = np.asarray(pos(*neighbor)) - np.asarray(pos(row, col))
            if delta[1] <= 0:
                continue
            cost = abs(bp - desired) * BDNA_RISE_PER_BP + 0.6 * (
                max(x.axis_start.y for x in hs) - center[1]
            )
            if target_x is not None:
                cost += abs(center[0] - target_x)
            candidates.append((cost, h.id, bp, neighbor))
    for _, hid, bp, neighbor in sorted(candidates):
        covered = [
            (s, d)
            for s in design.strands
            if s.strand_type == StrandType.STAPLE
            for d in s.domains
            if d.helix_id == hid
            and min(d.start_bp, d.end_bp) <= bp <= max(d.start_bp, d.end_bp)
        ]
        for s, d in covered:
            step = 1 if d.direction == Direction.FORWARD else -1
            cut = bp - step if five_prime else bp
            endpoint = (
                (s.domains[0].start_bp == bp and s.domains[0].helix_id == hid)
                if five_prime
                else (s.domains[-1].end_bp == bp and s.domains[-1].helix_id == hid)
            )
            try:
                trial = (
                    design
                    if endpoint
                    else _build_nick(
                        design,
                        NickRequest(helix_id=hid, bp_index=cut, direction=d.direction),
                    )
                )
                nicked = trial
                trial, _ = _build_overhang_extrude(
                    trial,
                    OverhangExtrudeRequest(
                        helix_id=hid,
                        bp_index=bp,
                        direction=d.direction,
                        is_five_prime=five_prime,
                        neighbor_row=neighbor[0],
                        neighbor_col=neighbor[1],
                        length_bp=length,
                    ),
                )
            except ValueError:
                continue
            added = next(
                o
                for o in trial.overhangs
                if o.id not in {v.id for v in design.overhangs}
            )
            carrier = trial.find_strand(added.strand_id)
            embedded = [domain for domain in carrier.domains if not domain.overhang_id]
            adjacent = embedded[0] if five_prime else embedded[-1]
            # Seven bases is one HC crossover interval; square candidates may
            # use longer intervals. Never leave a one-base anchoring stub.
            if abs(adjacent.end_bp - adjacent.start_bp) + 1 < 7:
                continue
            # A legal crossover phase alone does not guarantee a legal nick:
            # reject candidate splits that expose a crossover at a terminus.
            from backend.core.validator import validate_design

            if not validate_design(trial).passed:
                continue
            if not endpoint:
                _record(
                    history,
                    design,
                    nicked,
                    "nick",
                    f"Nick staple for nanoparticle {index + 1}",
                    {
                        "bp_index": bp,
                        "cut_bp_index": cut,
                        "helix_id": hid,
                        "direction": d.direction.value,
                    },
                    f"nick:{index}",
                    ("bp_index",),
                )
            _record(
                history,
                nicked,
                trial,
                "overhang-extrude",
                f"Extrude nanoparticle {index + 1} overhang",
                {
                    "length_bp": length,
                    "helix_id": hid,
                    "bp_index": bp,
                    "direction": d.direction.value,
                    "is_five_prime": five_prime,
                    "neighbor_row": neighbor[0],
                    "neighbor_col": neighbor[1],
                },
                f"overhang:{index}",
                ("length_bp",),
            )
            return trial, added.id
    raise ValueError(
        "No legal same-side staple attachment site was available near a particle. Try another duplex length or particle separation."
    )


def _joint(design, version, geometry):
    owner, record = _surface_owner(design, version.nanoparticle_id, version.strand_id)
    flag = "is_five_prime" if owner.attach_end == "5p" else "is_three_prime"
    point = next(
        n["backbone_position"]
        for n in geometry
        if n.get("strand_id") == version.strand_id and n.get(flag)
    )
    return np.asarray(point), np.asarray(record.backbone_attachment_local_nm)


def _fit_swing(
    root,
    joint,
    center,
    radius,
    frame,
    geometry,
    version,
    particles,
    centers,
    angles=None,
):
    """Search the sphere-intersection circle and duplex axial roll for clearance.

    Both rigid rotations preserve the exact graft joint and crossover bead.
    Evaluate emitted native DNA landmarks, including bases, before committing
    a pose; the shortest swing alone can put the opposite strand inside gold.
    """
    length = np.linalg.norm(joint - root)
    delta = center - root
    distance = np.linalg.norm(delta)
    if distance > length + radius + 1e-7 or distance < abs(length - radius) - 1e-7:
        raise ValueError(
            "The fixed-center attachment spheres do not intersect. Try a longer duplex."
        )
    unit = delta / distance
    a = (length**2 - radius**2 + distance**2) / (2 * distance)
    perpendicular = frame[:, 2] - unit * np.dot(frame[:, 2], unit)
    if np.linalg.norm(perpendicular) < 1e-8:
        reference = np.eye(3)[int(np.argmin(np.abs(unit)))]
        perpendicular = reference - unit * np.dot(reference, unit)
    perpendicular /= np.linalg.norm(perpendicular)
    other = np.cross(unit, perpendicular)
    circle_radius = np.sqrt(max(0, length**2 - a**2))
    points = np.array(
        [
            n[key]
            for n in geometry
            if n.get("strand_id") == version.strand_id
            or n.get("overhang_id") == version.overhang_id
            for key in ("backbone_position", "base_position")
        ]
    )
    best = None
    best_clearance = -float("inf")
    phases = (
        [np.radians(angles["phase_deg"])]
        if angles and "phase_deg" in angles
        else np.linspace(0, 2 * np.pi, 16, endpoint=False)
    )
    rolls = (
        np.array([np.radians(angles["duplex_roll_deg"])])
        if angles and "duplex_roll_deg" in angles
        else np.linspace(0, 2 * np.pi, 24, endpoint=False)
    )
    if not np.isfinite(phases).all() or not np.isfinite(rolls).all():
        raise ValueError("Attachment angles must be finite.")
    for phase in phases:
        target = (
            root
            + a * unit
            + circle_radius * (np.cos(phase) * perpendicular + np.sin(phase) * other)
        )
        swing = _rotation_between(joint - root, target - root)
        axis = (target - root) / length
        rotations = Rotation.from_rotvec(rolls[:, None] * axis).as_matrix() @ swing
        transformed = np.einsum("kij,nj->kni", rotations, points - root) + root
        clearance = np.min(
            np.stack(
                [
                    np.linalg.norm(transformed - c, axis=2) - p.diameter_nm / 2
                    for p, c in zip(particles, centers)
                ]
            ),
            axis=(0, 2),
        )
        index = int(np.argmax(clearance))
        if clearance[index] > best_clearance:
            best_clearance = clearance[index]
            best = (
                target,
                rotations[index],
                {
                    "phase_deg": float(np.degrees(phase)),
                    "duplex_roll_deg": float(np.degrees(rolls[index])),
                },
            )
    if best_clearance < 0:
        raise ValueError(
            "No sampled fixed-center duplex orientation clears all gold cores. Try a longer duplex or a different particle arrangement."
        )
    return best


def materialize(
    source: Design, candidate: RodCandidate, settings: GeneratorSettings, history=None
):
    from backend.core.lattice import make_bundle_design
    from backend.core.seamed_router import auto_scaffold_seamed
    from backend.core.two_np_generator import scaffold_nt

    from backend.core.platform_generator import platform_frame

    particles, centers, distance = gold_particles(source)
    platform = len(particles) > 2
    shape = "platform" if platform else "rod"
    pose_params = _params(
        history, "rod-pose", {"roll_deg": settings.roll_deg}, ("roll_deg",)
    )
    roll = GeneratorSettings(roll_deg=pose_params["roll_deg"]).roll_deg
    frame = platform_frame(centers, roll) if platform else pair_frame(centers, roll)
    origin = centers.mean(0)
    if platform:
        projected = (centers - origin) @ frame
        origin = origin + frame @ np.array(
            [
                (projected[:, 0].min() + projected[:, 0].max()) / 2,
                0,
                (projected[:, 2].min() + projected[:, 2].max()) / 2,
            ]
        )
    targets = (centers - origin) @ frame
    bp = _params(
        history,
        "bundle",
        {"length_bp": candidate.summary["nominal_length_bp"]},
        ("length_bp",),
    )
    if not isinstance(bp["length_bp"], int) or not 21 <= bp["length_bp"] <= 2016:
        raise ValueError("Bundle length must be an integer from 21 to 2016 bp.")
    before = Design(lattice_type=source.lattice_type, nanoparticles=particles)
    rod = make_bundle_design(
        candidate.summary["cells"],
        bp["length_bp"],
        name=f"Generated {len(particles)}-NP {shape}",
        lattice_type=source.lattice_type,
    )
    rod = rod.copy_with(nanoparticles=particles)
    _record(
        history,
        before,
        rod,
        "bundle-create",
        f"Create {shape} bundle",
        {
            **bp,
            "cells": candidate.summary["cells"],
            "lattice_type": source.lattice_type.value,
        },
        "bundle",
        ("length_bp",),
    )
    before = rod
    rod, routing = auto_scaffold_seamed(rod)
    if not routing.valid:
        raise ValueError("The edited bundle could not be routed as one scaffold.")
    _record(
        history,
        before,
        rod,
        "auto-scaffold-seamed",
        f"Route {shape} scaffold",
        {},
        "scaffold",
    )
    sequence_params = _params(
        history,
        "autostaple",
        {"scaffold_name": candidate.summary["scaffold_name"]},
        ("scaffold_name",),
    )
    budget = {"M13mp18": 7249, "p8064": 8064}.get(sequence_params["scaffold_name"])
    if budget is None or scaffold_nt(rod) > budget:
        raise ValueError(
            "The routed bundle exceeds the selected 7249/8064 scaffold budget."
        )
    before = rod
    with scratch_session(source.lattice_type):
        state.set_design(rod)
        rod = full_autostaple(sequence_params["scaffold_name"]).model_copy(deep=True)
    rod = rod.copy_with(feature_log=[], cluster_transforms=[])
    _record(
        history,
        before,
        rod,
        "full-autostaple",
        f"Route and sequence {shape} staples",
        sequence_params,
        "autostaple",
        ("scaffold_name",),
    )
    rod_ids = {h.id for h in rod.helices}
    starts = np.array([h.axis_start.to_array() for h in rod.helices])
    ends = np.array([h.axis_end.to_array() for h in rod.helices])
    center_local = (
        np.minimum(starts.min(0), ends.min(0)) + np.maximum(starts.max(0), ends.max(0))
    ) / 2
    rod, handles = _handles(source, rod, particles, settings, history)
    connections = []
    for index, (owner, record, sequence, reused) in enumerate(handles):
        target_z = center_local[2] + targets[index, 2]
        length = _params(
            history, f"overhang:{index}", {"length_bp": len(sequence)}, ("length_bp",)
        )["length_bp"]
        if length != len(sequence):
            raise ValueError(
                "Overhang length must match the retained handle sequence. Edit its conjugation sequence first."
            )
        rod, oid = _add_root(
            rod,
            rod_ids,
            target_z,
            length,
            owner.attach_end == "3p",
            history,
            index,
            target_x=center_local[0] + targets[index, 0] if platform else None,
        )
        rc = sequence.upper().translate(str.maketrans("ACGT", "TGCA"))[::-1]
        before = rod
        sp = _params(history, f"sequence:{index}", {"sequence": rc}, ("sequence",))
        rod, _, _ = _build_overhang_patch(
            rod,
            oid,
            OverhangPatchRequest(
                sequence=sp["sequence"], label=f"NP {index + 1} anchor"
            ),
        )
        _record(
            history,
            before,
            rod,
            "overhang-sequence",
            f"Sequence nanoparticle {index + 1} overhang",
            sp,
            f"sequence:{index}",
            ("sequence",),
        )
        connections.append(
            dict(
                particle_id=particles[index].id,
                strand_id=record.strand_id,
                overhang_id=oid,
                reused=reused,
                duplex_bp=len(sequence),
            )
        )
    before = rod
    rod = assign_staple_sequences(rod)
    _backfill_dropped_junctions(rod)
    _record(
        history,
        before,
        rod,
        "assign-staple-sequences",
        "Assign attachment staple sequences",
        {},
        "attachment-sequences",
    )
    np_hids = {
        r.helix_id for c in rod.nanoparticle_conjugations for r in c.surface_strands
    }
    cluster = ClusterRigidTransform(
        name=f"Generated {shape}",
        helix_ids=[h.id for h in rod.helices if h.id not in np_hids],
        rotation=Rotation.from_matrix(frame).as_quat().tolist(),
        translation=(origin - frame @ center_local).tolist(),
    )
    before = rod
    rod = rod.copy_with(cluster_transforms=[cluster])
    _record(
        history,
        before,
        rod,
        "cluster-pose",
        f"Align {shape} with nanoparticle centers",
        pose_params,
        "rod-pose",
        ("roll_deg",),
    )
    for index, item in enumerate(connections):
        before = rod
        v = NanoparticleConnectionVersion(
            name="Generated attachment",
            nanoparticle_id=item["particle_id"],
            strand_id=item["strand_id"],
            overhang_id=item["overhang_id"],
            direct_variant="end-to-root",
        )
        rod = rod.copy_with(
            nanoparticle_connection_versions=[*rod.nanoparticle_connection_versions, v]
        )
        rod = _set_np_version_applied(rod, v.id, True)
        _record(
            history,
            before,
            rod,
            "nanoparticle-connection-version-create",
            f"Pair nanoparticle {index + 1} handle and overhang",
            item,
            f"connect:{index}",
        )
    # One common offset must be reachable by every actual duplex, including
    # unequal core sizes and particle centers displaced from the fitted plane.
    geometry = fitting_geometry(rod)
    upper = float("inf")
    lower = (
        float(np.max(starts[:, 1]) - center_local[1])
        + max(p.diameter_nm / 2 - targets[i, 1] for i, p in enumerate(particles))
        + 1.2
    )
    for i, v in enumerate(rod.nanoparticle_connection_versions):
        root, _ = resolve_overhang_anchor(geometry, v.overhang_id, "root")
        joint, local = _joint(rod, v, geometry)
        reach = np.linalg.norm(joint - root) + np.linalg.norm(local)
        relative = frame.T @ (root - centers[i])
        radial_sq = reach**2 - relative[0] ** 2 - relative[2] ** 2
        if radial_sq <= 0:
            raise ValueError(
                "An attachment cannot reach its fixed particle center at a legal crossover phase. Increase duplex length."
            )
        upper = min(upper, relative[1] + np.sqrt(radial_sq))
    offset_params = _params(
        history, "rod-offset", {"offset_nm": float(upper - 0.03)}, ("offset_nm",)
    )
    offset = float(offset_params["offset_nm"])
    if not np.isfinite(offset):
        raise ValueError("Rod offset must be finite.")
    if offset < lower:
        raise ValueError(
            "The fixed centers cannot all be reached on the same side with these handle lengths and core radii. Increase duplex length or adjust the particle arrangement."
        )
    cluster = cluster.model_copy(
        update={
            "translation": (
                np.asarray(cluster.translation) - frame[:, 1] * offset
            ).tolist()
        }
    )
    before = rod
    rod = rod.copy_with(cluster_transforms=[cluster])
    _record(
        history,
        before,
        rod,
        "cluster-pose",
        f"Offset {shape} beside the nanoparticles",
        offset_params,
        "rod-offset",
        ("offset_nm",),
    )
    geometry = fitting_geometry(rod)
    for i, v in enumerate(rod.nanoparticle_connection_versions):
        root, _ = resolve_overhang_anchor(geometry, v.overhang_id, "root")
        joint, local = _joint(rod, v, geometry)
        before = rod
        angles = _params(history, f"fit:{i}", {}, ("phase_deg", "duplex_roll_deg"))
        target, rotation, fit_params = _fit_swing(
            root,
            joint,
            centers[i],
            np.linalg.norm(local),
            frame,
            geometry,
            v,
            particles,
            centers,
            angles,
        )
        rod, _, _ = _build_overhang_patch(
            rod,
            v.overhang_id,
            OverhangPatchRequest(
                rotation=Rotation.from_matrix(rotation).as_quat().tolist()
            ),
        )
        pose = particles[i].pose.to_array().copy()
        pose[:3, :3] = (
            _rotation_between(pose[:3, :3] @ local, target - centers[i]) @ pose[:3, :3]
        )
        rod = replace_gold_nanosphere(
            rod, particles[i].id, pose=pose.flatten().tolist()
        )
        rod, _ = materialize_duplex_cluster(rod, v.overhang_id)
        _record(
            history,
            before,
            rod,
            "nanoparticle-connection-relax",
            f"Fit nanoparticle {i + 1} duplex at fixed center",
            fit_params,
            f"fit:{i}",
            ("phase_deg", "duplex_roll_deg"),
        )
        geometry = fitting_geometry(rod)
    # Verify actual emitted coordinates, never just the nominal helix axes.
    residuals = []
    for i, v in enumerate(rod.nanoparticle_connection_versions):
        joint, local = _joint(rod, v, geometry)
        particle = next(p for p in rod.nanoparticles if p.id == v.nanoparticle_id)
        predicted = (particle.pose.to_array() @ np.r_[local, 1])[:3]
        residual = float(np.linalg.norm(joint - predicted))
        if residual > 0.02 or not np.allclose(
            particle.pose.to_array()[:3, 3], centers[i], atol=1e-9
        ):
            raise ValueError(
                "Generated attachment failed its fixed-center geometry check."
            )
        root, _ = resolve_overhang_anchor(geometry, v.overhang_id, "root")
        if np.dot(centers[i] - root, frame[:, 1]) <= 0:
            raise ValueError(
                "Generated attachment is not on the requested common side."
            )
        residuals.append(residual)
    positions = np.array(
        [n[key] for n in geometry for key in ("backbone_position", "base_position")]
    )
    for p, center in zip(particles, centers):
        if np.min(np.linalg.norm(positions - center, axis=1)) < p.diameter_nm / 2:
            raise ValueError(
                "A generated DNA strand intersects a gold core. Try a longer duplex or a different particle arrangement."
            )
    before = rod
    rod = rod.copy_with(
        nanoparticle_connection_versions=[
            v.model_copy(
                update={
                    "relaxed": True,
                    "residual_nm": residuals[i],
                    "constraint_root_nm": tuple(
                        resolve_overhang_anchor(geometry, v.overhang_id, "root")[0]
                    ),
                }
            )
            for i, v in enumerate(rod.nanoparticle_connection_versions)
        ]
    )
    # Pose patches invalidate cached staple sequences; rederive the final
    # sequenced topology, including all complementary attachment domains.
    rod = assign_staple_sequences(rod)
    _record(
        history,
        before,
        rod,
        "assign-staple-sequences",
        "Finalize sequences and measured attachment constraints",
        {},
        "final-sequences",
    )
    return rod, {
        "connections": connections,
        "attachment_residuals_nm": residuals,
        "rod_offset_nm": offset,
        "platform_offset_nm": offset if platform else None,
    }
