"""Hierarchical coarse-grained tube assembly utilities.

This experiment keeps a massive origami tube symbolic: each origami/ring
member is one repeated instance with a stable source design and transform.
Only requested windows are expanded into a normal NADOC Design for atomistic
or mrDNA follow-up.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from backend.core.atomistic import build_atomistic_model, crossover_geometry_diagnostics
from backend.core.models import Design, DesignMetadata, Helix, LatticeType, Strand, Vec3
from backend.core.pdb_export import export_identity_json, export_identity_tsv, export_pdb, export_psf


DEFAULT_SPEC: dict[str, Any] = {
    "unit_source": "Examples/2hb_xover_val.nadoc",
    "ring": {
        "units": 12,
        "radius_nm": 80.0,
        "angular_offset_deg": 0.0,
        "closure_connector_labels": ["left", "right"],
    },
    "stack": {
        "rings": 4,
        "axial_spacing_nm": 16.0,
        "twist_deg_per_ring": 0.0,
    },
    "coarse_sites": [
        {"name": "center", "position_nm": [0.0, 0.0, 0.0]},
        {"name": "left", "position_nm": [0.0, -4.0, 0.0]},
        {"name": "right", "position_nm": [0.0, 4.0, 0.0]},
        {"name": "bottom", "position_nm": [0.0, 0.0, -8.0]},
        {"name": "top", "position_nm": [0.0, 0.0, 8.0]},
    ],
    "relaxation": {
        "steps": 200,
        "dt": 0.08,
        "ring_spring": 1.0,
        "stack_spring": 1.0,
        "radial_spring": 0.4,
        "axial_spring": 0.2,
        "exclusion_spring": 4.0,
        "min_center_distance_nm": 4.0,
        "damping": 0.85,
        "record_every": 20,
    },
    "reconstruction": {
        "ring_start": 0,
        "ring_count": 1,
        "unit_start": 0,
        "unit_count": 3,
        "context_rings": 0,
        "context_units": 1,
    },
}


@dataclass(frozen=True)
class CoarseSite:
    name: str
    position_nm: np.ndarray


@dataclass(frozen=True)
class SymbolicInstance:
    id: str
    source_design: str
    ring_index: int
    unit_index: int
    transform: np.ndarray
    connector_sites: dict[str, list[float]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_design": self.source_design,
            "repeat_indices": {
                "ring": self.ring_index,
                "unit": self.unit_index,
            },
            "transform": [float(v) for v in self.transform.reshape(-1)],
            "connector_sites": self.connector_sites,
        }


@dataclass
class TubeState:
    spec: dict[str, Any]
    centers: np.ndarray
    ring_indices: np.ndarray
    unit_indices: np.ndarray


def load_spec(path: Path | None = None) -> dict[str, Any]:
    spec = json.loads(json.dumps(DEFAULT_SPEC))
    if path is not None:
        user = json.loads(path.read_text())
        _deep_update(spec, user)
    _validate_spec(spec)
    return spec


def _deep_update(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _validate_spec(spec: dict[str, Any]) -> None:
    if int(spec["ring"]["units"]) < 3:
        raise ValueError("ring.units must be at least 3")
    if int(spec["stack"]["rings"]) < 1:
        raise ValueError("stack.rings must be at least 1")
    if float(spec["ring"]["radius_nm"]) <= 0:
        raise ValueError("ring.radius_nm must be positive")
    if float(spec["stack"]["axial_spacing_nm"]) <= 0:
        raise ValueError("stack.axial_spacing_nm must be positive")


def coarse_sites_from_spec(spec: dict[str, Any]) -> list[CoarseSite]:
    sites = []
    for row in spec.get("coarse_sites", []):
        sites.append(CoarseSite(
            name=str(row["name"]),
            position_nm=np.asarray(row["position_nm"], dtype=float),
        ))
    return sites


def initial_tube_state(spec: dict[str, Any], *, perturb_nm: float = 0.0, seed: int = 1) -> TubeState:
    n_units = int(spec["ring"]["units"])
    n_rings = int(spec["stack"]["rings"])
    radius = float(spec["ring"]["radius_nm"])
    z_step = float(spec["stack"]["axial_spacing_nm"])
    theta0 = math.radians(float(spec["ring"].get("angular_offset_deg", 0.0)))
    twist = math.radians(float(spec["stack"].get("twist_deg_per_ring", 0.0)))

    centers: list[list[float]] = []
    ring_indices: list[int] = []
    unit_indices: list[int] = []
    for ring_idx in range(n_rings):
        for unit_idx in range(n_units):
            theta = theta0 + twist * ring_idx + 2.0 * math.pi * unit_idx / n_units
            centers.append([radius * math.cos(theta), radius * math.sin(theta), ring_idx * z_step])
            ring_indices.append(ring_idx)
            unit_indices.append(unit_idx)

    arr = np.asarray(centers, dtype=float)
    if perturb_nm > 0:
        rng = np.random.default_rng(seed)
        arr += rng.normal(0.0, perturb_nm, size=arr.shape)
    return TubeState(
        spec=spec,
        centers=arr,
        ring_indices=np.asarray(ring_indices, dtype=int),
        unit_indices=np.asarray(unit_indices, dtype=int),
    )


def instance_transform(center: np.ndarray) -> np.ndarray:
    radial = np.asarray([center[0], center[1], 0.0], dtype=float)
    r_norm = float(np.linalg.norm(radial))
    if r_norm < 1e-9:
        radial = np.asarray([1.0, 0.0, 0.0])
    else:
        radial /= r_norm
    tangent = np.asarray([-radial[1], radial[0], 0.0], dtype=float)
    axial = np.asarray([0.0, 0.0, 1.0], dtype=float)
    mat = np.eye(4, dtype=float)
    mat[:3, 0] = radial
    mat[:3, 1] = tangent
    mat[:3, 2] = axial
    mat[:3, 3] = center
    return mat


def symbolic_instances(state: TubeState) -> list[SymbolicInstance]:
    source = str(state.spec["unit_source"])
    sites = coarse_sites_from_spec(state.spec)
    instances: list[SymbolicInstance] = []
    for i, center in enumerate(state.centers):
        ring = int(state.ring_indices[i])
        unit = int(state.unit_indices[i])
        transform = instance_transform(center)
        connector_sites = {
            site.name: _transform_point(transform, site.position_nm).tolist()
            for site in sites
        }
        instances.append(SymbolicInstance(
            id=f"r{ring:04d}_u{unit:04d}",
            source_design=source,
            ring_index=ring,
            unit_index=unit,
            transform=transform,
            connector_sites=connector_sites,
        ))
    return instances


def _transform_point(mat: np.ndarray, point: np.ndarray) -> np.ndarray:
    p = np.asarray([point[0], point[1], point[2], 1.0], dtype=float)
    return (mat @ p)[:3]


def ring_closure_error_nm(state: TubeState) -> float:
    n_units = int(state.spec["ring"]["units"])
    target = _ring_chord_nm(state.spec)
    errors = []
    for ring in range(int(state.spec["stack"]["rings"])):
        idx = np.where(state.ring_indices == ring)[0]
        by_unit = {int(state.unit_indices[i]): i for i in idx}
        for unit in range(n_units):
            a = by_unit[unit]
            b = by_unit[(unit + 1) % n_units]
            errors.append(abs(float(np.linalg.norm(state.centers[b] - state.centers[a])) - target))
    return float(max(errors, default=0.0))


def _ring_chord_nm(spec: dict[str, Any]) -> float:
    n_units = int(spec["ring"]["units"])
    radius = float(spec["ring"]["radius_nm"])
    return 2.0 * radius * math.sin(math.pi / n_units)


def restraint_energy(state: TubeState) -> dict[str, float]:
    spec = state.spec
    n_units = int(spec["ring"]["units"])
    n_rings = int(spec["stack"]["rings"])
    relax = spec["relaxation"]
    target_ring = _ring_chord_nm(spec)
    target_stack = float(spec["stack"]["axial_spacing_nm"])
    target_radius = float(spec["ring"]["radius_nm"])
    min_dist = float(relax["min_center_distance_nm"])

    ring_e = 0.0
    stack_e = 0.0
    radial_e = 0.0
    axial_e = 0.0
    exclusion_e = 0.0
    by_key = {
        (int(state.ring_indices[i]), int(state.unit_indices[i])): i
        for i in range(len(state.centers))
    }

    for ring in range(n_rings):
        for unit in range(n_units):
            a = by_key[(ring, unit)]
            b = by_key[(ring, (unit + 1) % n_units)]
            ring_e += _spring_energy(state.centers[a], state.centers[b], target_ring)
            if ring + 1 < n_rings:
                c = by_key[(ring + 1, unit)]
                stack_e += _spring_energy(state.centers[a], state.centers[c], target_stack)

    for i, center in enumerate(state.centers):
        radius = float(np.linalg.norm(center[:2]))
        radial_e += 0.5 * (radius - target_radius) ** 2
        target_z = int(state.ring_indices[i]) * target_stack
        axial_e += 0.5 * (center[2] - target_z) ** 2

    for i, j in _near_pairs(state.centers, min_dist):
        d = float(np.linalg.norm(state.centers[j] - state.centers[i]))
        if d < min_dist:
            exclusion_e += 0.5 * (min_dist - d) ** 2

    return {
        "ring": ring_e * float(relax["ring_spring"]),
        "stack": stack_e * float(relax["stack_spring"]),
        "radial": radial_e * float(relax["radial_spring"]),
        "axial": axial_e * float(relax["axial_spring"]),
        "exclusion": exclusion_e * float(relax["exclusion_spring"]),
    }


def _spring_energy(a: np.ndarray, b: np.ndarray, target: float) -> float:
    return 0.5 * (float(np.linalg.norm(b - a)) - target) ** 2


def relax_tube(state: TubeState) -> tuple[TubeState, list[dict[str, Any]]]:
    spec = state.spec
    relax = spec["relaxation"]
    steps = int(relax["steps"])
    dt = float(relax["dt"])
    damping = float(relax["damping"])
    record_every = max(1, int(relax["record_every"]))

    centers = state.centers.copy()
    velocities = np.zeros_like(centers)
    trajectory: list[dict[str, Any]] = []

    for step in range(steps + 1):
        current = TubeState(spec, centers.copy(), state.ring_indices.copy(), state.unit_indices.copy())
        if step % record_every == 0 or step == steps:
            energy = restraint_energy(current)
            trajectory.append({
                "step": step,
                "energy": {k: float(v) for k, v in energy.items()},
                "total_energy": float(sum(energy.values())),
                "centers": centers.tolist(),
            })
        if step == steps:
            break
        forces = _compute_forces(current)
        velocities = damping * (velocities + dt * forces)
        centers = centers + dt * velocities

    return TubeState(spec, centers, state.ring_indices.copy(), state.unit_indices.copy()), trajectory


def _compute_forces(state: TubeState) -> np.ndarray:
    spec = state.spec
    relax = spec["relaxation"]
    n_units = int(spec["ring"]["units"])
    n_rings = int(spec["stack"]["rings"])
    target_ring = _ring_chord_nm(spec)
    target_stack = float(spec["stack"]["axial_spacing_nm"])
    target_radius = float(spec["ring"]["radius_nm"])
    min_dist = float(relax["min_center_distance_nm"])

    forces = np.zeros_like(state.centers)
    by_key = {
        (int(state.ring_indices[i]), int(state.unit_indices[i])): i
        for i in range(len(state.centers))
    }

    def add_pair(i: int, j: int, target: float, stiffness: float) -> None:
        delta = state.centers[j] - state.centers[i]
        dist = float(np.linalg.norm(delta))
        if dist < 1e-9:
            return
        force = stiffness * (dist - target) * (delta / dist)
        forces[i] += force
        forces[j] -= force

    for ring in range(n_rings):
        for unit in range(n_units):
            a = by_key[(ring, unit)]
            b = by_key[(ring, (unit + 1) % n_units)]
            add_pair(a, b, target_ring, float(relax["ring_spring"]))
            if ring + 1 < n_rings:
                c = by_key[(ring + 1, unit)]
                add_pair(a, c, target_stack, float(relax["stack_spring"]))

    for i, center in enumerate(state.centers):
        xy = center[:2]
        radius = float(np.linalg.norm(xy))
        if radius > 1e-9:
            forces[i, :2] += -float(relax["radial_spring"]) * (radius - target_radius) * (xy / radius)
        target_z = int(state.ring_indices[i]) * target_stack
        forces[i, 2] += -float(relax["axial_spring"]) * (center[2] - target_z)

    for i, j in _near_pairs(state.centers, min_dist):
        delta = state.centers[j] - state.centers[i]
        dist = float(np.linalg.norm(delta))
        if 1e-9 < dist < min_dist:
            force = float(relax["exclusion_spring"]) * (min_dist - dist) * (delta / dist)
            forces[i] -= force
            forces[j] += force
    return forces


def shape_report(initial: TubeState, relaxed: TubeState, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
    initial_energy = restraint_energy(initial)
    final_energy = restraint_energy(relaxed)
    return {
        "schema": "nadoc.exp28_hierarchical_tube_shape_report.v1",
        "tube": {
            "rings": int(relaxed.spec["stack"]["rings"]),
            "units_per_ring": int(relaxed.spec["ring"]["units"]),
            "instances": int(len(relaxed.centers)),
            "radius_nm": float(relaxed.spec["ring"]["radius_nm"]),
            "axial_spacing_nm": float(relaxed.spec["stack"]["axial_spacing_nm"]),
            "approx_length_nm": float((int(relaxed.spec["stack"]["rings"]) - 1) * float(relaxed.spec["stack"]["axial_spacing_nm"])),
        },
        "closure": {
            "max_ring_neighbor_error_nm": ring_closure_error_nm(relaxed),
        },
        "clashes": clash_report(relaxed),
        "energy": {
            "initial": initial_energy,
            "final": final_energy,
            "initial_total": float(sum(initial_energy.values())),
            "final_total": float(sum(final_energy.values())),
            "trajectory_frames": len(trajectory),
        },
    }


def clash_report(state: TubeState) -> dict[str, Any]:
    min_dist = float(state.spec["relaxation"]["min_center_distance_nm"])
    min_observed = _nearest_neighbor_distance(state.centers)
    violations = len(_near_pairs(state.centers, min_dist))
    return {
        "min_center_distance_nm": min_dist,
        "min_observed_center_distance_nm": min_observed,
        "violating_pairs": violations,
    }


def _near_pairs(points: np.ndarray, cutoff: float) -> list[tuple[int, int]]:
    if len(points) < 2 or cutoff <= 0:
        return []
    from scipy.spatial import cKDTree

    return [(int(i), int(j)) for i, j in cKDTree(points).query_pairs(cutoff)]


def _nearest_neighbor_distance(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    from scipy.spatial import cKDTree

    distances, _idxs = cKDTree(points).query(points, k=2)
    return float(np.min(distances[:, 1]))


def select_reconstruction_instances(
    instances: Iterable[SymbolicInstance],
    spec: dict[str, Any],
    window: dict[str, Any] | None = None,
) -> tuple[list[SymbolicInstance], dict[str, Any]]:
    cfg = dict(spec.get("reconstruction", {}))
    if window:
        cfg.update(window)
    n_units = int(spec["ring"]["units"])
    n_rings = int(spec["stack"]["rings"])
    ring_start = int(cfg.get("ring_start", 0))
    ring_count = int(cfg.get("ring_count", 1))
    unit_start = int(cfg.get("unit_start", 0))
    unit_count = int(cfg.get("unit_count", 1))
    context_rings = int(cfg.get("context_rings", 0))
    context_units = int(cfg.get("context_units", 0))

    ring_lo = max(0, ring_start - context_rings)
    ring_hi = min(n_rings - 1, ring_start + ring_count + context_rings - 1)
    selected_units = {
        (unit_start + offset) % n_units
        for offset in range(-context_units, unit_count + context_units)
    }
    selected = [
        inst for inst in instances
        if ring_lo <= inst.ring_index <= ring_hi and inst.unit_index in selected_units
    ]
    manifest = {
        "schema": "nadoc.exp28_reconstruction_manifest.v1",
        "window": {
            "ring_start": ring_start,
            "ring_count": ring_count,
            "unit_start": unit_start,
            "unit_count": unit_count,
            "context_rings": context_rings,
            "context_units": context_units,
            "expanded_ring_range": [ring_lo, ring_hi],
            "expanded_units": sorted(selected_units),
        },
        "instances": [inst.to_json_dict() for inst in selected],
    }
    return selected, manifest


def expand_instances_to_design(instances: list[SymbolicInstance], source_design: Design) -> Design:
    helices: list[Helix] = []
    strands: list[Strand] = []
    for inst in instances:
        prefix = f"inst-{inst.id}::"
        for helix in source_design.helices:
            helices.append(_transform_helix(helix, inst.transform, prefix))
        for strand in source_design.strands:
            strands.append(_prefix_strand(strand, prefix))
    helix_ids = [h.id for h in helices]
    if len(helix_ids) != len(set(helix_ids)):
        raise ValueError("expanded reconstruction window has duplicate helix IDs")
    return Design(
        id="exp28_window",
        helices=helices,
        strands=strands,
        lattice_type=source_design.lattice_type if source_design.lattice_type else LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Exp28 reconstruction window"),
    )


def _transform_helix(helix: Helix, mat: np.ndarray, prefix: str) -> Helix:
    return helix.model_copy(update={
        "id": f"{prefix}{helix.id}",
        "axis_start": Vec3.from_array(_transform_point(mat, helix.axis_start.to_array())),
        "axis_end": Vec3.from_array(_transform_point(mat, helix.axis_end.to_array())),
    })


def _prefix_strand(strand: Strand, prefix: str) -> Strand:
    return strand.model_copy(update={
        "id": f"{prefix}{strand.id}",
        "domains": [
            domain.model_copy(update={"helix_id": f"{prefix}{domain.helix_id}"})
            for domain in strand.domains
        ],
    })


def write_outputs(
    out_dir: Path,
    initial: TubeState,
    relaxed: TubeState,
    trajectory: list[dict[str, Any]],
    *,
    reconstruct: bool = True,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    instances = symbolic_instances(relaxed)
    report = shape_report(initial, relaxed, trajectory)
    selected, manifest = select_reconstruction_instances(instances, relaxed.spec)

    written: dict[str, str] = {}

    def write_json(rel: str, payload: Any) -> None:
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        written[rel] = str(path)

    write_json("tube_spec.resolved.json", relaxed.spec)
    write_json("relaxed_instances.json", {
        "schema": "nadoc.exp28_relaxed_instances.v1",
        "instances": [inst.to_json_dict() for inst in instances],
    })
    write_json("cg_trajectory.json", {
        "schema": "nadoc.exp28_cg_trajectory.v1",
        "frames": trajectory,
    })
    write_json("shape_report.json", report)
    write_json("reconstruction_manifest.json", manifest)

    if reconstruct and selected:
        source_path = Path(relaxed.spec["unit_source"])
        if not source_path.is_absolute():
            source_path = Path.cwd() / source_path
        source_design = Design.from_json(source_path.read_text())
        window_design = expand_instances_to_design(selected, source_design)
        window_dir = out_dir / "window_atomistic"
        window_dir.mkdir(parents=True, exist_ok=True)
        design_path = window_dir / "window.nadoc"
        design_path.write_text(window_design.to_json(indent=2))
        written["window_atomistic/window.nadoc"] = str(design_path)

        model = build_atomistic_model(window_design)
        diagnostics = crossover_geometry_diagnostics(window_design)
        files = {
            "window.pdb": export_pdb(window_design, model=model),
            "window.stub.psf": export_psf(window_design, model=model),
            "window.identity.json": export_identity_json(window_design, model=model),
            "window.identity.tsv": export_identity_tsv(window_design, model=model),
            "atomistic_diagnostics.json": json.dumps({
                "schema": "nadoc.exp28_window_atomistic_diagnostics.v1",
                "atoms": len(model.atoms),
                "bonds": len(model.bonds),
                "nucleotides": len({(a.chain_id, a.seq_num) for a in model.atoms}),
                "crossover_geometry": diagnostics,
            }, indent=2),
        }
        for name, text in files.items():
            path = window_dir / name
            path.write_text(text if text.endswith("\n") else text + "\n")
            written[f"window_atomistic/{name}"] = str(path)

    return written


def run_workflow(
    *,
    spec_path: Path | None,
    out_dir: Path,
    perturb_nm: float = 0.0,
    seed: int = 1,
    reconstruct: bool = True,
) -> dict[str, str]:
    spec = load_spec(spec_path)
    initial = initial_tube_state(spec, perturb_nm=perturb_nm, seed=seed)
    relaxed, trajectory = relax_tube(initial)
    return write_outputs(out_dir, initial, relaxed, trajectory, reconstruct=reconstruct)
