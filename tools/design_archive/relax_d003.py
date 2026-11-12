"""Legacy review helpers and a guarded shared-workflow relaxation entry point."""

from pathlib import Path
import numpy as np
from backend.core.models import Design, CameraPose
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


def run(folder):
    """Compatibility entry point; rejects legacy source histories before fitting."""
    from tools.design_archive.shared_pipeline import run as shared_run
    return shared_run(design_id='D003', run_id='recorded-relaxation',
                      source_part=Path(folder) / 'D003_imported.nadoc', relax=True)


if __name__ == '__main__':
    run(Path('workspace/Experimental/D003'))
