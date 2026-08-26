"""Synthetic-nucleotide identity used by NAMD atomistic scalar overlays."""

from types import SimpleNamespace

from backend.core.atomistic_to_nadoc import atom_design_ident
import backend.core.md_trajectory as md_trajectory
from backend.core.surface import _nuc_key
import numpy as np


def test_crossover_extra_base_identity_keeps_unique_rmsf_key():
    assert atom_design_ident(("__xb__", "xo7", 2), "staple") == {
        "strand_id": "staple",
        "helix_id": "__xb__",
        "bp_index": -1,
        "direction": "",
        "copy_k": 0,
        "scalar_key": "__xb__:xo7:2:0",
        "base_key": "__xb__:xo7:2",
    }


def test_extension_identity_keeps_tail_index_and_direction():
    assert atom_design_ident(("__ext_tail7", 3, "REVERSE"), "staple") == {
        "strand_id": "staple",
        "helix_id": "__ext_tail7",
        "bp_index": 3,
        "direction": "REVERSE",
        "copy_k": 0,
        "scalar_key": "__ext_tail7:3:REVERSE:0",
        "base_key": "__ext_tail7:3:REVERSE",
    }


def test_loop_copy_identity_keeps_copy_index():
    assert atom_design_ident(("h0", 9, "FORWARD", 2), "scaffold")["copy_k"] == 2


def test_surface_owner_prefers_full_synthetic_scalar_key():
    atom = SimpleNamespace(
        scalar_key="__xb__:xo7:2:0",
        helix_id="__xb__",
        bp_index=-1,
        direction="",
    )
    assert _nuc_key(atom) == "__xb__:xo7:2:0"


def test_direct_heavy_pbc_preserves_recorded_intra_residue_coordinates():
    """Atomistic display may choose periodic images, but must never stamp/rebuild atoms."""
    raw = np.array(
        [
            [9.8, 1.0, 2.0],
            [9.9, 1.1, 2.2],
            [0.2, 1.2, 2.4],
            [0.4, 1.3, 2.5],
        ]
    )
    layout = {
        "heavy_res_group": np.array([0, 0, 1, 1]),
        "residue_anchor_rows": np.array([0, 2]),
        "residue_segment_ids": np.array(["S", "S"], dtype=object),
        "heavy_segment_group": np.array([0, 0, 0, 0]),
        "p_heavy_rows": np.array([0, 2]),
        "p_segment_group": np.array([0, 0]),
        "n_segments": 1,
    }
    placed = md_trajectory._direct_heavy_pre_positions(
        raw,
        np.array([[4.8, 1.0, 2.0], [5.2, 1.2, 2.4]]),
        np.array([10.0, 10.0, 10.0]),
        np.array([-5.0, 0.0, 0.0]),
        layout,
    )
    np.testing.assert_allclose(placed[1] - placed[0], raw[1] - raw[0])
    np.testing.assert_allclose(placed[3] - placed[2], raw[3] - raw[2])
    np.testing.assert_allclose(placed[:, 0], [4.8, 4.9, 5.2, 5.4])


def test_atomistic_flex_mean_positions_every_synthetic_residue_by_serial(monkeypatch):
    """Crossover/extension atoms must be averaged directly, never parent-key projected."""
    ctx = {
        "n_frames": 2,
        "atom_meta": [
            {"serial": 1, "scalar_key": "__xb__:xo7:2:0"},
            {"serial": 4, "scalar_key": "__ext_tail7:3:REVERSE:0"},
        ],
    }
    frames = [
        [
            {"serial": 1, "x": 1.0, "y": 2.0, "z": 3.0},
            {"serial": 4, "x": 10.0, "y": 20.0, "z": 30.0},
        ],
        [
            {"serial": 1, "x": 3.0, "y": 4.0, "z": 5.0},
            {"serial": 4, "x": 14.0, "y": 24.0, "z": 34.0},
        ],
    ]
    monkeypatch.setattr(md_trajectory, "_build_md_nadoc_ctx", lambda *a, **k: ctx)
    monkeypatch.setattr(
        md_trajectory, "_extract_md_atoms_frame", lambda _ctx, idx: frames[idx]
    )

    result = md_trajectory.md_rmsf_atomistic(
        "job.psf", [("prod", "production", "prod.dcd")], "job.pdb", "design"
    )
    flat = result["atomistic"]
    assert flat[3:6] == [2.0, 3.0, 4.0]  # crossover insert, serial 1
    assert flat[12:15] == [12.0, 22.0, 32.0]  # extension atom, serial 4
