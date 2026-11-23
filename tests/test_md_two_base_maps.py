"""Rigid-transform and periodic-image oracles for measured relative base maps."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.md_two_base_maps import relative_coordinates, ring_frame


def ring():
    theta = np.arange(6)*np.pi/3
    return np.column_stack((np.cos(theta),np.sin(theta),np.zeros(6)))


def test_known_translation_and_rotation_in_first_base_frame():
    a = ring()
    center, axes = ring_frame(a)
    turn = Rotation.from_rotvec([0,0,30],degrees=True).as_matrix()
    b = (a-center) @ axes @ turn.T @ axes.T + center + axes @ [10,20,30]
    assert relative_coordinates(a,b) == pytest.approx([1,2,3,0,0,30],abs=1e-10)


def test_global_rigid_motion_does_not_change_coordinates():
    a = ring(); b = ring() @ Rotation.from_euler('xyz',[20,30,45],degrees=True).as_matrix().T + [4,5,6]
    rotation = Rotation.from_euler('xyz',[80,-20,15],degrees=True).as_matrix()
    assert relative_coordinates(a@rotation.T+12,b@rotation.T+12) == pytest.approx(relative_coordinates(a,b),abs=1e-10)


def test_periodic_wrapped_rings_and_displacement():
    a = ring()+[19.8,10,10]; b = ring()+[21.8,10,10]
    box = np.array([20,20,20,90,90,90])
    assert relative_coordinates(a%20,b%20,box) == pytest.approx(relative_coordinates(a,b),abs=1e-6)


def test_identical_frames_zero_and_degenerate_ring_rejected():
    assert relative_coordinates(ring(),ring()) == pytest.approx([0]*6,abs=1e-12)
    with pytest.raises(ValueError,match='Degenerate'):
        ring_frame(np.zeros((6,3)))


def test_complete_cache_skips_trajectory_and_rekeys_order(tmp_path,monkeypatch):
    import MDAnalysis as mda
    from types import SimpleNamespace
    from backend.core import md_two_base_maps as maps
    topology = tmp_path/'test.psf';topology.touch()
    trajectory = tmp_path/'test.dcd';trajectory.touch()
    design = tmp_path/'design.json';design.write_text('{}')
    xyz = np.vstack([ring(),ring()+[4,0,0]])
    class Frames:
        def __len__(self):
            return 51
        def __iter__(self):
            return iter([SimpleNamespace(positions=xyz,dimensions=None)]*51)
        def close(self):
            pass
    calls=[]
    def universe(*args):
        calls.append(args)
        return SimpleNamespace(trajectory=Frames())
    monkeypatch.setattr(mda,'Universe',universe)
    monkeypatch.setattr(maps,'residue_rings',lambda *args:[np.arange(6),np.arange(6,12)])
    args=(topology,[trajectory],design,tmp_path,['a','b'])
    progress=tmp_path/'progress.json'
    updates=[]
    real_progress=maps.write_progress
    def track(path,done,total):
        updates.append((done,total))
        real_progress(path,done,total)
    monkeypatch.setattr(maps,'write_progress',track)
    first=maps.md_two_base_maps(*args,progress_path=progress)
    assert updates == [(0,51),(25,51),(50,51),(51,51)]
    import json
    assert json.loads(progress.read_text()) == dict(done=51,total=51,percent=100)
    assert first['frames']==51
    assert maps.md_two_base_maps(*args)==first
    assert len(calls)==1
    maps.md_two_base_maps(*args[:-1],['b','a'])
    assert len(calls)==2


def test_progress_reports_measured_fraction_atomically(tmp_path):
    import json
    from backend.core.md_two_base_progress import write_progress
    path=tmp_path/'request.json'
    write_progress(path,25,100)
    assert json.loads(path.read_text())==dict(done=25,total=100,percent=25)
    assert not path.with_suffix('.tmp').exists()
