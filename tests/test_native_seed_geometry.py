"""Native viewing and NAMD preparation must start from identical heavy atoms."""
from pathlib import Path
import numpy as np
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_cache import build_atomistic_model_cached, clear_atomistic_cache
from backend.core.models import Design
from backend.core.namd_topology import _write_segment_pdbs


def test_native_seed_matches_viewport_and_psfgen_input(tmp_path):
    design = Design.from_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    viewed = build_atomistic_model(design, fast_bridges=True)
    seed = build_atomistic_model(design)
    coords = lambda m: np.array([(a.x, a.y, a.z) for a in m.atoms])
    np.testing.assert_array_equal(coords(seed), coords(viewed))
    clear_atomistic_cache()
    try:
        assert build_atomistic_model_cached(design) is build_atomistic_model_cached(design, fast_bridges=True)
    finally:
        clear_atomistic_cache()
    a, b = tmp_path/'default', tmp_path/'viewed'
    a.mkdir(); b.mkdir()
    assert _write_segment_pdbs(design, a)[1] == _write_segment_pdbs(design, b, viewed)[1]
    assert {p.name:p.read_bytes() for p in a.iterdir()} == {p.name:p.read_bytes() for p in b.iterdir()}


def test_override_default_preserves_reconstruction():
    design = Design.from_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    default = build_atomistic_model(design, nuc_pos_override={})
    explicit = build_atomistic_model(design, nuc_pos_override={}, fast_bridges=False)
    assert [(a.x,a.y,a.z) for a in default.atoms] == [(a.x,a.y,a.z) for a in explicit.atoms]


def test_multibase_tail_display_preserves_physical_seed_bonds():
    from backend.core.models import StrandExtension
    design = Design.from_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    design.extensions = [StrandExtension(strand_id=design.strands[1].id,
                                        end="three_prime", sequence="TTT")]
    viewed = build_atomistic_model(design, fast_bridges=True)
    seed = build_atomistic_model(design)
    assert [(a.x,a.y,a.z) for a in viewed.atoms] == [(a.x,a.y,a.z) for a in seed.atoms]
    atoms = {a.serial:a for a in seed.atoms}
    lengths = [np.linalg.norm(np.array((atoms[a].x,atoms[a].y,atoms[a].z)) -
                              np.array((atoms[b].x,atoms[b].y,atoms[b].z)))*10
               for a,b in seed.bonds if {atoms[a].name,atoms[b].name} == {"O3'", "P"}
               and (atoms[a].extension_id or atoms[b].extension_id)]
    assert len(lengths) == 3
    assert all(1.5 <= v <= 3.2 for v in lengths)


def test_explicit_physical_interpolation_is_preserved(monkeypatch):
    from backend.core import atomistic
    from backend.core.models import StrandExtension
    design = Design.from_json(Path('Examples/2hb_xover_val.nadoc').read_text())
    design.extensions = [StrandExtension(strand_id=design.strands[1].id,
                                        end="three_prime", sequence="TTT")]
    def unexpected_solver(*args, **kwargs):
        raise AssertionError("Physical interpolation must not invoke the native tail solver")
    monkeypatch.setattr(atomistic, '_minimize_backbone_bridge', unexpected_solver)
    build_atomistic_model(design, nuc_pos_override={}, fast_bridges=True)
