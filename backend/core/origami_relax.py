"""Experimental rigid-cluster backbone stretch minimization; no simulation engine.

Only cluster poses change. Intrinsic helix geometry and strand routing are fixed.
Planar axis layouts retain their plane; other layouts use free rigid-body poses.
This is a local geometric fit with conservative planar body clearance, not a simulation.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import OptimizeResult, least_squares, minimize
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation
from threadpoolctl import threadpool_limits

from backend.core.design_geometry import _geometry_for_design


# Small bond-fit matrices are much slower with a large workstation BLAS pool.
@threadpool_limits.wrap(limits=1, user_api="blas")
def relax_origami(design, *, max_steps=30000, prevent_clashes=True):
    if any(c.domain_ids or c.parent_cluster_id for c in design.cluster_transforms):
        raise ValueError(
            "Relax Origami requires whole-helix poses; domain or nested clusters cannot be moved as rigid bodies."
        )
    if design.overhang_connections or design.extensions:
        raise ValueError(
            "Relax Origami currently requires routed helices without attached linkers or strand extensions."
        )
    geometry = _geometry_for_design(design)
    reference_geometry = (
        _geometry_for_design(design.copy_with(cluster_transforms=[]))
        if design.cluster_transforms
        else geometry
    )

    def bead_key(bead):
        return (
            bead.get("strand_id"),
            bead.get("domain_index"),
            bead["helix_id"],
            bead["bp_index"],
            bead["direction"],
            int(bead.get("copy_k", bead.get("copy", 0)) or 0),
        )

    reference = {bead_key(bead): bead for bead in reference_geometry}
    ids = [h.id for h in design.helices]
    if not 2 <= len(ids) <= 500:
        raise ValueError("Relax Origami supports 2–500 helices per attempt.")
    index = {hid: i for i, hid in enumerate(ids)}
    domains = {}
    axes = [[] for _ in ids]
    for bead in geometry:
        hid = bead["helix_id"]
        if hid not in index:
            continue
        di = bead.get("domain_index")
        if not isinstance(di, int):
            continue
        domains.setdefault((bead.get("strand_id"), di), []).append(bead)
        site = bead.get("helical_site", {}).get("axis_point")
        if site is not None:
            axes[index[hid]].append(site)
    if any(not a for a in axes):
        raise ValueError("Every helix must have occupied, placed nucleotides.")
    centers = np.array([np.mean(a, axis=0) for a in axes])
    all_axes = np.concatenate(axes)
    _, _, vt = np.linalg.svd(all_axes - all_axes.mean(axis=0), full_matrices=False)
    normal = vt[-1]
    planar = np.max(np.abs((all_axes - all_axes.mean(axis=0)) @ normal)) < 1e-5
    if prevent_clashes and not planar:
        raise ValueError(
            "Clash-aware Relax Origami currently requires a planar helix-axis layout."
        )
    plane = vt[:2]
    extra = {}
    for xo in design.crossovers:
        a, b = xo.half_a, xo.half_b
        key = frozenset(
            (
                (a.helix_id, a.index, a.strand.value),
                (b.helix_id, b.index, b.strand.value),
            )
        )
        extra[key] = len(xo.extra_bases or "")
    for link in design.forced_ligations:
        key = frozenset(
            (
                (
                    link.three_prime_helix_id,
                    link.three_prime_bp,
                    link.three_prime_direction.value,
                ),
                (
                    link.five_prime_helix_id,
                    link.five_prime_bp,
                    link.five_prime_direction.value,
                ),
            )
        )
        extra[key] = len(link.extra_bases or "")
    endpoints, reference_endpoints, owners, targets = [], [], [], []
    for strand in design.strands:
        for di, (a, b) in enumerate(zip(strand.domains, strand.domains[1:])):
            if a.helix_id == b.helix_id:
                continue  # Invariant under rigid-helix motion.
            selected = []
            for j, domain, last in ((di, a, True), (di + 1, b, False)):
                beads = domains.get((strand.id, j), [])
                if not beads:
                    raise ValueError("A strand junction has no placed endpoint.")
                sign = 1 if domain.direction.value == "FORWARD" else -1
                beads = sorted(
                    beads,
                    key=lambda n: (
                        sign * n["bp_index"],
                        sign * n.get("copy_k", n.get("copy", 0)),
                    ),
                )
                selected.append(beads[-1 if last else 0])
            key = frozenset(
                (
                    (a.helix_id, a.end_bp, a.direction.value),
                    (b.helix_id, b.start_bp, b.direction.value),
                )
            )
            endpoints.append([n["backbone_position"] for n in selected])
            reference_endpoints.append(
                [reference[bead_key(n)]["backbone_position"] for n in selected]
            )
            owners.append([index[a.helix_id], index[b.helix_id]])
            targets.append(0.67 * (1 + extra.get(key, 0)))
    if not endpoints:
        raise ValueError("No inter-helix backbone bonds were found.")
    endpoints, owners, targets = (
        np.array(endpoints),
        np.array(owners),
        np.array(targets),
    )
    # Reuse the application's geometry clustering, rather than introducing a
    # second definition of a rigid body based on the current bond lengths.
    from backend.core.cluster_autodetect import _cluster_by_lattice_neighbors

    def identity(cluster):
        return np.allclose(cluster.translation, 0) and np.allclose(
            Rotation.from_quat(cluster.rotation).as_matrix(), np.eye(3)
        )

    existing = list(design.cluster_transforms)
    geometry_clusters = [c for c in existing if c.name.startswith("Geometry Cluster ")]
    bodies = geometry_clusters or [c for c in existing if not c.is_default]
    omitted = [c for c in existing if c not in bodies]
    if any(not identity(c) for c in omitted):
        raise ValueError(
            "Relax Origami requires a non-overlapping partition of whole-helix clusters."
        )
    if not bodies:
        bodies = _cluster_by_lattice_neighbors(
            design.copy_with(cluster_transforms=[])
        ).cluster_transforms
    membership = [h for c in bodies for h in c.helix_ids]
    if len(membership) != len(ids) or set(membership) != set(ids):
        raise ValueError(
            "Relax Origami requires non-overlapping clusters covering every helix. Use geometry cluster detection first."
        )
    groups = [[index[h] for h in c.helix_ids] for c in bodies]
    n = len(groups)
    if prevent_clashes and n > 32:
        raise ValueError(
            "Clash-aware Relax Origami supports at most 32 rigid bodies per attempt."
        )
    if n < 2:
        raise ValueError(
            "Only one rigid cluster was found; there are no bonds between bodies to relax."
        )
    body_for_helix = {h: k for k, group in enumerate(groups) for h in group}
    owners = np.array([[body_for_helix[h] for h in pair] for pair in owners])
    between = owners[:, 0] != owners[:, 1]
    internal_bond_count = int(np.count_nonzero(~between))
    if not np.any(between):
        raise ValueError("No backbone bonds connect the rigid clusters.")
    endpoints, owners, targets = endpoints[between], owners[between], targets[between]
    reference_endpoints = np.asarray(reference_endpoints)[between]
    lengths = np.linalg.norm(
        reference_endpoints[:, 0] - reference_endpoints[:, 1], axis=1
    )
    centers = np.array(
        [np.mean(np.concatenate([axes[h] for h in group]), axis=0) for group in groups]
    )
    has_slack = targets > 0.67 + 1e-8
    targets = np.where(lengths < 3.0, np.maximum(lengths, targets), targets)
    preserve = ~has_slack & (targets > 0.67 + 1e-8)
    local = endpoints - centers[owners]
    dof = 3 if planar else 6

    def poses(x):
        q = np.zeros((n, dof))
        q[1:] = x.reshape(n - 1, dof)
        if planar:
            rotations = Rotation.from_rotvec(q[:, :1] * normal)
            translations = q[:, -2:] @ plane
        else:
            rotations = Rotation.from_rotvec(q[:, :3])
            translations = q[:, 3:]
        return rotations, translations

    def distances(x):
        rotations, translations = poses(x)
        moved = np.einsum("beij,bej->bei", rotations.as_matrix()[owners], local)
        moved += centers[owners] + translations[owners]
        return np.linalg.norm(moved[:, 0] - moved[:, 1], axis=1)

    def residual(x):
        delta = distances(x) - targets
        return np.where(preserve, delta, np.maximum(delta, 0))

    sparsity = lil_matrix((len(owners), (n - 1) * dof), dtype=int)
    for row, pair in enumerate(owners):
        for owner in pair:
            if owner:
                sparsity[row, (owner - 1) * dof : owner * dof] = 1
    initial = np.zeros((n - 1) * dof)
    clearance = None
    if prevent_clashes:
        from backend.core.origami_clashes import PlanarBodyClearance

        clearance = PlanarBodyClearance(axes, groups, centers, plane)
    if planar:

        def objective(x):
            rotations, translations = poses(x)
            arms = np.einsum("beij,bej->bei", rotations.as_matrix()[owners], local)
            points = arms + centers[owners] + translations[owners]
            delta = points[:, 0] - points[:, 1]
            length = np.linalg.norm(delta, axis=1)
            stretch = np.where(
                preserve, length - targets, np.maximum(length - targets, 0)
            )
            force = 2 * stretch[:, None] * delta / np.maximum(length[:, None], 1e-12)
            grad = np.zeros((n, dof))
            for side, sign in ((0, 1), (1, -1)):
                f = sign * force
                angle = np.sum(f * np.cross(normal, arms[:, side]), axis=1)
                values = np.column_stack((angle, f @ plane.T))
                np.add.at(grad, owners[:, side], values)
            return float(stretch @ stretch), grad[1:].ravel()

        starts = [initial]
        # For a flat strip with long-range closure bonds, try both winding senses.
        # These are generic initial guesses; the objective contains only bonds.
        axis = np.linalg.svd(
            np.asarray(axes[0]) - np.mean(axes[0], axis=0), full_matrices=False
        )[2][0]
        transverse = np.cross(normal, axis)
        across = centers @ transverse
        along = centers @ axis
        span = np.ptp(across)
        if span > 1 and np.max(residual(initial)) > 5:
            pitch = np.median(np.diff(np.unique(np.round(across, 5))))
            for winding in (-1, 1):
                theta = winding * 2 * np.pi * (across - across[0]) / (span + pitch)
                radius = (span + pitch) / (2 * np.pi)
                radial = (
                    np.cos(theta)[:, None] * axis - np.sin(theta)[:, None] * transverse
                )
                guessed = (radius + along - along.mean())[:, None] * radial
                guessed += centers[0] - guessed[0]
                q = np.column_stack((-theta, (guessed - centers) @ plane.T))
                starts.append(q[1:].ravel())
        candidates = [
            minimize(
                objective,
                start,
                jac=True,
                method="L-BFGS-B",
                options={
                    "maxiter": max_steps,
                    "maxfun": max_steps * 3,
                    "ftol": 1e-12,
                    "gtol": 1e-7,
                    "maxcor": 30,
                },
            )
            for start in starts
        ]
        result = min(candidates, key=lambda fit: fit.fun)
        if clearance is not None:

            def separation(x):
                return clearance.gaps(*poses(x)) - clearance.required_gap_nm

            feasible = []
            if np.min(separation(initial)) >= -1e-6:
                feasible.append(
                    OptimizeResult(
                        x=initial,
                        fun=objective(initial)[0],
                        nfev=0,
                        success=False,
                        message="Kept the original feasible pose; no better fit found.",
                    )
                )
            # The original pose and both winding senses offer different contact
            # arrangements. Enforce clearance rather than trading overlap for
            # a lower bond error with an arbitrary penalty weight.
            for start in [initial, *(fit.x for fit in candidates)]:
                fit = minimize(
                    objective,
                    start,
                    jac=True,
                    method="SLSQP",
                    constraints=[{"type": "ineq", "fun": separation}],
                    options={"maxiter": min(max_steps, 1000), "ftol": 1e-9},
                )
                if np.all(np.isfinite(fit.x)) and np.min(separation(fit.x)) >= -1e-6:
                    feasible.append(fit)
            if not feasible:
                raise ValueError(
                    "No clash-free rigid-body fit was found; the design was not changed."
                )
            result = min(feasible, key=lambda fit: (fit.fun, not fit.success))
    else:
        result = least_squares(
            residual,
            initial,
            jac_sparsity=sparsity.tocsr(),
            max_nfev=min(max_steps, 400),
            ftol=1e-8,
            xtol=1e-8,
            gtol=1e-6,
        )
    before, after = residual(initial), residual(result.x)
    if not np.all(np.isfinite(result.x)) or (
        clearance is None and np.dot(after, after) > np.dot(before, before) + 1e-8
    ):
        raise ValueError("The minimizer did not produce a finite, improved pose.")
    rotations, translations = poses(result.x)
    # The identity default is only a bootstrap container, superseded by bodies.
    clusters = [c for c in omitted if not c.is_default]
    for i, body in enumerate(bodies):
        # Compose the fitted world-space motion with the existing body pose.
        # Keep its pivot and ID so repeated relaxation does not stack clusters.
        old_rotation = Rotation.from_quat(body.rotation)
        pivot = np.asarray(body.pivot)
        translation = (
            rotations[i].apply(pivot + np.asarray(body.translation) - centers[i])
            + centers[i]
            + translations[i]
            - pivot
        )
        clusters.append(
            body.model_copy(
                update={
                    "translation": translation.tolist(),
                    "rotation": (rotations[i] * old_rotation).as_quat().tolist(),
                }
            )
        )
    report = {
        "method": "backbone bond fit between rigid clusters"
        + (" with planar body clearance" if clearance else ""),
        "planar": bool(planar),
        "helix_count": len(ids),
        "rigid_bundle_sizes": [len(g) for g in groups],
        "bond_count": len(targets),
        "internal_bond_count": internal_bond_count,
        "evaluations": result.nfev,
        "optimizer_converged": bool(result.success),
        "message": result.message,
        "before": stretch_summary(before),
        "after": stretch_summary(after),
        "limitations": "Local geometric fit, no simulation or base-pair energy. Clearance uses conservative helix-axis convex envelopes expanded by helix radius; it is not an atomistic clash test and does not repair internal body clashes. All geometry within each cluster is fixed.",
    }
    if clearance is not None:
        report["clashes"] = {
            "before": clearance.summary(*poses(initial)),
            "after": clearance.summary(*poses(result.x)),
        }
    candidate = design.copy_with(cluster_transforms=clusters)
    return candidate, report


def stretch_summary(stretch):
    return {
        "max_excess_nm": float(np.max(np.maximum(stretch, 0))),
        "rms_bond_error_nm": float(np.sqrt(np.mean(stretch**2))),
        "stretched_bonds": int(np.count_nonzero(stretch > 0.05)),
    }
