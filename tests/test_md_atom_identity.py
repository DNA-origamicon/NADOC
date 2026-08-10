"""Synthetic-nucleotide identity used by NAMD atomistic scalar overlays."""

from backend.core.atomistic_to_nadoc import atom_design_ident
import backend.core.md_trajectory as md_trajectory


def test_crossover_extra_base_identity_keeps_unique_rmsf_key():
    assert atom_design_ident(("__xb__", "xo7", 2), "staple") == {
        "strand_id": "staple",
        "helix_id": "__xb__",
        "bp_index": -1,
        "direction": "",
        "copy_k": 0,
        "scalar_key": "__xb__:xo7:2:0",
    }


def test_extension_identity_keeps_tail_index_and_direction():
    assert atom_design_ident(("__ext_tail7", 3, "REVERSE"), "staple") == {
        "strand_id": "staple",
        "helix_id": "__ext_tail7",
        "bp_index": 3,
        "direction": "REVERSE",
        "copy_k": 0,
        "scalar_key": "__ext_tail7:3:REVERSE:0",
    }


def test_loop_copy_identity_keeps_copy_index():
    assert atom_design_ident(("h0", 9, "FORWARD", 2), "scaffold")["copy_k"] == 2


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
