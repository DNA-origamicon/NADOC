"""
Integration test for the MD trajectory loading pipeline.

Exercises the same code path that /ws/md-run triggers:
  scan_run_dir → build_chain_map → build_p_gro_order → MDAnalysis Universe
  → _try_unwrap (no-op for GRO) → centroid_offset → _extract_universe(frame=0)

Generates a native minimized package and controlled XTC frames in a temporary directory.
"""

from __future__ import annotations

import math

import pytest

pytest_plugins = ["tests.md_trajectory_fixture"]


@pytest.fixture(scope="module")
def design(generated_gromacs):
    return generated_gromacs.design


@pytest.fixture(scope="module")
def universe(generated_gromacs):
    import MDAnalysis as mda
    root = generated_gromacs.folder
    return mda.Universe(str(root / "em.gro"), str(root / "view_whole.xtc"))


@pytest.fixture(scope="module")
def chain_data(design, generated_gromacs):
    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map, build_p_gro_order

    model = build_atomistic_model(design)
    cm = build_chain_map(model)
    pdb_txt = generated_gromacs.pdb.read_text(errors="replace")
    p_order = build_p_gro_order(pdb_txt, cm)
    return {"chain_map": cm, "p_order": p_order}


# ── tests ─────────────────────────────────────────────────────────────────────


def test_universe_opens(universe):
    assert universe.atoms.n_atoms > 0
    assert len(universe.trajectory) > 0


def test_n_frames_nonzero(universe):
    assert len(universe.trajectory) > 100, "Expected >100 frames in view_whole.xtc"


def test_chain_map_size(chain_data):
    cm = chain_data["chain_map"]
    assert len(cm) > 0, "Chain map is empty"


def test_p_order_size(chain_data):
    p_order = chain_data["p_order"]
    cm = chain_data["chain_map"]
    assert len(p_order) > 0
    assert len(p_order) <= len(cm) + 10  # allow small discrepancy for 5'-P stripping


def test_try_unwrap_skips_gro(universe, capsys):
    """GRO topology has no bonds — _try_unwrap must return early without hanging."""
    import time

    logs: list[str] = []

    # Inline the same logic as ws.py _try_unwrap.
    start = time.monotonic()
    try:
        from MDAnalysis.transformations import unwrap as mda_unwrap  # type: ignore

        try:
            _ = universe.bonds
            has_bonds = True
        except Exception:
            has_bonds = False
        if not has_bonds:
            logs.append("skip")
        else:
            universe.trajectory.add_transformations(mda_unwrap(universe.atoms))
            logs.append("unwrapped")
    except Exception as exc:
        logs.append(f"exception:{exc}")
    elapsed = time.monotonic() - start

    assert "skip" in logs, "Expected early return for GRO topology"
    assert elapsed < 5.0, f"_try_unwrap took {elapsed:.1f}s — guess_bonds not skipped!"


def test_centroid_offset_nontrivial(universe, chain_data, design):
    from backend.core.atomistic_to_nadoc import _extract_universe, centroid_offset

    beads_0 = _extract_universe(universe, 0, chain_data["p_order"])
    T = centroid_offset(beads_0, design)
    magnitude = math.sqrt(sum(c**2 for c in T))
    # GROMACS places the molecule ~6 nm from origin in the periodic box.
    assert magnitude > 0.5, f"Centroid offset suspiciously small: {T}"


def test_frame0_positions_finite(universe, chain_data, design):
    from backend.core.atomistic_to_nadoc import _extract_universe, centroid_offset

    p_order = chain_data["p_order"]
    beads_0 = _extract_universe(universe, 0, p_order)
    T = centroid_offset(beads_0, design)

    for b in beads_0:
        x, y, z = b.pos[0] + T[0], b.pos[1] + T[1], b.pos[2] + T[2]
        assert math.isfinite(x) and math.isfinite(y) and math.isfinite(z)
        # NADOC world is ~±20 nm for a 10-helix bundle.
        assert abs(x) < 30 and abs(y) < 30 and abs(z) < 30, (
            f"Position out of expected range: ({x:.2f},{y:.2f},{z:.2f}) nm"
        )


def test_ready_payload_fields(universe, chain_data, design, generated_gromacs):
    """Simulate the full _load_sync return dict to confirm all keys are present."""
    from backend.core.atomistic_to_nadoc import _extract_universe, centroid_offset
    from backend.core.md_metrics import derive_total_ns, parse_log_metrics

    p_order = chain_data["p_order"]
    n_frames = len(universe.trajectory)
    beads_0 = _extract_universe(universe, 0, p_order)
    T = centroid_offset(beads_0, design)

    log_path = generated_gromacs.folder / "prod.log"
    metrics = parse_log_metrics(log_path) if log_path.exists() else None
    total_ns = derive_total_ns(metrics, n_frames) if metrics else None

    result = {
        "n_frames": n_frames,
        "n_p_atoms": len(chain_data["chain_map"]),
        "centroid_T": T,
        "dt_ps": metrics.dt_ps if metrics else None,
        "nstxout_comp": metrics.nstxout_comp if metrics else None,
        "ns_per_day": metrics.ns_per_day if metrics else None,
        "temperature_k": metrics.temperature_k if metrics else None,
        "total_ns": total_ns,
    }

    assert result["n_frames"] > 0
    assert result["n_p_atoms"] > 0
    assert result["centroid_T"] is not None
    if result["dt_ps"] is not None:
        assert result["dt_ps"] > 0
    if result["total_ns"] is not None:
        assert result["total_ns"] > 0
