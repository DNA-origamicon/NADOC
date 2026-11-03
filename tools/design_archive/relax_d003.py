"""Reproduce the authorized D003 experimental import, bond fit, and comparison."""

from pathlib import Path
import json
from uuid import uuid4
import numpy as np
from backend.core.cadnano import import_cadnano
from backend.core.models import Design, CameraPose
from backend.core.origami_relax import relax_origami
from backend.core.design_geometry import _geometry_for_design


def plot(output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 2, figsize=(11, 7))
    for ax, name in zip(axs, ["imported", "relaxed"]):
        design = Design.model_validate_json((output / f"D003_{name}.nadoc").read_text())
        geometry = _geometry_for_design(design)
        for i, helix in enumerate(design.helices):
            xyz = np.array(
                [
                    b["helical_site"]["axis_point"]
                    for b in geometry
                    if b["helix_id"] == helix.id
                ]
            )
            vector = np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0]
            q = (xyz - xyz.mean(0)) @ vector
            ends = xyz[[q.argmin(), q.argmax()]]
            ax.plot(
                ends[:, 2],
                ends[:, 1],
                color=plt.cm.hsv(i / len(design.helices)),
                lw=1.5,
            )
        ax.set_aspect("equal")
        ax.set_title(name)
        ax.set_xlabel("Z (nm)")
        ax.set_ylabel("Y (nm)")
    fig.tight_layout()
    fig.savefig(output / "D003_comparison.png", dpi=150)
    plt.close(fig)


def review_camera(design):
    points = np.array([n["backbone_position"] for n in _geometry_for_design(design)])
    target = (points.min(axis=0) + points.max(axis=0)) / 2
    distance = 2 * np.ptp(points, axis=0).max()
    return design.copy_with(
        camera_poses=[
            CameraPose(
                name="Face-on experimental review",
                target=target.tolist(),
                position=(target + [distance, 0, 0]).tolist(),
                up=[0, 1, 0],
            )
        ]
    )


def run(output):
    design, warnings = import_cadnano(
        json.loads((output / "registered.cadnano.json").read_text())
    )
    for helix in design.helices:
        if helix.grid_pos is not None:
            helix.label = str(helix.grid_pos[0])
    design.metadata.name = "D003 imported — experimental reconstruction"
    design = review_camera(design)
    (output / "D003_imported.nadoc").write_text(design.to_json())
    relaxed, report = relax_origami(design)
    relaxed = relaxed.model_copy(
        update={
            "id": str(uuid4()),
            "metadata": relaxed.metadata.model_copy(
                update={"name": "D003 relaxed — experimental attempt"}
            ),
        }
    )
    relaxed = review_camera(relaxed)
    report["import_warnings"] = warnings
    (output / "D003_relaxed.nadoc").write_text(relaxed.to_json())
    (output / "relaxation.json").write_text(json.dumps(report, indent=2) + "\n")
    plot(output)
    # Independently compare rendered within-body distances before and after.
    from scipy.spatial.distance import pdist

    before_geometry = _geometry_for_design(design)
    after_geometry = _geometry_for_design(relaxed)
    errors = []
    for cluster in relaxed.cluster_transforms:
        points = []
        for geometry in (before_geometry, after_geometry):
            body = np.array(
                [
                    b["backbone_position"]
                    for b in geometry
                    if b["helix_id"] in cluster.helix_ids
                ]
            )
            points.append(body[np.linspace(0, len(body) - 1, 64, dtype=int)])
        errors.append(float(np.max(np.abs(pdist(points[0]) - pdist(points[1])))))
    assert len(errors) == 4 and max(errors) < 1e-8
    validation = {
        "unchanged_authoring_fields": {
            field: getattr(design, field) == getattr(relaxed, field)
            for field in (
                "helices",
                "strands",
                "crossovers",
                "forced_ligations",
                "deformations",
            )
        },
        "rigid_cluster_sizes": [len(c.helix_ids) for c in relaxed.cluster_transforms],
        "max_sampled_internal_distance_change_nm": max(errors),
        "connecting_bonds_optimized": report["bond_count"],
        "internal_interhelix_bonds_excluded": report["internal_bond_count"],
        "distinct_document_ids": design.id != relaxed.id,
        "saved_face_on_cameras": bool(design.camera_poses and relaxed.camera_poses),
        "intended_square_plate_recovered": False,
        "visual_review": "Flat four-body arrangement with intact sections; residual overlaps remain.",
    }
    assert all(validation["unchanged_authoring_fields"].values())
    (output / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")


if __name__ == "__main__":
    run(Path("workspace/Experimental/D003"))
