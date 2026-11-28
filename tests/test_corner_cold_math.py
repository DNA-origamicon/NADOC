"""Cold-fit acceleration against independent NumPy and frozen atom oracles."""

from dataclasses import replace
import gzip
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from backend.core.corner_local_environment import LocalEnvironment


def _environment_oracle(xyz, movable, points, gradient):
    rows = cKDTree(points).query_ball_point(xyz[movable], 0.20)
    counts = np.array([len(row) for row in rows])
    if not counts.sum():
        return 0.0
    own = np.repeat(movable, counts)
    other = np.concatenate(rows).astype(int)
    delta = xyz[own] - points[other]
    distance = np.linalg.norm(delta, axis=1)
    penetration = distance - 0.20
    np.add.at(
        gradient, own, (2 * penetration / np.maximum(distance, 1e-12))[:, None] * delta
    )
    return float(penetration @ penetration)


def test_local_environment_preserves_full_tree_cost_and_gradient():
    rng = np.random.default_rng(876)
    points = rng.normal(size=(5000, 3))
    # Exact contact boundary, coincident points and signed zeros.
    points[:6] = [
        [0.2, 0, 0],
        [np.nextafter(0.2, 0), 0, 0],
        [np.nextafter(0.2, 1), 0, 0],
        [0, -0.2, 0],
        [0, 0, 0.2],
        [-0.0, 0, 0],
    ]
    local = LocalEnvironment(points)
    xyz = rng.normal(size=(60, 3)) * 0.1
    xyz[0] = 0
    movable = np.arange(0, 60, 2)
    # Reuse lists, cross their skin, and leave/re-enter the entire local box.
    for step in [0, 0.001, 0.124, 0.126, 1, 50, 0, -0.3]:
        current = xyz + step
        expected = rng.normal(size=current.shape)
        actual = expected.copy()
        cost = _environment_oracle(current, movable, points, expected)
        assert local.accumulate(current, movable, actual) == cost
        np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(local.data, points)


def test_empty_environment_keeps_gradient():
    local = LocalEnvironment(np.empty((0, 3)))
    gradient = np.ones((1, 3))
    assert local.accumulate(np.zeros((1, 3)), np.array([0]), gradient) == 0
    np.testing.assert_array_equal(gradient, np.ones((1, 3)))


def test_seed_batch_retains_optimizer_steps_and_final_coordinates(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from backend.core import atomistic_minimisers as seeds
    from backend.core.corner_seam_bridge_math import bridge_cost
    from backend.core.corner_closure_math import seed_costs

    results = []
    minimize = seeds._scipy_minimize

    def observed(*args, **kwargs):
        result = minimize(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(seeds, "_scipy_minimize", observed)
    rng = np.random.default_rng(453)
    source = {"C3'": 0, "O3'": 1}
    destination = {"P": 2, "O5'": 3, "C5'": 4, "OP1": 5, "OP2": 6}
    for _ in range(8):
        points = rng.normal(size=(7, 3)) * 0.4
        a = [SimpleNamespace(x=x, y=y, z=z) for x, y, z in points]
        b = deepcopy(a)
        seeds._minimize_backbone_bridge(a, source, destination, cost_fn=bridge_cost)
        seeds._minimize_backbone_bridge(
            b,
            source,
            destination,
            cost_fn=bridge_cost,
            cost_batch_fn=lambda c3, xs, c5: seed_costs(c3, xs, c5, 2.0),
        )
        old, new = results[-2:]
        for field in ("nit", "nfev", "njev", "fun", "message"):
            assert new[field] == old[field]
        np.testing.assert_array_equal(new.x, old.x)
        np.testing.assert_array_equal(
            [[p.x, p.y, p.z] for p in b], [[p.x, p.y, p.z] for p in a]
        )


def test_closure_coordinates_cost_and_gradient_match_independent_numpy_oracle():
    from backend.core.atomistic import Atom, AtomisticModel
    from backend.core.corner_seam_closure import ComponentClosure
    from experiments.corner_seam_closure import ComponentClosure as Oracle

    # Read the existing approved fixture; no new construction or saved snapshot.
    path = (
        Path(__file__).parents[1]
        / "frontend/src/ui/geometry_review_data/corner-closure.json.gz"
    )
    with gzip.open(path, "rt") as stream:
        fixture = json.load(stream)["controls"]["hc2"]["candidate"]
    atoms = [Atom(**row) for row in fixture["atoms"]]
    seam = next(a.crossover_id for a in atoms if a.crossover_id)
    seam_ids = {a.serial for a in atoms if a.crossover_id == seam}
    neighbour_ids = {
        i for edge in fixture["bonds"] if seam_ids.intersection(edge) for i in edge
    }
    residues = {
        (atoms[i].helix_id, atoms[i].bp_index, atoms[i].direction)
        for i in neighbour_ids
        if atoms[i].crossover_id is None
    }
    ids = [
        a.serial
        for a in atoms
        if a.crossover_id == seam
        or (
            a.crossover_id is None and (a.helix_id, a.bp_index, a.direction) in residues
        )
    ]
    mapping = {serial: i for i, serial in enumerate(ids)}
    model = AtomisticModel(
        atoms=[replace(atoms[i], serial=mapping[i]) for i in ids],
        bonds=[
            (mapping[i], mapping[j])
            for i, j in fixture["bonds"]
            if i in mapping and j in mapping
        ],
    )
    environment = np.array([[a.x, a.y, a.z] for a in atoms if a.serial not in mapping])
    old, new = (
        Oracle(model, environment=environment),
        ComponentClosure(model, environment=environment),
    )
    np.testing.assert_array_equal(new.pairs, old.pairs)
    rng = np.random.default_rng(978)
    for scale in [0.0, 1e-9, 1e-4, 0.01, 0.15, 2.0, 0.0]:
        for _ in range(10):
            x = old.x0 + rng.normal(size=old.x0.shape) * scale
            np.testing.assert_array_equal(new.coordinates(x)[0], old.coordinates(x)[0])
            expected, actual = old.objective(x), new.objective(x)
            assert actual[0] == expected[0]
            np.testing.assert_array_equal(actual[1], expected[1])


def test_compiled_stamp_preserves_each_original_matrix_vector_product():
    from backend.core.corner_atom_stamp import stamp, local_coordinates
    from backend.core.atomistic import _native_local_defs
    rng = np.random.default_rng(88)
    for residue in ('DA', 'DC', 'DG', 'DT'):
        for direction in ('FORWARD', 'REVERSE'):
            local = local_coordinates(residue, direction)
            np.testing.assert_array_equal(local, [row[2:] for row in _native_local_defs(residue, direction)])
            for _ in range(20):
                origin, rotation = rng.normal(size=3), rng.normal(size=(3, 3))
                expected = np.array([origin + rotation @ row for row in local])
                np.testing.assert_array_equal(stamp(origin, rotation, local), expected)


def test_compiled_pair_eligibility_preserves_dense_reference_order():
    from backend.core.corner_closure_math import eligible_pairs
    rng = np.random.default_rng(984)
    for n in (1, 2, 15, 100):
        adjacent = rng.random((n, n)) < .03
        adjacent |= adjacent.T
        np.fill_diagonal(adjacent, False)
        moving = rng.random(n) < .3
        expected = (moving[:, None] | moving[None, :]) & ~adjacent & ~(adjacent @ adjacent)
        expected = np.column_stack(np.nonzero(np.triu(expected, 1)))
        np.testing.assert_array_equal(eligible_pairs(adjacent, moving), expected)


def test_cost_only_residuals_match_gradient_provider_including_degenerate_arms():
    from backend.core.corner_seam_bridge_math import _bridge_cost_terms, _bridge_terms
    rng = np.random.default_rng(45)
    inputs = [np.zeros((5, 3)), np.full((5, 3), 1e-14)]
    inputs.extend(rng.normal(size=(5, 3)) for _ in range(100))
    for points in inputs:
        np.testing.assert_array_equal(_bridge_cost_terms(*points), _bridge_terms(*points)[0])
