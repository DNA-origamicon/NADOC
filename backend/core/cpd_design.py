"""Deliberate CPD test geometry. Does not widen force-field qualification."""

from __future__ import annotations

import hashlib
import json
import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.base_keys import atom_base_key, resolve_base_keys
from backend.core.cpd_product import _proper_kabsch, _template_coordinates
from backend.core.models import NucleotideTransform, PhotoproductJunction
from backend.core.photoproduct_registry import (
    REGISTRY_PATH,
    photoproduct_registry,
    photoproduct_capability,
)


def design_template(stereochemistry="cis-syn"):
    capability = photoproduct_capability("TT-CPD", stereochemistry)
    if not capability.get("simulation_supported"):
        raise ValueError(
            "This CPD type is in development; no qualified template is available."
        )
    entry = next(
        p for p in photoproduct_registry()["products"] if p["id"] == capability["id"]
    )
    asset = entry["assets"]["coordinate_template"]
    data = (REGISTRY_PATH.parent / asset["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise ValueError("CPD coordinate template failed its integrity check.")
    return _template_coordinates(
        json.loads(data),
        allowed_release_statuses=frozenset({"released", "preliminary"}),
    )


def template_preview(stereochemistry="cis-syn"):
    coordinates = design_template(stereochemistry)
    keys = list(coordinates)
    # Distance-derived display bonds, plus explicit cyclobutane crosslinks.
    bonds = []
    for i, a in enumerate(keys):
        for j in range(i + 1, len(keys)):
            b = keys[j]
            if a.split(":")[0] != b.split(":")[0]:
                if (a, b) not in [("1:C5", "2:C5"), ("1:C6", "2:C6")]:
                    continue
            cutoff = (
                0.125
                if a.split(":")[1].startswith("H") or b.split(":")[1].startswith("H")
                else 0.19
            )
            if 0.04 < np.linalg.norm(coordinates[a] - coordinates[b]) < cutoff:
                bonds.append([i, j])
    return {
        "atom_keys": keys,
        "positions": [coordinates[k].tolist() for k in keys],
        "bonds": bonds,
        "qualification": "Preliminary cis-syn template. Extra-base test structures are not qualified for NAMD export.",
    }


def _pose_with_jacobian(coordinates, center, torsions, x):
    """Single-bond rotations and rigid pose with an analytic Cartesian Jacobian."""
    flexible = coordinates.copy()
    for angle, (first, second, members) in zip(x[6:], torsions):
        origin = flexible[first].copy()
        axis = flexible[second] - origin
        axis /= np.linalg.norm(axis)
        flexible[members] = (flexible[members] - origin) @ Rotation.from_rotvec(
            angle * axis
        ).as_matrix().T + origin
    rotation = Rotation.from_rotvec(x[:3]).as_matrix()
    points = (flexible - center) @ rotation.T + center + x[3:6]
    jac = np.zeros((len(points), 3, len(x)))
    rx, ry, rz = x[:3]
    skew = np.array([[0.0, -rz, ry], [rz, 0.0, -rx], [-ry, rx, 0.0]])
    theta = np.linalg.norm(x[:3])
    right_jac = (
        np.eye(3)
        - ((1 - np.cos(theta)) / theta**2 if theta > 1e-6 else 0.5) * skew
        + ((theta - np.sin(theta)) / theta**3 if theta > 1e-6 else 1 / 6)
        * (skew @ skew)
    )
    for k in range(3):
        jac[:, :, k] = np.cross(right_jac[:, k], flexible - center) @ rotation.T
    jac[:, :, 3:6] = np.eye(3)
    for k, (first, second, members) in enumerate(torsions, 6):
        axis = flexible[second] - flexible[first]
        axis /= np.linalg.norm(axis)
        jac[members, :, k] = (
            np.cross(axis, flexible[members] - flexible[first]) @ rotation.T
        )
    return points, jac


def minimize_attachment_bonds(model, endpoints, placed):
    """Relax the product pose and six single-bond torsions against fixed neighbors.

    This is a local bond-length and steric relaxation, not force-field dynamics.
    The CPD base-ring core, bond lengths, valence angles and chirality are preserved.
    """
    from scipy.optimize import least_squares, minimize

    endpoint_numbers = {e.key: i for i, e in enumerate(endpoints, 1)}
    by_serial = {a.serial: a for a in model.atoms}
    attachments = []
    for first, second in model.bonds:
        a, b = by_serial[first], by_serial[second]
        if {a.name, b.name} != {"O3'", "P"}:
            continue
        ia, ib = (
            endpoint_numbers.get(atom_base_key(a)),
            endpoint_numbers.get(atom_base_key(b)),
        )
        if (ia is None) == (ib is None):
            continue
        if ia is None:
            a, b, ia = b, a, ib
        attachments.append((f"{ia}:{a.name}", np.array([b.x, b.y, b.z])))
    # Both conversion and re-relaxation use identical atom identities and an
    # absolute template frame fitted to fixed flanking atoms, never the previous
    # CPD pose. Template-only H and phosphate aliases cannot shift the pivot.
    keys = sorted(
        f"{i}:{name}"
        for i, e in enumerate(endpoints, 1)
        for name in e.atom_positions_nm
    )
    input_coordinates = np.array([placed[k] for k in keys])
    template = design_template()
    aliases = {"OP1": "O1P", "OP2": "O2P"}
    coordinates = np.array(
        [
            template[
                f"{k.split(':', 1)[0]}:{aliases.get(k.split(':', 1)[1], k.split(':', 1)[1])}"
            ]
            for k in keys
        ]
    )
    if attachments:
        source = np.array([coordinates[keys.index(k)] for k, _ in attachments])
        target = np.array([xyz for _, xyz in attachments])
        fit_r, fit_t, _ = _proper_kabsch(source, target)
        coordinates = coordinates @ fit_r.T + fit_t
    else:
        fit_r, fit_t, _ = _proper_kabsch(coordinates, input_coordinates)
        coordinates = coordinates @ fit_r.T + fit_t
    center = coordinates.mean(axis=0)
    indices = [keys.index(k) for k, _ in attachments]
    fixed = np.array([xyz for _, xyz in attachments]).reshape(-1, 3)
    target_nm = 0.16  # authored phosphodiester O3'–P bond target

    torsions = []
    for first, second, names in [
        ("N1", "C1'", None),
        ("C4'", "C5'", {"C5'", "H5'", "H5''", "O5'", "P", "OP1", "OP2"}),
        ("C5'", "O5'", {"O5'", "P", "OP1", "OP2"}),
    ]:
        for number in (1, 2):
            members = [
                i
                for i, k in enumerate(keys)
                if k.startswith(f"{number}:")
                and (
                    ("'" in k or k.split(":")[1] in {"P", "OP1", "OP2"})
                    if names is None
                    else k.split(":")[1] in names
                )
            ]
            torsions.append(
                (
                    keys.index(f"{number}:{first}"),
                    keys.index(f"{number}:{second}"),
                    members,
                )
            )

    def moved(x):
        return _pose_with_jacobian(coordinates, center, torsions, x)[0]

    def lengths(x):
        return np.linalg.norm(moved(x)[indices] - fixed, axis=1)

    # Only actual emitted atoms participate: do not double-count OP1/O1P
    # aliases or template hydrogens absent from this model.
    from backend.core.atomistic import VDW_RADIUS
    from scipy.spatial.distance import cdist

    moving = [a for a in model.atoms if atom_base_key(a) in endpoint_numbers]
    moving_indices = [
        keys.index(f"{endpoint_numbers[atom_base_key(a)]}:{a.name}") for a in moving
    ]
    radius = np.max(np.linalg.norm(coordinates - center, axis=1)) + np.sqrt(12.0) + 2.0
    nearby = [
        a
        for a in model.atoms
        if atom_base_key(a) not in endpoint_numbers
        and np.linalg.norm(np.array([a.x, a.y, a.z]) - center) <= radius
    ]
    environment = np.array([[a.x, a.y, a.z] for a in nearby]).reshape(-1, 3)
    radii = (
        np.array([VDW_RADIUS.get(a.element, 0.16) for a in moving])[:, None]
        + np.array([VDW_RADIUS.get(a.element, 0.16) for a in nearby])[None, :]
    )
    neighbors = {}
    for a, b in model.bonds:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    # Fresh designs do not yet contain the CPD bonds; use the same product
    # graph as saved lesions for intramolecular nonbonded exclusions.
    serials = {(atom_base_key(a), a.name): a.serial for a in moving}
    for name in ("C5", "C6"):
        a, b = [serials[(e.key, name)] for e in endpoints]
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    mask = np.ones((len(moving), len(nearby)), dtype=bool)
    for i, atom in enumerate(moving):
        bonded = neighbors.get(atom.serial, set())
        excluded = bonded | {k for j in bonded for k in neighbors.get(j, set())}
        mask[i] = [other.serial not in excluded for other in nearby]

    internal_pairs = []
    for i, atom in enumerate(moving):
        bonded = neighbors.get(atom.serial, set())
        excluded = bonded | {k for j in bonded for k in neighbors.get(j, set())}
        for j in range(i + 1, len(moving)):
            if moving[j].serial not in excluded:
                internal_pairs.append((i, j))
    internal_i = np.array([i for i, _ in internal_pairs], dtype=int)
    internal_j = np.array([j for _, j in internal_pairs], dtype=int)
    moving_radii = np.array([VDW_RADIUS.get(a.element, 0.16) for a in moving])
    internal_radii = moving_radii[internal_i] + moving_radii[internal_j]
    original_internal = np.linalg.norm(
        coordinates[moving_indices][internal_i]
        - coordinates[moving_indices][internal_j],
        axis=1,
    )
    # Preserve any close native template contacts; penalize newly introduced overlaps.
    internal_clearance = np.minimum(0.90 * internal_radii, original_internal)

    def internal_overlap(points):
        atoms = points[moving_indices]
        distance = np.linalg.norm(atoms[internal_i] - atoms[internal_j], axis=1)
        return np.maximum(0.0, internal_clearance - distance)

    def contacts_at(points):
        distances = cdist(points[moving_indices], environment)
        # Soft steric clearance, excluding bonded and 1–3 graph neighbors.
        overlap = np.where(mask, np.maximum(0.0, 0.90 * radii - distances), 0.0)
        return distances, overlap

    cached = None

    def evaluate(x):
        nonlocal cached
        if cached is not None and np.array_equal(x, cached[0]):
            return cached[1:]
        points, jac = _pose_with_jacobian(coordinates, center, torsions, x)
        distances, overlap = contacts_at(points)
        norm = np.sqrt(np.sum(overlap**2, axis=1))
        delta = points[moving_indices, None, :] - environment[None, :, :]
        gradient = (
            -np.sum(
                overlap[:, :, None] * delta / np.maximum(distances[:, :, None], 1e-12),
                axis=1,
            )
            / np.maximum(norm[:, None], 1e-12)
            / 0.01
        )
        steric_jac = np.einsum("ij,ijk->ik", gradient, jac[moving_indices])
        bond_delta = points[indices] - fixed
        bond_dist = np.linalg.norm(bond_delta, axis=1)
        bond_jac = (
            np.einsum(
                "ij,ijk->ik",
                bond_delta / np.maximum(bond_dist[:, None], 1e-12),
                jac[indices],
            )
            / 0.04
        )
        internal_delta = (
            points[moving_indices][internal_i] - points[moving_indices][internal_j]
        )
        internal_dist = np.linalg.norm(internal_delta, axis=1)
        internal_penalty = np.maximum(0.0, internal_clearance - internal_dist)
        internal_jac = (
            -np.einsum(
                "ij,ijk->ik",
                internal_delta / np.maximum(internal_dist[:, None], 1e-12),
                jac[moving_indices][internal_i] - jac[moving_indices][internal_j],
            )
            / 0.01
        )
        internal_jac[internal_penalty <= 0.0] = 0.0
        residual = np.concatenate(
            (
                (bond_dist - target_nm) / 0.04,
                norm / 0.01,
                internal_penalty / 0.01,
                0.05 * x,
            )
        )
        derivative = np.vstack(
            (bond_jac, steric_jac, internal_jac, 0.05 * np.eye(len(x)))
        )
        cached = (x.copy(), residual, derivative)
        return residual, derivative

    def residual(x):
        return evaluate(x)[0]

    bounds = (
        [-np.pi] * 3 + [-2.0] * 3 + [-np.pi] * 6,
        [np.pi] * 3 + [2.0] * 3 + [np.pi] * 6,
    )
    # Cover all 24 proper cube orientations instead of only translations of
    # one initial pose. The ordering is fixed and independent of previous edits.
    starts = [np.r_[r, np.zeros(9)] for r in Rotation.create_group("O").as_rotvec()]
    results = [
        least_squares(
            residual, start, jac=lambda x: evaluate(x)[1], bounds=bounds, max_nfev=180
        )
        for start in starts
    ]
    score = lambda x: float(np.sum(residual(x) ** 2))
    result = min(
        results, key=lambda r: score(r.x) if np.all(np.isfinite(r.x)) else float("inf")
    )

    def value_gradient(x):
        residual_value, derivative = evaluate(x)
        return float(residual_value @ residual_value), 2 * derivative.T @ residual_value

    # Quasi-Newton polishing uses the full objective curvature after the broad
    # bounded search, reducing the remaining small contact/attachment compromise.
    polished = [
        minimize(
            value_gradient,
            r.x,
            jac=True,
            method="L-BFGS-B",
            bounds=list(zip(*bounds)),
            options={"maxiter": 500, "maxfun": 1000, "ftol": 1e-12, "gtol": 1e-6},
        )
        for r in sorted(results, key=lambda r: score(r.x))[:2]
    ]
    result = min([result, *polished], key=lambda r: score(r.x))
    # Finish with explicit nonbonded clearance constraints. A soft penalty alone
    # can trade a small overlap for a shorter attachment bond at its minimum.
    best_points = moved(result.x)
    best_distances, _ = contacts_at(best_points)
    ci, cj = np.where(mask & (best_distances < 0.90 * radii + 0.10))
    internal_floor = np.minimum(0.85 * internal_radii, original_internal) - 0.005

    def clearance(x):
        points, derivative = _pose_with_jacobian(coordinates, center, torsions, x)
        atoms = points[moving_indices]
        delta = atoms[ci] - environment[cj]
        lengths = np.linalg.norm(delta, axis=1)
        jacobian = np.einsum(
            "ij,ijk->ik",
            delta / np.maximum(lengths[:, None], 1e-12),
            derivative[moving_indices][ci],
        )
        idelta = atoms[internal_i] - atoms[internal_j]
        ilengths = np.linalg.norm(idelta, axis=1)
        ijac = np.einsum(
            "ij,ijk->ik",
            idelta / np.maximum(ilengths[:, None], 1e-12),
            derivative[moving_indices][internal_i]
            - derivative[moving_indices][internal_j],
        )
        return np.r_[
            lengths - 0.85 * radii[ci, cj] - 0.001, ilengths - internal_floor
        ], np.vstack((jacobian, ijac))

    constrained = minimize(
        value_gradient,
        result.x,
        jac=True,
        method="SLSQP",
        bounds=list(zip(*bounds)),
        constraints={
            "type": "ineq",
            "fun": lambda x: clearance(x)[0],
            "jac": lambda x: clearance(x)[1],
        },
        options={"maxiter": 200, "ftol": 1e-9},
    )
    candidate_distances, _ = contacts_at(moved(constrained.x))
    if (
        np.all(np.isfinite(constrained.x))
        and clearance(constrained.x)[0].min(initial=0.0) >= -1e-7
        and np.all(candidate_distances[mask] >= 0.85 * radii[mask])
        and score(constrained.x) <= 2.0 * score(result.x)
    ):
        result = constrained
    polish_report = {
        "accepted": result is constrained,
        "success": bool(constrained.success),
        "message": str(constrained.message),
        "objective": score(constrained.x),
        "minimum_constraint": float(clearance(constrained.x)[0].min(initial=0.0)),
    }
    solution = result.x
    before = np.linalg.norm(input_coordinates[indices] - fixed, axis=1)
    after = lengths(solution)

    def clash_report(points):
        distances, _ = contacts_at(points)
        overlap = np.where(mask, np.maximum(0.0, 0.85 * radii - distances), 0.0)
        return {
            "count": int(np.sum(overlap > 1e-6)),
            "severe_count": int(np.sum(mask & (distances < 0.5 * radii))),
            "overlap_squared_nm2": float(np.sum(overlap**2)),
            "max_overlap_nm": float(np.max(overlap, initial=0.0)),
            "minimum_vdw_ratio": float(np.min((distances / radii)[mask]))
            if mask.any()
            else None,
        }

    report = {
        "method": "ring-preserving CPD torsion and steric minimization",
        "status": "converged" if result.success else "bounded-best-fit",
        "bond_count": len(attachments),
        "target_nm": target_nm,
        "before_nm": before.tolist(),
        "after_nm": after.tolist(),
        "rms_error_before_nm": float(np.sqrt(np.mean((before - target_nm) ** 2)))
        if len(before)
        else 0.0,
        "rms_error_after_nm": float(np.sqrt(np.mean((after - target_nm) ** 2)))
        if len(after)
        else 0.0,
        "remaining_strain": bool(np.any(np.abs(after - target_nm) > 0.05)),
        "evaluations": sum(r.nfev for r in [*results, *polished, constrained]),
        "starts": len(starts),
        "nearby_atom_count": len(nearby),
        "clearance_vdw_ratio": 0.90,
        "version": "canonical-torsion-search-v2",
        "clearance_polish": polish_report,
        "glycosidic_rotation_degrees": np.rad2deg(solution[6:8]).tolist(),
        "backbone_rotation_degrees": np.rad2deg(solution[8:]).tolist(),
        "internal_overlap_squared_nm2": float(
            np.sum(internal_overlap(moved(solution)) ** 2)
        ),
        "clashes_before": clash_report(input_coordinates),
        "clashes_after": clash_report(moved(solution)),
        "objective_before": float(
            np.sum(((before - target_nm) / 0.04) ** 2)
            + np.sum(contacts_at(input_coordinates)[1] ** 2) / 0.01**2
        ),
        "objective_after": score(solution),
    }
    return dict(zip(keys, moved(solution))), report


def _store_product_pose(design, endpoints, placed, source_positions=None):
    """Project the same unposed residue geometry for fresh and saved CPDs."""
    poses = list(design.nucleotide_transforms)
    stored = {}
    for i, endpoint in enumerate(endpoints, 1):
        names = [name for name in endpoint.atom_positions_nm if f"{i}:{name}" in placed]
        if set(endpoint.atom_positions_nm) - set(names):
            raise ValueError(
                "The CPD template does not cover every atom of the selected residue."
            )
        # Use the unposed residue as the source of the new absolute CG/atom pose.
        existing = next(
            (
                p
                for p in poses
                if p.target_key()
                == ("extra_base", endpoint.parsed.crossover_id, endpoint.parsed.k)
            ),
            None,
        )
        source = (
            source_positions.get(endpoint.key)
            if source_positions is not None
            else endpoint.atom_positions_nm
        )
        original = np.array([source[name] for name in names])
        if existing and source_positions is None:
            er = Rotation.from_quat(existing.rotation).as_matrix()
            pivot = np.array(existing.pivot)
            original = (original - pivot - existing.translation) @ er + pivot
        desired = np.array([placed[f"{i}:{name}"] for name in names])
        r, t, _ = _proper_kabsch(original, desired)
        pose = NucleotideTransform(
            id=existing.id if existing else str(uuid.uuid4()),
            kind="extra_base",
            crossover_id=endpoint.parsed.crossover_id,
            extra_base_k=endpoint.parsed.k,
            translation=t.tolist(),
            rotation=Rotation.from_matrix(r).as_quat().tolist(),
        )
        poses = [p for p in poses if p.target_key() != pose.target_key()]
        poses.append(pose)
        # Exact product deformation precedes the saved rigid pose, so subsequent
        # unit transforms preserve all template bonds and stereocenters.
        stored[endpoint.key] = {
            name: ((placed[f"{i}:{name}"] - t) @ r).tolist() for name in names
        }
    return poses, stored


def convert_extra_pair(design, base_keys, stereochemistry="cis-syn"):
    """Place the complete template by a proper rigid fit; commit both poses together."""
    if len(base_keys) != 2 or len(set(base_keys)) != 2:
        raise ValueError("Select exactly two distinct extra thymine bases.")
    coordinates = design_template(stereochemistry)
    consumed = {
        k for p in design.photoproduct_junctions for k in (p.base_key_1, p.base_key_2)
    }
    if consumed.intersection(base_keys):
        raise ValueError("A selected base already belongs to a CPD.")
    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design)
    endpoints, errors = resolve_base_keys(
        design, sorted(base_keys), atomistic_model=model, require_atoms=True
    )
    if (
        errors
        or len(endpoints) != 2
        or any(e.base != "T" or e.parsed.family != "xover" for e in endpoints)
    ):
        raise ValueError(
            "Select exactly two crossover extra bases that resolve to thymine."
        )
    anchors = ["C1'", "N1", "C5", "C6"]
    source = np.array([coordinates[f"{i}:{name}"] for i in (1, 2) for name in anchors])
    target = np.array(
        [e.atom_positions_nm[name] for e in endpoints for name in anchors]
    )
    rotation, translation, _ = _proper_kabsch(source, target)
    placed = {k: rotation @ v + translation for k, v in coordinates.items()}
    for i in (1, 2):
        for display, template in (("OP1", "O1P"), ("OP2", "O2P")):
            placed[f"{i}:{display}"] = placed[f"{i}:{template}"]
    placed, relaxation = minimize_attachment_bonds(model, endpoints, placed)
    poses, stored = _store_product_pose(design, endpoints, placed)
    lesion = PhotoproductJunction(
        base_key_1=endpoints[0].key,
        base_key_2=endpoints[1].key,
        stereochemistry=stereochemistry,
        orientation_method="design-test-template-v1",
        design_coordinates=stored,
        bond_relaxation=relaxation,
    )
    return design.copy_with(
        photoproduct_junctions=[*design.photoproduct_junctions, lesion],
        nucleotide_transforms=poses,
    ), lesion


def apply_design_coordinates(atoms, design):
    coordinates = {
        key: positions
        for lesion in design.photoproduct_junctions
        for key, positions in lesion.design_coordinates.items()
    }
    if not coordinates:
        return
    for atom in atoms:
        position = coordinates.get(atom_base_key(atom), {}).get(atom.name)
        if position is not None:
            atom.x, atom.y, atom.z = position


def add_design_bonds(model, design):
    if not any(p.design_coordinates for p in design.photoproduct_junctions):
        return
    by_key = {(atom_base_key(a), a.name): a.serial for a in model.atoms}
    existing = {tuple(sorted(b)) for b in model.bonds}
    for lesion in design.photoproduct_junctions:
        if not lesion.design_coordinates:
            continue
        for name in ("C5", "C6"):
            pair = [
                by_key.get((k, name)) for k in (lesion.base_key_1, lesion.base_key_2)
            ]
            if None not in pair and tuple(sorted(pair)) not in existing:
                model.bonds.append(tuple(pair))


def relax_existing_cpd(design, lesion_id):
    """Re-relax a saved CPD using the same solver and projection as conversion."""
    from backend.core.atomistic import build_atomistic_model

    lesion = next((p for p in design.photoproduct_junctions if p.id == lesion_id), None)
    if lesion is None or not lesion.design_coordinates:
        raise ValueError("Select a converted CPD to relax.")
    model = build_atomistic_model(design)
    endpoints, errors = resolve_base_keys(
        design,
        [lesion.base_key_1, lesion.base_key_2],
        atomistic_model=model,
        require_atoms=True,
    )
    if errors or len(endpoints) != 2:
        raise ValueError("CPD endpoints no longer resolve.")
    placed = {
        f"{i}:{name}": np.array(xyz)
        for i, e in enumerate(endpoints, 1)
        for name, xyz in e.atom_positions_nm.items()
    }
    relaxed, report = minimize_attachment_bonds(model, endpoints, placed)
    # Rebuild only the source projection, with this CPD and its endpoint poses
    # removed. Fitting against the already-deformed saved product accumulated a
    # different coarse pose than new conversion, even for identical final atoms.
    target_keys = {("extra_base", e.parsed.crossover_id, e.parsed.k) for e in endpoints}
    unposed = design.copy_with(
        photoproduct_junctions=[
            p for p in design.photoproduct_junctions if p.id != lesion.id
        ],
        nucleotide_transforms=[
            p for p in design.nucleotide_transforms if p.target_key() not in target_keys
        ],
    )
    raw_model = build_atomistic_model(unposed)
    raw_endpoints, raw_errors = resolve_base_keys(
        unposed,
        [e.key for e in endpoints],
        atomistic_model=raw_model,
        require_atoms=True,
    )
    if raw_errors:
        raise ValueError("Could not rebuild the CPD source projection.")
    poses, stored = _store_product_pose(
        design, endpoints, relaxed, {e.key: e.atom_positions_nm for e in raw_endpoints}
    )
    updated = lesion.model_copy(
        update={"bond_relaxation": report, "design_coordinates": stored}
    )
    return design.copy_with(
        nucleotide_transforms=poses,
        photoproduct_junctions=[
            updated if p.id == lesion.id else p for p in design.photoproduct_junctions
        ],
    ), report
