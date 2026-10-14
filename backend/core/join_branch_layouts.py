"""Particle-directed rigid branch layouts, independent of lattice construction."""

import numpy as np


def join_branch_layouts(centers: np.ndarray) -> list[dict]:
    """Propose stems with two or four independently directed terminal branches.

    The caller checks planarity and physical clearances. Coordinates stay in the
    particles' world frame; each arm follows the ray from its junction to its
    particle. Stem endpoints and junctions are centerline targets, before bundle
    thickness, nanoparticle radii, or connector clearance are applied.

    Four particles produce all three pairings, ranked by pair spans plus the
    distance between their centroids. Each pairing tries the Connectivity
    preview's opposed-split setback first, then the pair midpoints. For three
    particles, each particle is tried as the stem terminal with the other two
    branching from one junction. Coincident endpoints are omitted.
    """
    points = np.asarray(centers, dtype=float)
    if points.shape not in ((3, 3), (4, 3)) or not np.isfinite(points).all():
        raise ValueError("Join branches require three or four finite 3D centers.")
    if any(
        np.linalg.norm(points[i] - points[j]) < 1e-8
        for i in range(len(points))
        for j in range(i)
    ):
        raise ValueError("Join branch particle centers must be distinct.")

    layouts = []

    def append(start, end, branches, stem_particles, setback):
        if np.linalg.norm(end - start) < 1e-8 or any(
            np.linalg.norm(points[index] - junction) < 1e-8
            for index, junction in branches
        ):
            return
        layouts.append(
            dict(
                stem_start=start.tolist(),
                stem_end=end.tolist(),
                arms=[
                    dict(particle_index=index, junction=junction.tolist())
                    for index, junction in branches
                ],
                stem_particles=stem_particles,
                setback=setback,
            )
        )

    if len(points) == 4:
        pairings = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]

        def pairing_cost(pairing):
            left, right = pairing
            return (
                np.linalg.norm(points[left[0]] - points[left[1]])
                + np.linalg.norm(points[right[0]] - points[right[1]])
                + np.linalg.norm(
                    points[list(left)].mean(0) - points[list(right)].mean(0)
                )
            )

        for left, right in sorted(pairings, key=pairing_cost):
            a, b = points[list(left)].mean(0), points[list(right)].mean(0)
            for setback in (0.25, 0.0):
                # Match discoverConnectivity's opposed-splits construction:
                # shift the first split, then grow the second from that split.
                start = a + (b - a) * (setback / 2)
                end = b - (b - start) * setback
                append(
                    start,
                    end,
                    [(i, start) for i in left] + [(i, end) for i in right],
                    [],
                    setback,
                )
    else:

        def singleton_cost(index):
            other = [i for i in range(3) if i != index]
            midpoint = points[other].mean(0)
            return np.linalg.norm(points[index] - midpoint) + np.linalg.norm(
                points[other[0]] - points[other[1]]
            )

        for index in sorted(range(3), key=singleton_cost):
            other = [i for i in range(3) if i != index]
            start = points[index]
            midpoint = points[other].mean(0)
            for setback in (0.25, 0.0):
                end = midpoint - (midpoint - start) * setback
                append(start, end, [(i, end) for i in other], [index], setback)
    return layouts
