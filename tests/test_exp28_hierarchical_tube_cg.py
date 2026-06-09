from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from experiments.exp28_hierarchical_tube_cg.tube_cg import (
    DEFAULT_SPEC,
    expand_instances_to_design,
    initial_tube_state,
    load_spec,
    relax_tube,
    restraint_energy,
    ring_closure_error_nm,
    select_reconstruction_instances,
    shape_report,
    symbolic_instances,
    write_outputs,
)


def _spec(**updates):
    spec = json.loads(json.dumps(DEFAULT_SPEC))
    spec["ring"]["units"] = updates.pop("units", 8)
    spec["ring"]["radius_nm"] = updates.pop("radius_nm", 40.0)
    spec["stack"]["rings"] = updates.pop("rings", 3)
    spec["stack"]["axial_spacing_nm"] = updates.pop("axial_spacing_nm", 12.0)
    spec["relaxation"]["steps"] = updates.pop("steps", 50)
    spec["relaxation"]["record_every"] = updates.pop("record_every", 10)
    for section, vals in updates.items():
        spec[section].update(vals)
    return spec


def test_ring_closure_transform_composes_to_identity_scale():
    spec = _spec(units=12, radius_nm=50.0, rings=1)
    state = initial_tube_state(spec)
    assert ring_closure_error_nm(state) < 1e-9

    instances = symbolic_instances(state)
    first = instances[0].transform
    last = instances[-1].transform
    delta = first @ np.linalg.inv(last)
    expected_step = 2.0 * math.pi / spec["ring"]["units"]
    actual_step = math.atan2(delta[1, 0], delta[0, 0])
    assert abs(abs(actual_step) - expected_step) < 1e-9


def test_axial_stacking_positions_and_identity_stability_after_relaxation():
    spec = _spec(units=6, rings=4, axial_spacing_nm=15.0)
    initial = initial_tube_state(spec, perturb_nm=0.2, seed=4)
    initial_ids = [i.id for i in symbolic_instances(initial)]
    relaxed, _traj = relax_tube(initial)
    relaxed_ids = [i.id for i in symbolic_instances(relaxed)]

    assert initial_ids == relaxed_ids
    for ring_idx in range(spec["stack"]["rings"]):
        z_vals = relaxed.centers[relaxed.ring_indices == ring_idx, 2]
        assert abs(float(z_vals.mean()) - ring_idx * spec["stack"]["axial_spacing_nm"]) < 0.5


def test_coarse_relaxation_decreases_energy_without_nans():
    spec = _spec(units=8, rings=3, radius_nm=30.0, steps=80)
    initial = initial_tube_state(spec, perturb_nm=1.5, seed=7)
    relaxed, traj = relax_tube(initial)

    initial_total = sum(restraint_energy(initial).values())
    final_total = sum(restraint_energy(relaxed).values())
    assert np.isfinite(relaxed.centers).all()
    assert traj[0]["total_energy"] > traj[-1]["total_energy"]
    assert final_total < initial_total


def test_excluded_volume_report_catches_overlaps():
    spec = _spec(units=4, rings=1, radius_nm=2.0, steps=1)
    spec["relaxation"]["min_center_distance_nm"] = 5.0
    state = initial_tube_state(spec)
    report = shape_report(state, state, [])
    assert report["clashes"]["violating_pairs"] > 0


def test_window_expansion_produces_unique_design_and_atomistic_model():
    spec = _spec(units=6, rings=2)
    spec["reconstruction"].update({
        "ring_start": 0,
        "ring_count": 1,
        "unit_start": 0,
        "unit_count": 2,
        "context_units": 1,
    })
    state = initial_tube_state(spec)
    instances = symbolic_instances(state)
    selected, manifest = select_reconstruction_instances(instances, spec)
    source = Design.from_json(Path(spec["unit_source"]).read_text())
    expanded = expand_instances_to_design(selected, source)

    assert len(selected) == 4
    assert manifest["window"]["expanded_units"] == [0, 1, 2, 5]
    assert len({h.id for h in expanded.helices}) == len(expanded.helices)
    assert all(d.helix_id.startswith("inst-") for s in expanded.strands for d in s.domains)

    atomistic = build_atomistic_model(expanded)
    assert len(atomistic.atoms) > 0
    assert len(atomistic.bonds) > 0


def test_write_outputs_reproducible_window_manifest(tmp_path):
    spec = _spec(units=6, rings=2, steps=10)
    initial = initial_tube_state(spec)
    relaxed, traj = relax_tube(initial)
    written1 = write_outputs(tmp_path / "a", initial, relaxed, traj, reconstruct=False)
    written2 = write_outputs(tmp_path / "b", initial, relaxed, traj, reconstruct=False)

    a = json.loads(Path(written1["reconstruction_manifest.json"]).read_text())
    b = json.loads(Path(written2["reconstruction_manifest.json"]).read_text())
    assert a == b


def test_load_spec_deep_overrides(tmp_path):
    path = tmp_path / "tube_spec.json"
    path.write_text(json.dumps({
        "ring": {"units": 10},
        "stack": {"rings": 2},
        "relaxation": {"steps": 3},
    }))
    spec = load_spec(path)
    assert spec["ring"]["units"] == 10
    assert spec["ring"]["radius_nm"] == DEFAULT_SPEC["ring"]["radius_nm"]
    assert spec["stack"]["rings"] == 2
    assert spec["relaxation"]["steps"] == 3


def test_scale_smoke_symbolic_memory_scales_with_instance_count():
    spec = _spec(units=80, rings=125, radius_nm=150.0, axial_spacing_nm=8.0, steps=0)
    state = initial_tube_state(spec)
    instances = symbolic_instances(state)
    approx_length = (spec["stack"]["rings"] - 1) * spec["stack"]["axial_spacing_nm"]

    assert len(instances) == 10_000
    assert approx_length >= 900.0
    assert state.centers.shape == (10_000, 3)
    assert len(instances[0].connector_sites) == len(spec["coarse_sites"])

