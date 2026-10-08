"""Isolated connectivity-conditioned pilot; never changes native DNA geometry.

Shared ridge regressors predict nucleotide rotations and relative center changes
on covalent, paired and spatial edges. A graph solve integrates those changes;
rigid nucleotide reconstruction and soft bond/steric projection produce all atoms.
This is a screening hypothesis, not an atomistic force field or a seed validator.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.optimize import minimize
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

SCHEMA = "local-rigid-nucleotide-v1"


def psf_block(text, marker, width):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if marker in line)
    count = int(lines[start].split()[0])
    values = []
    for line in lines[start + 1 :]:
        if len(values) >= count * width:
            break
        values.extend(map(int, line.split()))
    result = np.asarray(values, dtype=int).reshape(-1, width) - 1
    if len(result) != count:
        raise ValueError(f"Incomplete PSF {marker}")
    return result


def _means(values, index, count):
    result = np.zeros((count,) + values.shape[1:])
    np.add.at(result, index, values)
    return result / np.bincount(index, minlength=count).reshape(
        (count,) + (1,) * (values.ndim - 1)
    ).clip(1)


def prepare(native, bonds):
    """Use PSF connectivity and existing native atom keys, without strand inference."""
    x = np.asarray(native["positions_nm"], dtype=float)
    ri = np.asarray(native["residue_index"], dtype=int)
    names = np.asarray(native["names"])
    keys = [tuple(k) for k in native["keys"]]
    n = len(keys)
    heavy = np.char.startswith(names.astype(str), "H") == 0
    groups = [np.flatnonzero((ri == i) & heavy) for i in range(n)]
    centers = np.array([x[g].mean(0) for g in groups])
    lookup = [{names[j]: j for j in g} for g in groups]
    frames = []
    for atoms in lookup:
        a = x[atoms["C3'"]] - x[atoms["C1'"]]
        a /= np.linalg.norm(a)
        b = x[atoms["C4'"]] - x[atoms["C1'"]]
        b -= np.dot(a, b) * a
        b /= np.linalg.norm(b)
        frames.append(np.stack([a, b, np.cross(a, b)], axis=1))
    frames = np.asarray(frames)
    bonds = np.asarray(bonds, dtype=int)
    cross = bonds[ri[bonds[:, 0]] != ri[bonds[:, 1]]]
    edges = {tuple(sorted((int(ri[a]), int(ri[b])))): 0 for a, b in cross}
    # Opposite members of an existing duplex key; copies and synthetic insertions
    # stay distinct. Extras still have covalent/spatial edges and all their atoms.
    paired = {}
    for i, key in enumerate(keys):
        if len(key) >= 3 and key[2] in ("FORWARD", "REVERSE"):
            paired.setdefault(key[:2] + key[3:], []).append(i)
    for members in paired.values():
        if len(members) == 2:
            edges.setdefault(tuple(sorted(members)), 1)
    # Radius graph avoids arbitrary nearest-neighbor tie breaking in periodic DNA.
    for i, j in cKDTree(centers).query_pairs(2.7, output_type="ndarray"):
        edges.setdefault((int(i), int(j)), 2)
    ij = np.array(sorted(edges), dtype=int).reshape(-1, 2)
    kind = np.array([edges[tuple(e)] for e in ij], dtype=int)
    # Both directed views share a regressor and are symmetrized at inference.
    src = np.r_[ij[:, 0], ij[:, 1]]
    dst = np.r_[ij[:, 1], ij[:, 0]]
    types = np.tile(kind, 2)
    rel = np.einsum("ni,nij->nj", centers[dst] - centers[src], frames[src])
    base = np.array(
        [
            [
                float("N6" in a),
                float("O6" in a),
                float("N4" in a),
                float("C7" in a or "C5M" in a),
            ]
            for a in lookup
        ]
    )
    features = [base]
    for edge_kind in range(3):
        mask = types == edge_kind
        count = np.bincount(src[mask], minlength=n)
        vec = rel[mask]
        moments = np.column_stack(
            [
                vec,
                vec * vec,
                vec[:, 0] * vec[:, 1],
                vec[:, 0] * vec[:, 2],
                vec[:, 1] * vec[:, 2],
            ]
        )
        features.extend([count[:, None], _means(moments, src[mask], n)])
    crossing = (types == 0) & np.array(
        [keys[i][0] != keys[j][0] for i, j in zip(src, dst)], dtype=bool
    )
    cross_count = np.bincount(src[crossing], minlength=n)[:, None]
    node = np.column_stack([*features, cross_count])
    # Invariant scalar descriptors propagated through the actual strand/duplex
    # graph; vector components belong to each node's own atom-defined frame.
    scalar = np.column_stack(
        [base, cross_count, *[features[1 + 2 * k] for k in range(3)]]
    )
    connected = types < 2
    for _ in range(2):
        scalar = _means(scalar[dst[connected]], src[connected], n)
        node = np.column_stack([node, scalar])
    relative_frames = np.einsum("nji,njk->nik", frames[src], frames[dst]).reshape(-1, 9)
    edge = np.column_stack(
        [
            node[src],
            node[dst],
            rel,
            relative_frames,
            np.eye(3)[types],
            crossing[:, None],
        ]
    )
    return dict(
        x=x,
        ri=ri,
        names=names,
        keys=keys,
        heavy=heavy,
        groups=groups,
        centers=centers,
        frames=frames,
        bonds=bonds,
        cross=cross,
        ij=ij,
        kind=kind,
        src=src,
        dst=dst,
        node_features=node,
        edge_features=edge,
    )


def labels(data, target):
    centers, rotations = [], []
    for i, group in enumerate(data["groups"]):
        a = data["x"][group] - data["centers"][i]
        center = target[group].mean(0)
        b = target[group] - center
        u, _, vt = np.linalg.svd(a.T @ b)
        rot = (u @ np.diag([1.0, 1.0, np.linalg.det(u @ vt)]) @ vt).T
        centers.append(center)
        rotations.append(data["frames"][i].T @ Rotation.from_matrix(rot).as_rotvec())
    delta = np.asarray(centers) - data["centers"]
    edges = np.einsum(
        "ni,nij->nj",
        delta[data["dst"]] - delta[data["src"]],
        data["frames"][data["src"]],
    )
    return np.array(rotations), edges


def _fit(xs, ys, alpha):
    # Equal design weight. No randomly split neighboring atoms/frames.
    mean = sum(x.mean(0) for x in xs) / len(xs)
    variance = sum(((x - mean) ** 2).mean(0) for x in xs) / len(xs)
    scale = np.sqrt(variance).clip(1e-5)
    n = len(mean) + 1
    aa, ab = np.zeros((n, n)), np.zeros((n, 3))
    for x, y in zip(xs, ys):
        a = np.column_stack([np.ones(len(x)), (x - mean) / scale])
        aa += a.T @ a / len(a)
        ab += a.T @ y / len(a)
    penalty = np.eye(n) * alpha
    penalty[0, 0] = 1e-8
    coef = np.linalg.solve(aa + penalty, ab)
    return dict(mean=mean.tolist(), scale=scale.tolist(), coefficients=coef.tolist())


def train(samples, alpha=0.1, use_global_prior=True):
    from backend.core.exp_regression import fit, predict_positions

    global_coefficients = (
        fit(
            [
                dict(input_nm=d["x"], target_nm=y, mapped_rows=np.arange(len(y)))
                for d, y in samples
            ]
        )
        if use_global_prior
        else np.zeros(6)
    )
    targets = []
    for data, y in samples:
        actual = labels(data, y)
        prior = labels(data, predict_positions(data["x"], global_coefficients))
        targets.append(tuple(a - b for a, b in zip(actual, prior)))
    return dict(
        schema=SCHEMA,
        global_coefficients=global_coefficients.tolist(),
        alpha=alpha,
        rotation=_fit(
            [d["node_features"] for d, _ in samples], [t[0] for t in targets], alpha
        ),
        edge=_fit(
            [d["edge_features"] for d, _ in samples], [t[1] for t in targets], alpha
        ),
        rotation_limit_rad=0.5,
        edge_limit_nm=0.2,
    )


def _apply(features, model):
    a = np.column_stack(
        [
            np.ones(len(features)),
            (features - np.array(model["mean"])) / np.array(model["scale"]),
        ]
    )
    return a @ np.array(model["coefficients"])


def _limit(v, maximum):
    norms = np.linalg.norm(v, axis=1)
    return v * np.minimum(1, maximum / norms.clip(1e-12))[:, None], int(
        (norms > maximum).sum()
    )


def predict(data, model, constrain=True, cancel=None):
    if model["schema"] != SCHEMA:
        raise ValueError("Unsupported local predictor schema")
    rotation, clipped_rot = _limit(
        _apply(data["node_features"], model["rotation"]), model["rotation_limit_rad"]
    )
    delta, clipped_edge = _limit(
        _apply(data["edge_features"], model["edge"]), model["edge_limit_nm"]
    )
    from backend.core.exp_regression import predict_positions

    prior_rot, prior_edge = labels(
        data, predict_positions(data["x"], model["global_coefficients"])
    )
    rotation += prior_rot
    delta += prior_edge
    delta = np.einsum("nij,nj->ni", data["frames"][data["src"]], delta)
    n, m = len(data["centers"]), len(data["ij"])
    delta = (delta[:m] - delta[m:]) / 2
    ij = data["ij"]
    incidence = sparse.coo_matrix(
        (np.tile([-1.0, 1.0], m), (np.repeat(np.arange(m), 2), ij.ravel())),
        shape=(m, n),
    ).tocsr()
    weights = np.choose(data["kind"], [1.0, 1.0, 0.15])
    laplacian = incidence.T @ sparse.diags(weights) @ incidence + sparse.eye(n) * 1e-6
    translation = spsolve(laplacian.tocsc(), incidence.T @ (weights[:, None] * delta))
    rotation = np.einsum("nij,nj->ni", data["frames"], rotation)
    matrices = Rotation.from_rotvec(rotation).as_matrix()
    ri = data["ri"]
    offset = np.einsum("nij,nj->ni", matrices[ri], data["x"] - data["centers"][ri])
    centers = data["centers"] + translation
    raw = offset + centers[ri]
    report = dict(clipped_rotations=clipped_rot, clipped_directed_edges=clipped_edge)
    if constrain:
        centers, projection = project(data, offset, centers, cancel=cancel)
        report["projection"] = projection
    return offset + centers[ri], raw, report


def project(data, offsets, centers, cancel=None, rounds=3, iterations=150):
    """Soft inter-residue phosphodiester length + gross heavy-atom clash constraints.

    All intra-residue distances/chirality remain exact under rigid reconstruction.
    0.160 nm is CHARMM36 ON2-P/P2 equilibrium (par_all36_na.prm). This is
    deliberately not a full force field: no angle/torsion, solvation or ion energy.
    """
    ri, bonds, cross = data["ri"], data["bonds"], data["cross"]
    for a, b in cross:
        if {str(data["names"][a]), str(data["names"][b])} != {"O3'", "P"}:
            raise ValueError(
                "Local projection needs parameters for a nonstandard inter-residue bond"
            )
    atom_count = len(ri)
    excluded = {int(min(a, b) * atom_count + max(a, b)) for a, b in bonds}
    neighbors = [[] for _ in ri]
    for a, b in bonds:
        neighbors[a].append(b)
        neighbors[b].append(a)
    for group in neighbors:
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                excluded.add(int(min(a, b) * atom_count + max(a, b)))
    original = centers.copy()
    heavy_indices = np.flatnonzero(data["heavy"])
    evaluations = 0
    result = None
    for _ in range(rounds):
        if cancel and cancel():
            raise RuntimeError("Local prediction cancelled")
        xyz = offsets + centers[ri]
        pairs = cKDTree(xyz[heavy_indices]).query_pairs(0.24, output_type="ndarray")
        pairs = heavy_indices[pairs]
        pairs = np.array(
            [
                p
                for p in pairs
                if ri[p[0]] != ri[p[1]]
                and int(min(p) * atom_count + max(p)) not in excluded
            ],
            dtype=int,
        ).reshape(-1, 2)

        def objective(flat):
            if cancel and cancel():
                raise RuntimeError("Local prediction cancelled")
            c = flat.reshape(-1, 3)
            xyz = offsets + c[ri]
            residual = c - original
            value = 0.5 * np.sum(residual**2)
            grad = residual.copy()
            for atom_pairs, length, weight, repulsive in [
                (cross, 0.160, 400.0, False),
                (pairs, 0.18, 100.0, True),
            ]:
                a, b = atom_pairs.T
                vector = xyz[a] - xyz[b]
                distance = np.linalg.norm(vector, axis=1).clip(1e-10)
                error = distance - length
                if repulsive:
                    error = np.minimum(error, 0)
                value += 0.5 * weight * np.dot(error, error)
                force = weight * (error / distance)[:, None] * vector
                np.add.at(grad, ri[a], force)
                np.add.at(grad, ri[b], -force)
            return value, grad.ravel()

        result = minimize(
            objective,
            centers.ravel(),
            jac=True,
            method="L-BFGS-B",
            options=dict(maxiter=iterations, ftol=1e-10, gtol=1e-5, maxcor=10),
        )
        evaluations += result.nfev
        centers = result.x.reshape(-1, 3)
    return centers, dict(
        converged=bool(result.success),
        message=str(result.message),
        evaluations=evaluations,
        rounds=rounds,
        max_center_correction_nm=float(
            np.linalg.norm(centers - original, axis=1).max()
        ),
    )


def geometry(data, predicted):
    """Independent bond and gross-clash diagnostics; not an energy validation."""
    ri, bonds = data["ri"], data["bonds"]
    a, b = bonds.T
    lengths = np.linalg.norm(predicted[a] - predicted[b], axis=1)
    native = np.linalg.norm(data["x"][a] - data["x"][b], axis=1)
    inter = ri[a] != ri[b]
    heavy = np.flatnonzero(data["heavy"])
    pairs = cKDTree(predicted[heavy]).query_pairs(0.12, output_type="ndarray")
    pairs = heavy[pairs]
    excluded = {tuple(sorted(p)) for p in bonds.tolist()}
    severe = [
        p.tolist()
        for p in pairs
        if ri[p[0]] != ri[p[1]] and tuple(sorted(p)) not in excluded
    ]
    return dict(
        intra_bond_max_change_nm=float(
            np.max(np.abs(lengths[~inter] - native[~inter]))
        ),
        inter_bond_percentiles_nm=np.percentile(
            lengths[inter], [0, 50, 95, 100]
        ).tolist(),
        inter_bonds_outside_014_018_nm=int(
            ((lengths[inter] < 0.14) | (lengths[inter] > 0.18)).sum()
        ),
        severe_inter_residue_heavy_pairs_under_012_nm=len(severe),
        severe_pair_examples=severe[:20],
    )
