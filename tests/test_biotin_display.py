"""Binding-pocket registration, real spacer connectivity and honest failed fits."""
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.atomistic import build_atomistic_model, atomistic_to_json
from backend.core.biotin_atomistic import CATALOG, RING, SPACER, pocket_transform
from backend.core.gold_strep_dna import build_dna_set, pocket_geometry
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating


def design_with_dna(count=1, dna=1):
    particle = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(10, count_override=count))
    entries = build_dna_set(particle, 'ACGTACGT', dna_per_strep=dna, linker_nm=1.8)
    particle.biotin_dna = [r for r, _, _ in entries]
    return Design(nanoparticles=[particle], helices=[h for _, h, _ in entries], strands=[s for _, _, s in entries])


def test_pockets_match_attachment_geometry_in_every_chain():
    design = design_with_dna()
    p = design.nanoparticles[0]
    for chain in 'ABCD':
        r = p.biotin_dna[0].model_copy(update={'chain': chain})
        m = pocket_transform(p, r)
        ligand = {a['name']: np.array(a['position']) for a in CATALOG['pockets']['A']['atoms']}
        anchor, direction = pocket_geometry(p, chain)
        assert np.allclose(anchor, m[:3, :3] @ ligand['C11'] + m[:3, 3])
        expected = m[:3, :3] @ (ligand['C11'] - ligand['C10'])
        assert np.allclose(direction, expected / np.linalg.norm(expected))


def test_teg_has_real_graph_fixed_ring_and_one_phosphate_connection():
    d = design_with_dna(); model = build_atomistic_model(d)
    assert not model.warnings
    modification = [a for a in model.atoms if a.residue == 'BTE']
    assert len(modification) == 28
    assert {a.name for a in modification} >= {a[0] for a in SPACER}
    assert 'O12' not in {a.name for a in modification}  # amide replaces carboxyl OH
    xyz = np.array([[a.x, a.y, a.z] for a in model.atoms])
    modified = {a.serial for a in modification}
    bonds = [(i, j) for i, j in model.bonds if i in modified or j in modified]
    assert len(bonds) == 30  # 28 new atoms, two ring closures, one DNA bond
    assert all(.115 < np.linalg.norm(xyz[i] - xyz[j]) < .195 for i, j in bonds)
    external = [(i,j) for i,j in bonds if (i in modified) != (j in modified)]
    assert len(external) == 1
    i,j = external[0]
    assert model.atoms[i].name == 'O4T' and model.atoms[j].name == 'P'
    direction = xyz[i] - xyz[j]
    for a in model.atoms:
        if a.seq_num == 1 and a.name in ("O5'", 'OP1', 'OP2'):
            v = xyz[a.serial] - xyz[j]
            angle = np.rad2deg(np.arccos(np.dot(v, direction) / np.linalg.norm(v) / np.linalg.norm(direction)))
            assert 90 < angle < 130
    matrix = pocket_transform(d.nanoparticles[0], d.nanoparticles[0].biotin_dna[0])
    for a in modification:
        if a.name in RING:
            original = next(x for x in CATALOG['pockets']['A']['atoms'] if x['name'] == a.name)
            assert np.allclose(xyz[a.serial], matrix[:3,:3] @ original['position'] + matrix[:3,3])


def test_unreachable_keeps_atom_serials_but_does_not_invent_a_bond():
    d = design_with_dna(); baseline = build_atomistic_model(d)
    h = d.helices[0]
    h.axis_start.x += 20; h.axis_end.x += 20
    model = build_atomistic_model(d)
    assert len(model.atoms) == len(baseline.atoms)
    assert [a.name for a in model.atoms] == [a.name for a in baseline.atoms]
    assert 'unconnected' in atomistic_to_json(model)['warnings'][0]
    modified = {a.serial for a in model.atoms if a.residue == 'BTE'}
    assert not any((i in modified) != (j in modified) for i,j in model.bonds)


def test_hidden_or_excluded_dna_does_not_leave_orphan_ligands():
    d = design_with_dna()
    assert not build_atomistic_model(d, exclude_helix_ids={d.helices[0].id}).atoms
    d.nanoparticles[0].visible = False
    assert not any(a.residue == 'BTE' for a in build_atomistic_model(d).atoms)


def test_multiple_tetramers_and_rigid_motion_preserve_ligand_coordinates():
    d = design_with_dna(count=2, dna=2)
    before = build_atomistic_model(d)
    assert sum(a.residue == 'BTE' for a in before.atoms) == 4 * 28
    r = Rotation.from_rotvec([.2,.4,-.3]).as_matrix(); t = np.array([11.,-4.,7.])
    m = np.eye(4); m[:3,:3] = r; m[:3,3] = t
    from backend.core.nanoparticle import replace_gold_nanosphere
    p = d.nanoparticles[0]
    moved = replace_gold_nanosphere(d, p.id, pose=m.ravel().tolist())
    after = build_atomistic_model(moved)
    b = np.array([[a.x,a.y,a.z] for a in before.atoms if a.residue == 'BTE'])
    a = np.array([[a.x,a.y,a.z] for a in after.atoms if a.residue == 'BTE'])
    assert np.allclose(a, b @ r.T + t, atol=2e-5)


def test_display_descriptor_treats_biotin_as_nonrigid_not_a_dna_residue():
    from backend.core.atomistic import atomistic_display_bundle
    bundle = atomistic_display_bundle(design_with_dna())
    biotin = {a['serial'] for a in bundle['atoms'] if a['residue'] == 'BTE'}
    assert len(biotin) == 28
    assert biotin <= set(bundle['nonrigid_serials'])


def test_surface_includes_the_same_biotin_atoms():
    from backend.core.atomistic import surface_atom_cloud
    d = design_with_dna()
    model = build_atomistic_model(d, fast_bridges=True)
    expected = np.array([[a.x,a.y,a.z] for a in model.atoms if a.residue == 'BTE'])
    positions, radii, strands, keys = surface_atom_cloud(d)
    assert np.allclose(positions[-28:], expected, atol=2e-6)
    assert len(positions) == len(radii) == len(strands) == len(keys)
