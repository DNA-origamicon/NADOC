"""Read-only attribution of >=60-degree surface turns before/after mesh smoothing.

uv run python -m scripts.diagnose_surface_sharpness workspace/mini_rect.nadoc \
    --output .development-artifacts/surface-quality/consistent-stages.json
No surface-generation defaults are changed by this experiment.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import numpy as np
from backend.core.models import Design
from backend.core.atomistic import surface_atom_cloud
from backend.core.surface import compute_split_surfaces_from_cloud, smooth_mesh
from backend.core.surface_acceleration import initialize_surface_cuda
from backend.core.surface_quality import surface_quality


def normals(mesh):
    t = mesh.vertices[mesh.faces].astype(float)
    cross = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    norm = np.linalg.norm(cross, axis=1)
    return cross / np.maximum(norm[:, None], 1e-30)


def diagnose(design, probe, output_dir):
    p, r, s, n = surface_atom_cloud(design)
    initialize_surface_cuda()
    start = time.perf_counter()
    raw = compute_split_surfaces_from_cloud(
        p, r, s, nuc_ids=n, probe_radius=probe, continuous_field=True, smooth=0
    )
    print(
        f"raw mesh: {len(raw.faces)} faces in {time.perf_counter() - start:.2f}s",
        flush=True,
    )
    qraw = surface_quality(raw, hotspot_limit=1000)
    before = normals(raw)
    stages = []
    for count in (1, 4, 8):
        m = smooth_mesh(raw, iterations=count)
        q = surface_quality(m, hotspot_limit=10000)
        points = [
            point for point in q.pop("hotspots") if point["normal_turn_deg"] >= 60
        ]
        for point in points:
            a, b = point["face_indices"]
            ids = np.unique(raw.faces[[a, b]])
            point["before_mesh_smoothing_deg"] = float(
                np.degrees(np.arccos(np.clip(before[a] @ before[b], -1, 1)))
            )
            point["max_vertex_displacement_nm"] = float(
                np.linalg.norm(m.vertices[ids] - raw.vertices[ids], axis=1).max()
            )
        if count == 4:
            from scripts.surface_sharpness_local import enrich_hotspots, plot_hotspot

            # Bound the expensive atom/field attribution while keeping angle
            # transition counts for EVERY sharp edge. Include an induced example.
            local_points = points[:24]
            induced = next(
                (point for point in points if point["before_mesh_smoothing_deg"] < 60),
                None,
            )
            if induced is not None and induced not in local_points:
                local_points.append(induced)
            enrich_hotspots(design, p, r, s, raw, m, local_points, probe)
            output_dir.mkdir(parents=True, exist_ok=True)
            for label, selected in [
                (
                    "preexisting",
                    next(
                        (p for p in points if p["before_mesh_smoothing_deg"] >= 60),
                        None,
                    ),
                ),
                (
                    "smoothing_induced",
                    next(
                        (p for p in points if p["before_mesh_smoothing_deg"] < 60), None
                    ),
                ),
            ]:
                if selected:
                    plot_hotspot(raw, m, selected, output_dir / f"{label}.png")
        q["edges_above_60_already_sharp_in_raw"] = sum(
            p["before_mesh_smoothing_deg"] >= 60 for p in points
        )
        q["edges_crossing_60_due_to_mesh_smoothing"] = sum(
            p["before_mesh_smoothing_deg"] < 60 for p in points
        )
        stages.append({"iterations": count, "quality": q, "edges_over_60": points})
        print(
            f"{count} iterations: >60={q['thresholds']['60']['edges']}, >90={q['thresholds']['90']['edges']}, created above60={q['edges_crossing_60_due_to_mesh_smoothing']}",
            flush=True,
        )
    return {
        "design": design.metadata.name,
        "probe_nm": probe,
        "grid_nm": 0.05,
        "sigma_nm": 0.0425,
        "raw_quality": qraw,
        "stages": stages,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--probe", type=float, default=0.14)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(
        Design.model_validate_json(args.design.read_text()),
        args.probe,
        args.output.parent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
