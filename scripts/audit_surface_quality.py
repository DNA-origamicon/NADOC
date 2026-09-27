"""Focused read-only surface quality/probe audit; no test session needed for related work.

Example: uv run python -m scripts.audit_surface_quality workspace/mini_rect.nadoc \
    --probe .14 --probe .24 --repeats 3 --output .development-artifacts/surface-quality/mini_rect.json
Timing excludes quality analysis/serialization and reports warm, alternating-order
samples separately from warmup. No design, geometry lock, or visual golden is changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time
from unittest.mock import patch

import numpy as np

from backend.api.routes_display_geometry import _build_design_surface_mesh
from backend.core.models import Design
from backend.core import surface
from backend.core.surface_acceleration import initialize_surface_cuda
from backend.core.surface_quality import surface_quality
from backend.core.surface_field import CONTINUOUS_SIGMA_NM


def audit(design, probes, repeats):
    roles = {s.id: "scaffold" if s.is_scaffold else "staple" for s in design.strands}
    result = {
        "design": design.metadata.name,
        "cuda_warmed": initialize_surface_cuda(),
        "cases": [],
    }
    original = surface.compute_surface_from_cloud
    for probe in probes:
        samples = {detail: [] for detail in ("continuous", "chimerax")}
        last = {}
        for repeat in range(repeats + 1):  # first pair is warmup, excluded from median
            order = (
                ("continuous", "chimerax")
                if repeat % 2 == 0
                else ("chimerax", "continuous")
            )
            for detail in order:
                calls = []

                def traced(*args, **kwargs):
                    gs = kwargs["grid_spacing"]
                    radius = kwargs["probe_radius"]
                    calls.append(
                        {
                            "grid_spacing_nm": gs,
                            "probe_radius_nm": radius,
                            "probe_radius_voxels": radius / gs,
                            "stencil_axial_reach_nm": int(np.floor(radius / gs)) * gs,
                            "filter_sigma_nm": CONTINUOUS_SIGMA_NM
                            if detail in {"continuous", "chimerax"}
                            else None,
                        }
                    )
                    return original(*args, **kwargs)

                start = time.perf_counter()
                with patch.object(surface, "compute_surface_from_cloud", traced):
                    mesh = _build_design_surface_mesh(
                        design, 0.2, probe, 1.3, 15, detail
                    )
                elapsed = time.perf_counter() - start
                if repeat:
                    samples[detail].append(elapsed)
                else:
                    print(f"warmup {detail} probe={probe}: {elapsed:.3f}s", flush=True)
                last[detail] = (mesh, calls)
                print(
                    f"sample {repeat} {detail} probe={probe}: {elapsed:.3f}s",
                    flush=True,
                )
        for detail, (mesh, calls) in last.items():
            # Split construction concatenates complete strand meshes in first-appearance
            # order. That order maps traced calls to actual surface owner IDs.
            strand_ids = list(dict.fromkeys(mesh.vertex_strand_ids))
            if len(strand_ids) != len(calls):
                raise ValueError(
                    "Empty strand meshes prevent unambiguous sampling attribution"
                )
            for sid, record in zip(strand_ids, calls):
                record.update(strand_id=sid, role=roles.get(sid, "other"))
            q = surface_quality(mesh)
            per_role = {}
            vertex_roles = np.array(
                [roles.get(sid, "other") for sid in mesh.vertex_strand_ids]
            )
            for role in sorted(set(vertex_roles)):
                faces = mesh.faces[np.all(vertex_roles[mesh.faces] == role, axis=1)]
                indices, remapped = np.unique(faces, return_inverse=True)
                part = surface.SurfaceMesh(
                    mesh.vertices[indices],
                    remapped.reshape(-1, 3),
                    [mesh.vertex_strand_ids[i] for i in indices],
                )
                per_role[role] = surface_quality(part)
            result["cases"].append(
                {
                    "detail": detail,
                    "probe_radius_nm": probe,
                    "warm_samples_s": samples[detail],
                    "warm_median_s": statistics.median(samples[detail]),
                    "sampling": calls,
                    "quality": q,
                    "by_role": per_role,
                }
            )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("design", type=Path)
    p.add_argument("--probe", type=float, action="append")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.repeats < 1:
        p.error("--repeats must be positive")
    probes = args.probe or [0.10, 0.14, 0.24]
    if any(not np.isfinite(r) or not 0 <= r <= 0.5 for r in probes):
        p.error("probe must be between 0 and 0.5 nm")
    design = Design.model_validate_json(args.design.read_text())
    result = audit(design, probes, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Report: {args.output}", flush=True)


if __name__ == "__main__":
    main()
