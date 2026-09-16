"""Playback acceleration preserves sparse identity and recorded geometry."""
from types import SimpleNamespace
import struct

import numpy as np


def test_dna_tables_preserve_serials_termini_and_bonds(tmp_path, monkeypatch):
    from backend.core import atomistic_to_nadoc as mapping
    from backend.core.md_playback_context import _build_tables

    psf = tmp_path / 'a.psf'
    # Two bases and solvent: sparse heavy serials, phosphate-free 5' terminus.
    names = ["O5'", 'H5', "C1'", 'N1', 'C2', 'N3', 'C4', 'C5', 'C6',
             'P', "C1'", 'N1', 'C2', 'N3', 'C4', 'C5', 'C6', 'OH2']
    psf.write_text('PSF\n18 !NATOM\n' + ''.join(
        f'{i+1} A {1 if i<9 else 2} {"DA" if i<17 else "TIP3"} {n} C 0 12 0\n'
        for i, n in enumerate(names)) + '\n3 !NBOND\n1 2 1 3 10 11\n')
    keys = [('h', 0, 'FORWARD'), ('h', 1, 'FORWARD')]
    monkeypatch.setattr(mapping, 'load_segid_chain_map', lambda _: {'A':'A'})
    monkeypatch.setattr(mapping, 'build_namd_coarse_reference', lambda *_, **kw: ({('A',i+1):k for i,k in enumerate(keys)}, {}))
    monkeypatch.setattr(mapping, 'build_active_design_reference', lambda _: dict.fromkeys(keys, np.zeros(3)))
    monkeypatch.setattr(mapping, 'md_rigid_reference_from_map', lambda *_: (np.zeros((3,3)), np.ones(3,bool), np.ones(3,bool)))
    monkeypatch.setattr(mapping, 'md_snap_mask', lambda *_: np.ones(3,bool))
    design = SimpleNamespace(strands=[SimpleNamespace(id='strand')], extensions=[], crossovers=[])
    ctx = _build_tables(psf, 'unused', design)
    assert ctx['heavy_idx'].tolist() == [0] + list(range(2,17))
    assert ctx['heavy_bonds'].tolist() == [[0,2],[9,10]]
    assert ctx['term_specs'] == [(keys[0],0,2,0)]
    assert ctx['p_order'] == [keys[1]]
    assert {m['strand_id'] for m in ctx['atom_meta']} == {'strand'}
    assert ctx['full_base_layout'][0].tolist() == [9,0]


def test_binary_frames_keep_float64_coordinates_and_composite_indices(monkeypatch):
    from backend.core import md_trajectory as mt
    from backend.core.md_atom_frames_bin import md_frames_atomistic_bin
    serials = np.array([1,4])
    coords = np.array([[1/3, 1e-12, -17.00123456789], [9.3, 0, 2]])
    monkeypatch.setattr(mt, '_build_playback_ctx', lambda *_a, **_k: {'heavy_idx':serials})
    monkeypatch.setattr(mt, 'composite_raw_frame_map', lambda *_: [0,20,40])
    seen=[]
    def extract(ctx, frame, **kw):
        seen.append(frame)
        return coords
    monkeypatch.setattr(mt, '_extract_md_atoms_frame', extract)
    data = md_frames_atomistic_bin('a', [('a','md','dcd')], 'b', None, [2,0,2,-1,8], stride=20)
    assert struct.unpack_from('<6I', data) == (0x4D444146,2,2,5,2,0)
    assert np.frombuffer(data, '<u4', count=2, offset=24).tolist() == [1,4]
    assert seen == [0,40]
    assert struct.unpack_from('<I',data,32)[0] == 0
    np.testing.assert_array_equal(np.frombuffer(data, '<f8', count=6, offset=40).reshape(-1,3),coords)
    assert struct.unpack_from('<I',data,32+8+2*24)[0] == 2


def test_read_ahead_preserves_order_and_restores_reader_after_error():
    from backend.core.md_read_ahead import read_ahead
    class Reader:
        def frame(self, i):
            return np.array([i, i+1], dtype=np.float32)
    original = Reader()
    ctx = {'dcd_prefix': original}
    try:
        with read_ahead(ctx, [0,20,40]):
            assert ctx['dcd_prefix'] is not original
            for i in [0,20,40]:
                np.testing.assert_array_equal(ctx['dcd_prefix'].frame(i), original.frame(i))
            raise ValueError('cancel')
    except ValueError:
        pass
    assert ctx['dcd_prefix'] is original


def test_binary_topology_preserves_sparse_serial_and_all_color_identity(monkeypatch):
    from backend.core import md_trajectory as mt
    from backend.core.md_atom_model_bin import md_atomistic_model_bin
    import json
    meta=[dict(element='C',name='C6',strand_id='s',helix_id='h',bp_index=7,
               direction='FORWARD',copy_k=2,base_key='h:7:FORWARD:2',scalar_key='')]
    ctx=dict(atom_meta=meta,heavy_idx=np.array([19]),heavy_bonds=np.array([[19,19]]))
    monkeypatch.setattr(mt,'_build_playback_ctx',lambda *_a,**_k:ctx)
    coords=np.array([[1/3,2.,3.]])
    monkeypatch.setattr(mt,'_extract_md_atoms_frame',lambda *_a,**_k:coords)
    buf=md_atomistic_model_bin('a',[('n','s','d')],'b',None)
    magic,version,n,_=struct.unpack_from('<4I',buf)
    assert (magic,version)==(0x4D44414D,1)
    h=json.loads(buf[16:16+n]); start=16+(n+7)//8*8
    cols={c['name']:np.frombuffer(buf,c['dtype'],count=c['count'],offset=start+c['offset']) for c in h['columns']}
    assert h['n_serials']==20
    assert cols['serial'].tolist()==[19]
    assert cols['copyK'].tolist()==[2]
    assert h['baseKeyTable'][cols['baseKeyIdx'][0]]=='h:7:FORWARD:2'
    assert h['nameTable'][cols['nameIdx'][0]]=='C6'
    assert cols['x'][0]==1/3


def test_interrupted_dcd_uses_complete_frames_not_stale_header(tmp_path):
    from backend.core.dcd_fast import write_trajectory
    from backend.core.md_trajectory import _DcdPrefixFile, composite_raw_frame_map
    path=tmp_path/'interrupted.dcd'
    frames=[np.arange(12,dtype=np.float32).reshape(4,3)+i for i in range(3)]
    write_trajectory(path,4,iter(frames),3)
    with path.open('r+b') as fh:
        fh.seek(8);fh.write(struct.pack('<i',1))
        fh.seek(0,2);fh.write(b'partial')
    prefix=_DcdPrefixFile(path,2)
    try:
        assert prefix.n_frames==3
        np.testing.assert_array_equal(prefix.frame(2)[0],frames[2][:2])
        assert composite_raw_frame_map([('production','md',path)],stride=2)==[0,2]
    finally:
        prefix.close()


def test_metadata_cache_keys_manifest_files_and_keeps_frame_state_private(tmp_path, monkeypatch):
    from backend.core import md_playback_context as cache
    from backend.core import md_trajectory as mt
    for name in ('a.psf','a.pdb','manifest.json'):
        (tmp_path/name).write_text('original')
    monkeypatch.setenv('NADOC_MD_PLAYBACK_CACHE_DIR',str(tmp_path/'cache'))
    class Prefix:
        def __init__(self,*args): self.ends=np.array([3])
    monkeypatch.setattr(mt,'_DcdPrefixChain',Prefix)
    built=[]
    def build(*args):
        built.append(True)
        return {'prefix_atoms':1,'marker':len(built)}
    monkeypatch.setattr(cache,'_build_tables',build)
    design=SimpleNamespace(model_dump=lambda **kw:{'name':'test'})
    def get(): return cache.playback_context(tmp_path/'a.psf',['a.dcd'],tmp_path/'a.pdb',design)
    first=get();first['R_prev']='old frame'
    second=get()
    assert second['R_prev'] is None and second['marker']==1
    (tmp_path/'manifest.json').write_text('changed mapping')
    assert get()['marker']==2
