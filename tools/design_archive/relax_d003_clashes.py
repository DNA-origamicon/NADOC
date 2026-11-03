"""Create a distinct D003 clash-aware artifact and independently audit its geometry."""

from itertools import combinations
from pathlib import Path
from uuid import uuid4
import json

import numpy as np
from scipy.spatial import cKDTree
from threadpoolctl import threadpool_limits

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.origami_relax import relax_origami
from tools.design_archive.relax_d003 import review_camera


def segment_distance(p, q):
    """Exact 3-D segment distance: interior stationary point or boundary minimum."""
    u, v, w = p[1] - p[0], q[1] - q[0], p[0] - q[0]
    a, b, c, d, e = u @ u, u @ v, v @ v, u @ w, v @ w
    candidates = []
    for point in p:
        projection = q[0] + np.clip((point - q[0]) @ v / max(c, 1e-30), 0, 1) * v
        candidates.append((point, projection))
    for point in q:
        projection = p[0] + np.clip((point - p[0]) @ u / max(a, 1e-30), 0, 1) * u
        candidates.append((projection, point))
    denom = a * c - b * b
    if denom > 1e-12 * max(a * c, 1):
        s, t = (b * e - c * d) / denom, (a * e - b * d) / denom
        if 0 <= s <= 1 and 0 <= t <= 1:
            candidates.append((p[0] + s * u, q[0] + t * v))
    x, y = min(candidates, key=lambda pair: np.linalg.norm(pair[0] - pair[1]))
    return float(np.linalg.norm(x - y)), (x + y) / 2


def audit(design):
    geometry = _geometry_for_design(design)
    owner = {h: i for i, c in enumerate(design.cluster_transforms) for h in c.helix_ids}
    segments = {}
    for h in design.helices:
        xyz = np.array(
            [b["helical_site"]["axis_point"] for b in geometry if b["helix_id"] == h.id]
        )
        axis = np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0]
        t = xyz @ axis
        segments[h.id] = xyz[[t.argmin(), t.argmax()]]
    distances, hits = [], []
    for a, b in combinations(segments, 2):
        if owner[a] == owner[b]:
            continue
        distance, point = segment_distance(segments[a], segments[b])
        distances.append(distance)
        if distance < 2.0 - 1e-6:
            hits.append(point.tolist())
    points = np.array([b["backbone_position"] for b in geometry])
    close = cKDTree(points).query_pairs(0.5)
    close = [
        (a, b)
        for a, b in close
        if owner[geometry[a]["helix_id"]] != owner[geometry[b]["helix_id"]]
    ]
    return (
        {
            "interbody_helix_pairs_below_2nm": len(hits),
            "minimum_interbody_axis_distance_nm": min(distances),
            "interbody_backbone_pairs_below_0_5nm": len(close),
        },
        hits,
        geometry,
        segments,
        owner,
    )


@threadpool_limits.wrap(limits=1, user_api="blas")
def run(folder):
    target = folder / "D003_rigid_clash_aware_v1.nadoc"
    if target.exists():
        raise FileExistsError(f"Preserve existing version: {target}")
    source = Design.model_validate_json(
        (folder / "D003_rigid_clusters_verified.nadoc").read_text()
    )
    assert sorted(len(c.helix_ids) for c in source.cluster_transforms) == [22] * 4
    result, fit = relax_origami(source)
    result = review_camera(
        result.model_copy(
            update={
                "id": str(uuid4()),
                "metadata": result.metadata.model_copy(
                    update={"name": "D003 rigid clash-aware v1"}
                ),
            }
        )
    )
    before, after = audit(source), audit(result)
    assert after[0]["interbody_helix_pairs_below_2nm"] == 0
    max_error = 0.0
    for body in source.cluster_transforms:
        positions = [
            np.array(
                [
                    b["backbone_position"]
                    for b in data[2]
                    if b["helix_id"] in body.helix_ids
                ]
            )
            for data in (before, after)
        ]
        x, y = [p - p.mean(0) for p in positions]
        u, _, vt = np.linalg.svd(x.T @ y)
        rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        max_error = max(
            max_error, float(np.linalg.norm(x @ rotation - y, axis=1).max())
        )
    assert max_error < 1e-8
    unchanged = {
        f: getattr(source, f) == getattr(result, f)
        for f in (
            "helices",
            "strands",
            "crossovers",
            "forced_ligations",
            "deformations",
        )
    }
    assert all(unchanged.values())
    target.write_text(result.to_json())
    report = {
        "before": before[0],
        "after": after[0],
        "fit": fit,
        "all_nucleotide_rigid_alignment_max_error_nm": max_error,
        "unchanged_authoring_fields": unchanged,
        "document_id": result.id,
        "limitations": "Coarse helix-envelope clearance; no atomistic validation. Inter-body checks only; internal body geometry is fixed.",
    }
    target.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
    for ax, data, title in zip(
        axs, (before, after), ("Rigid bond-only fit", "Rigid fit with clash prevention")
    ):
        for hid, ends in data[3].items():
            ax.plot(ends[:, 2], ends[:, 1], color=colors[data[4][hid]], lw=1.5)
        if data[1]:
            hits = np.array(data[1])
            ax.scatter(
                hits[:, 2],
                hits[:, 1],
                color="red",
                marker="x",
                s=16,
                label="Helix overlap",
            )
            ax.legend()
        ax.set_aspect("equal")
        ax.set_title(
            f"{title}\n{data[0]['interbody_helix_pairs_below_2nm']} overlapping inter-body helix pairs"
        )
        ax.set_xlabel("Z (nm)")
        ax.set_ylabel("Y (nm)")
    fig.tight_layout()
    fig.savefig(target.with_suffix(".png"), dpi=150)
    plt.close(fig)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run(Path("workspace/Experimental/D003"))
