"""Compare the open-era D003 artifact with a fresh four-body fit, without replacing it."""

from pathlib import Path
import hashlib
import json
from uuid import uuid4

import numpy as np
from threadpoolctl import threadpool_limits

from backend.core.cluster_autodetect import _cluster_by_lattice_neighbors
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.origami_relax import relax_origami
from tools.design_archive.relax_d003 import review_camera


@threadpool_limits.wrap(limits=1, user_api="blas")
def run(folder):
    source = Design.model_validate_json((folder / "D003_imported.nadoc").read_text())
    old_path = folder / "D003_relaxed.nadoc"
    old_bytes = old_path.read_bytes()
    old = Design.model_validate_json(old_bytes)
    target = folder / "D003_rigid_clusters_verified.nadoc"
    if target.exists():
        raise FileExistsError(f"Preserve the existing review artifact: {target}")
    fresh, fit = relax_origami(source)
    fresh = fresh.model_copy(
        update={
            "id": str(uuid4()),
            "metadata": fresh.metadata.model_copy(
                update={"name": "D003 rigid clusters — verified"}
            ),
        }
    )
    fresh = review_camera(fresh)
    bodies = _cluster_by_lattice_neighbors(source).cluster_transforms
    geometries = [_geometry_for_design(d) for d in (source, old, fresh)]

    def key(b):
        return (
            b["strand_id"],
            b["domain_index"],
            b["helix_id"],
            b["bp_index"],
            b["direction"],
            b.get("copy_k", b.get("copy", 0)),
        )

    maps = [{key(b): b for b in geometry} for geometry in geometries]
    assert maps[0].keys() == maps[1].keys() == maps[2].keys()
    results = []
    for body in bodies:
        keys = [k for k, b in maps[0].items() if b["helix_id"] in body.helix_ids]
        positions = [np.array([m[k]["backbone_position"] for k in keys]) for m in maps]
        x = positions[0] - positions[0].mean(0)
        errors = []
        for points in positions[1:]:
            y = points - points.mean(0)
            u, _, vt = np.linalg.svd(x.T @ y)
            correction = np.diag([1, 1, np.linalg.det(u @ vt)])
            errors.append(
                float(np.linalg.norm(x @ (u @ correction @ vt) - y, axis=1).max())
            )
        results.append(
            {
                "helix_labels": [source.find_helix(h).label for h in body.helix_ids],
                "nucleotides_checked": len(keys),
                "old_max_nonrigid_displacement_nm": errors[0],
                "verified_max_nonrigid_displacement_nm": errors[1],
            }
        )
    assert all(r["verified_max_nonrigid_displacement_nm"] < 1e-8 for r in results)
    assert len(fresh.cluster_transforms) == 4
    unchanged = {
        field: getattr(source, field) == getattr(fresh, field)
        for field in (
            "helices",
            "strands",
            "crossovers",
            "forced_ligations",
            "deformations",
        )
    }
    assert all(unchanged.values())
    target.write_text(fresh.to_json())
    report = {
        "old_file": str(old_path),
        "old_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "old_document_id": old.id,
        "old_cluster_count": len(old.cluster_transforms),
        "old_single_helix_clusters": sum(
            len(c.helix_ids) == 1 for c in old.cluster_transforms
        ),
        "verified_file": str(target),
        "verified_document_id": fresh.id,
        "verified_cluster_count": len(fresh.cluster_transforms),
        "unchanged_authoring_fields": unchanged,
        "bodies": results,
        "fit": fit,
    }
    (folder / "rigidity_audit.json").write_text(json.dumps(report, indent=2) + "\n")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
    for ax, geometry, title in zip(
        axs,
        geometries[1:],
        [
            "Existing file: 87 individual-helix transforms",
            "New verified file: four rigid bodies",
        ],
    ):
        for i, body in enumerate(bodies):
            for hid in body.helix_ids:
                xyz = np.array(
                    [
                        b["helical_site"]["axis_point"]
                        for b in geometry
                        if b["helix_id"] == hid
                    ]
                )
                direction = np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0]
                t = xyz @ direction
                ends = xyz[[t.argmin(), t.argmax()]]
                ax.plot(ends[:, 2], ends[:, 1], color=colors[i], lw=1.5)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_xlabel("Z (nm)")
        ax.set_ylabel("Y (nm)")
    fig.suptitle("D003: each color identifies the same original 22-helix body")
    fig.tight_layout()
    fig.savefig(folder / "D003_rigidity_audit.png", dpi=150)
    plt.close(fig)
    print(
        json.dumps(
            {
                "old_cluster_count": report["old_cluster_count"],
                "bodies": results,
                "verified_file": str(target),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    run(Path("workspace/Experimental/D003"))
