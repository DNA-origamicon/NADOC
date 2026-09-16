"""Independent measured-ring oracles, including a base split by a periodic face."""
import numpy as np

from backend.core.md_base_frames import measured_base_frames


def test_rotated_periodic_ring_centers_and_planes_include_terminal_anchor():
    # Two hexagons, one anchored by P and one by O5'. The first straddles x=10.
    theta = np.arange(6) * np.pi / 3
    ring = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(6)]) * 0.15
    anchors = np.array([[9.9, 2, 1], [2, 3, 4]])
    centers = anchors + [0.2, 0.3, 0.1]
    raw = np.vstack([anchors, ring + centers[0], ring + centers[1]]) % 10
    rotation = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])
    translation = np.array([5., 6., 7.])
    aligned = anchors @ rotation.T + translation
    got, planes = measured_base_frames(raw, np.array([0, 1]),
        [(np.array([0, 1]), np.arange(2, 14).reshape(2, 6))],
        aligned, rotation, np.array([10., 10., 10.]))
    np.testing.assert_allclose(got, centers @ rotation.T + translation, atol=1e-12)
    np.testing.assert_allclose(np.abs(planes), [[1, 0, 0], [1, 0, 0]], atol=1e-12)


def test_full_frame_extracts_real_terminal_ring_and_same_display_rotation(monkeypatch):
    import MDAnalysis as mda
    from backend.core import md_trajectory as mt

    u = mda.Universe.empty(14, n_residues=2,
        atom_resindex=[0] * 7 + [1] * 7, trajectory=True)
    u.add_TopologyAttr('names', ['P','N1','C2','N3','C4','C5','C6',
                               "O5'",'N1','C2','N3','C4','C5','C6'])
    t = np.arange(6) * np.pi / 3
    ring = np.column_stack([np.cos(t), np.sin(t), np.zeros(6)])
    u.atoms.positions = np.vstack([[0,0,0], ring + [3,0,0],
                                  [0,10,0], ring + [3,10,0]])
    ctx = {'universe':u, 'dna_p_idx':np.array([0]),
           'term_specs':[(('h',0,'R'),7,8,0)]}
    rotation = np.array([[0.,0.,1.],[0.,1.,0.],[-1.,0.,0.]])
    def extract(ctx, idx, *, with_termini, rotation_out):
        rotation_out['R_align'] = rotation
        return np.array([[0.,0.,0.]]), np.array([[0.,0.,-1.]]), np.array([[0.,1.,0.]]), np.array([[0.,0.,-1.]])
    monkeypatch.setattr(mt, '_extract_md_nadoc_frame', extract)
    out = mt._extract_md_full_frame(ctx, 0)
    assert out.shape == (2,12)
    np.testing.assert_allclose(out[:,9:], [[0,0,-.3],[0,1,-.3]], atol=1e-7)
    np.testing.assert_allclose(abs(out[:,6:9]), [[1,0,0],[1,0,0]], atol=1e-7)
