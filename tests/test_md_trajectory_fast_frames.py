"""Coordinate-only playback preserves DCD identity, imaging and sparse serials."""
import numpy as np
import pytest

from backend.core import md_trajectory as mt


@pytest.mark.parametrize("periodic", [True, False])
def test_prefix_coordinates_match_full_reader_and_atom_records(tmp_path, periodic):
    mda = pytest.importorskip("MDAnalysis")
    u = mda.Universe.empty(8, trajectory=True)
    paths = []
    rng = np.random.default_rng(42)
    for segment in range(2):
        path = tmp_path / f"part{segment}.dcd"
        with mda.Writer(str(path), n_atoms=8) as writer:
            for frame in range(2):
                u.atoms.positions = rng.uniform(0, 50, (8, 3)).astype(np.float32)
                u.dimensions = [50 + frame + segment, 60, 70, 90, 90, 90] if periodic else None
                writer.write(u.atoms)
        paths.append(path)
    u.load_new([str(p) for p in paths])
    heavy = np.array([0, 2, 4, 5])
    reference = np.array([[1., 2., 3.], [2., 3., 4.], [3., 2., 4.]])
    center = reference.mean(axis=0)
    ctx = dict(universe=u, p_order=[("h", i, "F") for i in range(3)],
               dna_p_idx=np.array([0, 2, 4]), heavy_idx=heavy,
               atom_meta=[{"serial": int(i + 1), "element": "C"} for i in heavy],
               centroid_T=np.array([1., -2., 3.]), eq_positions=reference,
               rigid_mask=np.ones(3, dtype=bool), eq_centroid=center,
               eq_centered=reference - center, direct_heavy_layout=None)
    prefix = mt._DcdPrefixChain(paths, 6)
    try:
        for frame in [0, 3, 1, 2]:
            records = mt._extract_md_atoms_frame(ctx, frame)
            expected = np.array([[a[k] for k in ("x", "y", "z")] for a in records])
            u.trajectory[(frame + 1) % 4]
            previous = u.trajectory.frame
            ctx["dcd_prefix"] = prefix
            actual = mt._extract_md_atoms_frame(ctx, frame, positions_only=True)
            np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=0)
            assert u.trajectory.frame == previous  # DNA-only read does not load solvent
            ctx["dcd_prefix"] = None
            np.testing.assert_array_equal(
                mt._extract_md_atoms_frame(ctx, frame, positions_only=True), expected)
    finally:
        prefix.close()
        u.trajectory.close()


def test_positions_only_scatter_keeps_sparse_serials_and_composite_indices(monkeypatch):
    ctx = {"n_frames": 10, "atom_meta": [{"serial": 4}, {"serial": 1}]}
    monkeypatch.setattr(mt, "_build_md_nadoc_ctx", lambda *a, **kw: ctx)
    monkeypatch.setattr(mt, "composite_raw_frame_map", lambda *a: [2, 7])
    seen = []
    def extract(context, frame, *, positions_only):
        assert context is ctx and positions_only
        seen.append(frame)
        return np.array([[frame + 0.123456, -2., 3.], [4., 5., 6.]])
    monkeypatch.setattr(mt, "_extract_md_atoms_frame", extract)
    result = mt.md_frames_atomistic("x.psf", [], "x.pdb", None, [1, -1, 0, 1, 2], positions_only=True)
    assert seen == [2, 7]
    assert set(result) == {"0", "1"}
    for idx, frame in enumerate(seen):
        xyz = np.array(result[str(idx)]).reshape(-1, 3)
        np.testing.assert_array_equal(xyz[[0, 2, 3]], np.zeros((3, 3)))
        np.testing.assert_array_equal(xyz[1], [4, 5, 6])
        np.testing.assert_array_equal(xyz[4], [frame + 0.1235, -2, 3])
