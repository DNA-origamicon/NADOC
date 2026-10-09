"""Fast free-body compliance of an open DNA bundle, with attachment uncertainty.

Virtual-work quadrature for balanced particle loads avoids a dense FE solve.
All translations and rotations of the particle set are projected out. The
bundle is a linearly elastic composite beam; this is a model estimate, not MD.
Units: nm, pN, radians, kBT = 4.11 pN nm at approximately 298 K.
"""

from itertools import combinations
import numpy as np
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.lattice import honeycomb_position, square_position
from backend.core.models import LatticeType

KBT, EA, EI, GJ = 4.11, 1100.0, 230.0, 460.0


def skew(p):
    x, y, z = p
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def rigid_projection(points):
    centered = np.asarray(points) - np.mean(points, axis=0)
    rigid = np.vstack([np.column_stack((np.eye(3), -skew(p))) for p in centered])
    return np.eye(len(points) * 3) - rigid @ np.linalg.pinv(rigid)


def section_properties(cells, lattice, coupling):
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    xy = np.asarray([position(*c) for c in cells])
    xy -= xy.mean(0)
    # Longitudinal helix strain supplies the parallel-axis term. Coupling
    # discounts the fully bonded limit for finite interhelix shear transfer.
    bend = len(cells) * EI * np.eye(2) + coupling * EA * np.array(
        [
            [np.sum(xy[:, 1] ** 2), -np.sum(xy[:, 0] * xy[:, 1])],
            [-np.sum(xy[:, 0] * xy[:, 1]), np.sum(xy[:, 0] ** 2)],
        ]
    )
    return len(cells) * EA, bend, len(cells) * GJ + coupling * EA / 2.6 * np.sum(xy**2)


def prepare_beam(summary, centers, lattice, duplex_bp):
    from backend.core.sweep_path import oriented_sample

    path = summary["path"]
    start = summary["path_start_bp"]
    length = summary["nominal_length_bp"]
    # Include every attachment station; quadrature never crosses an applied load.
    stations = np.array(
        [start * RISE + path["station_s"][i] for i in range(len(centers))]
    )
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    cuts = np.arange(0, length, period)
    # Respect both inclusive endpoints of every allowed reinforcement interval.
    edges = np.unique(
        np.r_[
            np.linspace(0, (length - 1) * RISE, 49),
            cuts * RISE,
            (cuts - 1) * RISE,
            (length - 1) * RISE,
            stations,
        ]
    )
    edges = edges[(edges >= 0) & (edges <= (length - 1) * RISE)]
    nodes, weights = np.polynomial.legendre.leggauss(3)
    distances = (
        (edges[:-1] + edges[1:])[:, None] + np.diff(edges)[:, None] * nodes
    ) / 2
    ds = (np.diff(edges)[:, None] * weights / 2).ravel()
    distances = distances.ravel()
    req = summary["sweep_request"]
    from backend.core.sweep_path import frame_key

    frames = frame_key(
        [np.eye(3).ravel().tolist()] + [None] * (len(req["points_nm"]) - 1)
    )
    xyz, rotations, _ = oriented_sample(
        req["points_nm"], distances, None, np.eye(3), [0, 0, 1], frames
    )
    world = np.asarray(path["frame"])
    points = np.asarray(path["origin"]) + (xyz - [0, 0, start * RISE]) @ world.T
    bases = world @ rotations
    centers = np.asarray(centers, dtype=float)
    projection = rigid_projection(centers)
    loads = projection.reshape(len(centers), 3, -1)
    force, moment = [], []
    for s, p, basis in zip(distances, points, bases):
        downstream = np.flatnonzero(stations > s)
        f = sum((loads[i] for i in downstream), np.zeros((3, len(centers) * 3)))
        m = sum((skew(centers[i] - p) @ loads[i] for i in downstream), np.zeros_like(f))
        force.append(basis.T @ f)
        moment.append(basis.T @ m)
    return dict(
        bp=distances / RISE,
        ds=ds,
        force=np.asarray(force),
        moment=np.asarray(moment),
        centers=centers,
        projection=projection,
        lattice=lattice,
        duplex_bp=duplex_bp,
    )


def beam_score(beam, profile, *, coupling=0.15, attachment_scale=1.0):
    """Return mean/worst pair error plus aligned 3D fluctuation, including soft out-of-plane motion."""
    n = len(beam["centers"])
    structural = np.zeros((3 * n, 3 * n))
    groups = {}
    for j, bp in enumerate(beam["bp"]):
        cells = tuple(
            tuple(p["cell"]) for p in profile if p["start_bp"] <= bp <= p["end_bp"]
        )
        if not cells:
            raise ValueError("The mechanical beam has a disconnected section.")
        groups.setdefault(cells, []).append(j)
    for cells, indices in groups.items():
        ea, bend, gj = section_properties(cells, beam["lattice"], coupling)
        f, m, w = beam["force"][indices], beam["moment"][indices], beam["ds"][indices]
        structural += np.einsum("ni,nj,n->ij", f[:, 2], f[:, 2], w / ea)
        structural += np.einsum(
            "nai,ab,nbj,n->ij", m[:, :2], np.linalg.inv(bend), m[:, :2], w
        )
        structural += np.einsum("ni,nj,n->ij", m[:, 2], m[:, 2], w / gj)
        # Timoshenko-style shear term, deliberately retained for short sections.
        structural += np.einsum("nai,naj,n->ij", f[:, :2], f[:, :2], w / (0.38 * ea))
    structural *= KBT
    # Independent duplex cantilever uncertainty. This finite compliance must
    # not vanish when the origami section becomes arbitrarily thick.
    attachment_variance = (
        KBT
        * (np.broadcast_to(beam["duplex_bp"], (n,)) * RISE) ** 3
        / (3 * EI * attachment_scale)
    )
    attachment = (beam["projection"] * np.repeat(attachment_variance, 3)) @ beam[
        "projection"
    ].T
    covariance = structural + attachment
    pairs = []
    for i, j in combinations(range(n), 2):
        direction = beam["centers"][j] - beam["centers"][i]
        direction /= np.linalg.norm(direction)
        g = np.zeros(3 * n)
        g[3 * i : 3 * i + 3] = -direction
        g[3 * j : 3 * j + 3] = direction
        pairs.append(
            dict(
                particle_indices=[i, j], variance_nm2=float(max(0, g @ covariance @ g))
            )
        )
    mean = float(np.mean([p["variance_nm2"] for p in pairs]))
    worst = max(p["variance_nm2"] for p in pairs)
    aligned = float(max(0, np.trace(covariance) / n))
    return dict(
        score_nm2=mean + 0.5 * worst + 0.25 * aligned,
        pair_variances=pairs,
        aligned_rms_nm=float(np.sqrt(aligned)),
        worst_pair_std_nm=float(np.sqrt(worst)),
        structural_variance_nm2=float(np.trace(structural) / n),
        attachment_variance_nm2=float(np.trace(attachment) / n),
    )


def robust_score(beam, profile, robust=False):
    scenarios = [(0.15, 1.0)] if not robust else [(0.05, 0.5), (0.15, 1.0), (0.5, 2.0)]
    results = [
        beam_score(beam, profile, coupling=c, attachment_scale=a) for c, a in scenarios
    ]
    return {
        **results[0],
        "score_nm2": max(r["score_nm2"] for r in results),
        "parameter_provenance": "Duplex constants shared with the native FEM model; coupling and attachment multipliers are uncalibrated sensitivity assumptions.",
        "scenarios": [
            dict(coupling=c, attachment_scale=a, **r)
            for (c, a), r in zip(scenarios, results)
        ],
        "qualification": "Linear composite-beam estimate; attachment compliance and interhelix coupling are uncertain. No equilibrium-shape or molecular-dynamics validation at this level.",
    }
