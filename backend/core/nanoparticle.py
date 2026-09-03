"""Pure helpers for display-layer nanoparticles."""

from __future__ import annotations

import math
import random
import uuid

import numpy as np

from backend.core.models import (
    Design, Direction, Domain, Helix, Mat4x4, Nanoparticle,
    NanoparticleConjugation, NanoparticleSurfaceStrand, Strand, StrandType, Vec3,
)
from backend.core.protein import gizmo_move_to_pose


def create_gold_nanosphere(
    diameter_nm: float, *, nanoparticle_id: str | None = None
) -> Nanoparticle:
    values = {"diameter_nm": diameter_nm}
    if nanoparticle_id is not None:
        values["id"] = nanoparticle_id
    return Nanoparticle(**values)


def replace_gold_nanosphere(
    design: Design,
    nanoparticle_id: str,
    *,
    diameter_nm: float | None = None,
    pose: list[float] | None = None,
    gizmo_move: dict | None = None,
) -> Design:
    particles = []
    found = False
    old_particle = None
    new_particle = None
    for particle in design.nanoparticles:
        if particle.id != nanoparticle_id:
            particles.append(particle)
            continue
        found = True
        old_particle = particle
        updates = {}
        if diameter_nm is not None:
            updates["diameter_nm"] = diameter_nm
        if pose is not None:
            updates["pose"] = Mat4x4(values=pose)
        if gizmo_move is not None:
            updates["pose"] = Mat4x4.from_array(
                gizmo_move_to_pose(
                    particle.pose.to_array(),
                    gizmo_move["pivot"],
                    gizmo_move["translation"],
                    gizmo_move["rotation"],
                )
            )
        new_particle = particle.model_copy(update=updates)
        particles.append(new_particle)
    if not found:
        raise KeyError(nanoparticle_id)
    out = design.copy_with(nanoparticles=particles)
    if old_particle is not None and new_particle is not None:
        out = _reposition_owned_helices(out, old_particle, new_particle)
    return out


def constrained_nanoparticle_move(design: Design, nanoparticle_id: str, version, geometry,
                                  *, pivot, translation, rotation, preconstrained=False):
    """Protein-parity two-ball-joint move for one applied NP duplex."""
    from scipy.spatial.transform import Rotation
    from backend.core.protein import gizmo_move_to_pose, resolve_overhang_anchor, _rotation_between
    from backend.core.duplex_cluster import (
        dematerialize_duplex_cluster, materialize_duplex_cluster, duplex_cluster_for,
    )

    particle = next(p for p in design.nanoparticles if p.id == nanoparticle_id)
    conjugation = next(c for c in design.nanoparticle_conjugations
                       if c.nanoparticle_id == nanoparticle_id)
    record = next(r for r in conjugation.surface_strands if r.strand_id == version.strand_id)
    root, _ = resolve_overhang_anchor(geometry, version.overhang_id, "root")
    if root is None:
        raise ValueError("Nanoparticle constraint cannot resolve the overhang crossover joint.")
    old_pose = particle.pose.to_array()
    cluster = duplex_cluster_for(design, version.overhang_id)
    flag = "is_five_prime" if conjugation.attach_end == "5p" else "is_three_prime"
    if record.backbone_attachment_local_nm is not None:
        local_joint = np.array([*record.backbone_attachment_local_nm, 1.0], dtype=float)
    else:
        # Legacy NADOC files predate the persisted exact helical joint.  Match
        # the browser's radial fallback exactly so Apply cannot jump relative
        # to its preview; the field is populated on the next Apply/rebind.
        local_joint = np.array([
            *(np.asarray(record.site_local, dtype=float)
              * (particle.diameter_nm / 2.0 + conjugation.spacer_nm)), 1.0
        ])
    body_joint = (old_pose @ local_joint)[:3]
    handle_nuc = next((n for n in geometry if n.get("strand_id") == record.strand_id
                       and n.get(flag)), None)
    if handle_nuc is None:
        raise ValueError("Nanoparticle constraint cannot resolve the handle attachment joint.")
    old_joint = np.asarray(handle_nuc["backbone_position"], dtype=float)
    proposed = gizmo_move_to_pose(old_pose, pivot, translation, rotation)
    proposed_joint = (proposed @ local_joint)[:3]
    link = old_joint - root
    radius = float(np.linalg.norm(link))
    requested = proposed_joint - root
    requested_radius = float(np.linalg.norm(requested))
    trans = np.asarray(translation, dtype=float)
    q = np.asarray(rotation, dtype=float)
    max_move = max(float(np.max(np.abs(trans))), 1e-12)
    locked = ((np.abs(trans) <= max_move * 0.01)
              if float(np.linalg.norm(q[:3])) < 1e-8 else np.zeros(3, dtype=bool))
    delta = requested.copy()
    fixed_sq = float(np.dot(delta[locked], delta[locked]))
    free_sq = float(np.dot(delta[~locked], delta[~locked]))
    if preconstrained:
        desired_joint = proposed_joint.copy()
    elif np.any(locked) and free_sq > 1e-24:
        desired_joint = proposed_joint.copy()
        desired_joint[~locked] = root[~locked] + delta[~locked] * math.sqrt(
            max(0.0, radius * radius - fixed_sq) / free_sq)
    else:
        direction = requested / requested_radius if requested_radius > 1e-12 else link / max(radius, 1e-12)
        desired_joint = root + direction * radius
    proposed[:3, 3] += desired_joint - proposed_joint
    swing = _rotation_between(link, desired_joint - root)

    moved = design
    if cluster is not None:
        cluster_id, cluster_name = cluster.id, cluster.name
        moved = dematerialize_duplex_cluster(moved, version.overhang_id)
        spec = next(o for o in moved.overhangs if o.id == version.overhang_id)
        old_r = Rotation.from_quat(spec.rotation).as_matrix()
        new_r = swing @ old_r
        moved = moved.model_copy(update={"overhangs": [
            o.model_copy(update={"rotation": Rotation.from_matrix(new_r).as_quat().tolist(),
                                 # Overhang transforms rotate about their live
                                 # crossover pivot.  Retaining the existing
                                 # translation makes this a pure rigid swing;
                                 # rebasing it as an origin-centred affine
                                 # transform displaces the duplex twice.
                                 "translation": list(spec.translation)})
            if o.id == version.overhang_id else o for o in moved.overhangs
        ]})
        moved, _ = materialize_duplex_cluster(
            moved, version.overhang_id, name=cluster_name, cluster_id=cluster_id,
        )
    moved = replace_gold_nanosphere(moved, nanoparticle_id,
                                    pose=proposed.reshape(-1).tolist())
    return moved, {
        "mode": "two_ball_joint", "root": root.tolist(), "joint": old_joint.tolist(),
        "radius_nm": radius, "requested_radius_nm": requested_radius,
        "clamped": abs(requested_radius - radius) > 1e-6,
        "plane_locked_axes": [axis for axis, value in zip("xyz", locked) if value],
        "body_joint_before_nm": body_joint.tolist(),
        "joint_error_nm": float(np.linalg.norm((proposed @ local_joint)[:3] - desired_joint)),
    }


THIOL_SCHEMES = {
    # Central planning densities, deliberately versioned and reported as
    # estimates rather than universal physical maxima.
    "direct_thiol": {"density": 0.10, "range": (0.05, 0.15), "spacer_nm": 0.7, "literature": "hurst-2006", "source_url": "https://doi.org/10.1021/ac0613582"},
    "alkyl_thiol": {"density": 0.09, "range": (0.04, 0.14), "spacer_nm": 1.4, "literature": "hurst-2006", "source_url": "https://doi.org/10.1021/ac0613582"},
    "peg_thiol": {"density": 0.07, "range": (0.04, 0.10), "spacer_nm": 3.5, "literature": "jacsau-2025-0.07", "source_url": "https://doi.org/10.1021/jacsau.5c00475"},
    "peg_backfill": {"density": 0.035, "range": (0.005, 0.05), "spacer_nm": 1.4, "literature": "zhao-hsing-2010", "source_url": "https://doi.org/10.1039/B920696E"},
}


def estimate_thiol_coverage(diameter_nm: float, scheme: str) -> dict:
    if scheme not in THIOL_SCHEMES:
        raise ValueError(f"Unknown thiol conjugation scheme: {scheme}")
    item = THIOL_SCHEMES[scheme]
    area = math.pi * float(diameter_nm) ** 2
    capacity = max(1, int(round(area * item["density"])))
    return {
        "scheme": scheme,
        "diameter_nm": float(diameter_nm),
        "surface_area_nm2": area,
        "density_per_nm2": item["density"],
        "estimated_capacity": capacity,
        "estimated_capacity_range": [
            max(1, int(round(area * item["range"][0]))),
            max(1, int(round(area * item["range"][1]))),
        ],
        "estimated_spacing_nm": math.sqrt(area / capacity),
        "default_spacer_nm": item["spacer_nm"],
        "literature_key": item["literature"],
        "source_url": item["source_url"],
        "model_version": "thiol-au-v1",
    }


def fibonacci_sites(count: int, seed: int = 1) -> list[tuple[float, float, float]]:
    """Deterministic, approximately uniform unit-sphere sites."""
    rng = random.Random(seed)
    phase = rng.random() * math.tau
    golden = math.pi * (3.0 - math.sqrt(5.0))
    result = []
    for i in range(count):
        y = 1.0 - 2.0 * (i + 0.5) / count
        radius = math.sqrt(max(0.0, 1.0 - y * y))
        angle = phase + golden * i
        result.append((radius * math.cos(angle), y, radius * math.sin(angle)))
    return result


def _point(matrix: np.ndarray, xyz) -> np.ndarray:
    return (matrix @ np.array([*xyz, 1.0], dtype=float))[:3]


def build_thiol_conjugation(
    particle: Nanoparticle, *, scheme: str, sequence: str, count: int,
    attach_end: str = "5p", spacer_nm: float | None = None, seed: int = 1,
) -> tuple[NanoparticleConjugation, list[Helix], list[Strand]]:
    sequence = sequence.strip().upper()
    if not sequence or any(base not in "ACGTN" for base in sequence):
        raise ValueError("sequence must contain one or more A/C/G/T/N bases")
    estimate = estimate_thiol_coverage(particle.diameter_nm, scheme)
    # Literature coverage is an estimate, not a hard construction limit.  The
    # slider stops at that estimate, while an explicit count may intentionally
    # exceed it for custom/high-density preparations.
    if count < 1:
        raise ValueError("count must be at least 1")
    spacer = estimate["default_spacer_nm"] if spacer_nm is None else float(spacer_nm)
    if not 0 <= spacer <= 100:
        raise ValueError("spacer_nm must be between 0 and 100")
    matrix = particle.pose.to_array()
    radius = particle.diameter_nm / 2.0
    helices, strands, records = [], [], []
    for index, site in enumerate(fibonacci_sites(count, seed)):
        sulfur_local = tuple(radius * v for v in site)
        start_local = tuple((radius + spacer) * v for v in site)
        end_local = tuple((radius + spacer + max(0.34, 0.34 * (len(sequence) - 1))) * v for v in site)
        start, end = _point(matrix, start_local), _point(matrix, end_local)
        helix_id = f"__np__{particle.id}__{index}__{uuid.uuid4().hex[:8]}"
        strand_id = str(uuid.uuid4())
        overhang_id = f"__np_oh__{strand_id}"
        helix = Helix(
            id=helix_id, axis_start=Vec3(x=float(start[0]), y=float(start[1]), z=float(start[2])),
            axis_end=Vec3(x=float(end[0]), y=float(end[1]), z=float(end[2])),
            length_bp=len(sequence), label=f"AuNP DNA {index + 1}",
        )
        direction = Direction.FORWARD if attach_end == "5p" else Direction.REVERSE
        domain = Domain(
            helix_id=helix_id,
            start_bp=0 if direction == Direction.FORWARD else len(sequence) - 1,
            end_bp=len(sequence) - 1 if direction == Direction.FORWARD else 0,
            direction=direction,
            overhang_id=overhang_id,
        )
        strand = Strand(id=strand_id, domains=[domain], strand_type=StrandType.STAPLE,
                        sequence=sequence, name=f"AuNP-{index + 1}")
        records.append(NanoparticleSurfaceStrand(
            strand_id=strand_id, helix_id=helix_id, overhang_id=overhang_id, site_local=site,
            sulfur_local_nm=sulfur_local,
        ))
        helices.append(helix); strands.append(strand)
    conjugation = NanoparticleConjugation(
        nanoparticle_id=particle.id, scheme=scheme, sequence=sequence,
        attach_end=attach_end, spacer_nm=spacer, requested_count=count,
        estimated_capacity=estimate["estimated_capacity"],
        density_per_nm2=count / estimate["surface_area_nm2"],
        distribution_seed=seed, model_version=estimate["model_version"],
        literature_key=estimate["literature_key"], surface_strands=records,
    )
    return conjugation, helices, strands


def _reposition_owned_helices(design: Design, old: Nanoparticle, new: Nanoparticle) -> Design:
    owned = {
        record.helix_id: (conj, record)
        for conj in design.nanoparticle_conjugations if conj.nanoparticle_id == old.id
        # A bound handle is part of the materialized rigid duplex child.  Its
        # helix has already been swung about the target crossover joint by the
        # constrained mover and must not subsequently be snapped back onto the
        # particle's radial construction axis.  Only free handles are rigidly
        # owned by the nanoparticle body.
        for record in conj.surface_strands
        if record.helix_id.startswith("__np__") and record.bound_overhang_id is None
    }
    if not owned:
        return design
    matrix = new.pose.to_array()
    radius = new.diameter_nm / 2.0
    helices = []
    for helix in design.helices:
        pair = owned.get(helix.id)
        if pair is None:
            helices.append(helix); continue
        conj, record = pair
        site = np.array(record.site_local)
        start = _point(matrix, site * (radius + conj.spacer_nm))
        length = float(np.linalg.norm(helix.axis_end.to_array() - helix.axis_start.to_array()))
        end = _point(matrix, site * (radius + conj.spacer_nm + length))
        helices.append(helix.model_copy(update={
            "axis_start": Vec3(x=float(start[0]), y=float(start[1]), z=float(start[2])),
            "axis_end": Vec3(x=float(end[0]), y=float(end[1]), z=float(end[2])),
        }))
    conjugations = []
    for conj in design.nanoparticle_conjugations:
        if conj.nanoparticle_id != old.id:
            conjugations.append(conj); continue
        estimate = estimate_thiol_coverage(new.diameter_nm, conj.scheme)
        conjugations.append(conj.model_copy(update={
            "estimated_capacity": estimate["estimated_capacity"],
            "density_per_nm2": conj.requested_count / estimate["surface_area_nm2"],
        }))
    return design.copy_with(helices=helices, nanoparticle_conjugations=conjugations)
