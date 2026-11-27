"""Approved terminal-T geometry: clearance, root preservation and transport controls."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.ring_piercing import model_piercings
from backend.core.terminal_t_motifs import apply_terminal_t_motifs, two_helix_frame

CASES = json.loads(gzip.decompress((Path(__file__).parent / "data/terminal_t_motif_cases.json.gz").read_bytes()))["cases"]


def fragment(case, monkeypatch, rotation=None, shift=None):
    case = deepcopy(case)
    rotation = np.eye(3) if rotation is None else rotation
    shift = np.zeros(3) if shift is None else shift
    atoms = [NS(**a) for a in case["atoms"]]
    for a in atoms:
        a.x, a.y, a.z = rotation @ [a.x, a.y, a.z] + shift
    frames = {h: {k: np.asarray(v) for k, v in f.items()} for h, f in case["frames"].items()}
    for f in frames.values():
        f["axis_points"] = f["axis_points"] @ rotation.T + shift
        for k in ["axis_tangents", "radial_hats"]:
            f[k] = f[k] @ rotation.T
    strands = [NS(id=s["id"], domains=[NS(**{**x, "direction": NS(value=x["direction"])}) for x in s["domains"]]) for s in case["strands"]]
    connector = NS(**case["connector"])
    design = NS(helices=[NS(id=h, loop_skips=[]) for h in frames], strands=strands,
                extensions=[NS(**e) for e in case["extensions"]],
                crossovers=[NS(id=connector.crossover_id, extra_bases="TT")], forced_ligations=[])
    monkeypatch.setattr("backend.core.junction_topology.crossover_connectors", lambda d: [connector])
    monkeypatch.setattr("backend.core.deformation.deformed_nucleotide_arrays", lambda h, d: frames[h.id])
    return design, atoms, case["bonds"], frames


def positions(atoms):
    return np.array([[a.x, a.y, a.z] for a in atoms])


@pytest.mark.parametrize("case", CASES, ids=["forward", "reverse", "alternate_reverse"])
def test_approved_motif_clears_extensions_and_preserves_root_and_fixed_atoms(case, monkeypatch):
    design, atoms, bonds, _ = fragment(case, monkeypatch)
    before = positions(atoms)
    adjacency = [set() for _ in atoms]
    for i, j in bonds:
        adjacency[i].add(j)
        adjacency[j].add(i)
    roots = []
    for e in design.extensions:
        name = "O3'" if e.end == "five_prime" else "P"
        tip = next(i for i, a in enumerate(atoms) if a.extension_id == e.id and a.name == name)
        root = next(i for i in adjacency[tip] if atoms[i].extension_id != e.id)
        roots.append((root, tip))
    report = apply_terminal_t_motifs(design, atoms, bonds)
    assert len(report) == 1 and report[0]["family"] == case["family"]
    after = positions(atoms)
    fixed = sorted(set(range(len(atoms))) - set(report[0]["moved_atom_serials"]))
    np.testing.assert_array_equal(after[fixed], before[fixed])
    for root, tip in roots:
        assert np.linalg.norm(after[root] - after[tip]) == pytest.approx(.16, abs=2e-5)
    extension_atoms = {i for i, a in enumerate(atoms) if a.extension_id in {e.id for e in design.extensions}}
    for i, j in cKDTree(after).query_pairs(.2):
        if j not in adjacency[i] and not adjacency[i] & adjacency[j]:
            assert not extension_atoms & {i, j}
    hits = model_piercings(NS(atoms=atoms, bonds=bonds), max_report=10000)
    assert not any(extension_atoms & set(h["bond_serials"] + h["ring_serials"]) for h in hits)


@pytest.mark.parametrize("case", CASES, ids=["forward", "reverse", "alternate_reverse"])
def test_placement_is_equivariant_under_rigid_design_motion(case, monkeypatch):
    design, atoms, bonds, _ = fragment(case, monkeypatch)
    apply_terminal_t_motifs(design, atoms, bonds)
    expected = positions(atoms)
    rotation = Rotation.from_euler("xyz", [23, -51, 117], degrees=True).as_matrix()
    shift = np.array([5.2, -3.1, 7.4])
    design, atoms, bonds, _ = fragment(case, monkeypatch, rotation, shift)
    apply_terminal_t_motifs(design, atoms, bonds)
    np.testing.assert_allclose(positions(atoms), expected @ rotation.T + shift, atol=2e-12, rtol=0)


@pytest.mark.parametrize("unsupported", ["long_tail", "other_insert", "other_phase", "nearby_loop", "no_extensions"])
def test_unapproved_motifs_keep_existing_geometry(unsupported, monkeypatch):
    design, atoms, bonds, frames = fragment(CASES[0], monkeypatch)
    if unsupported == "long_tail":
        design.extensions[0].sequence = "TT"
    elif unsupported == "other_insert":
        design.crossovers[0].extra_bases = "AT"
    elif unsupported == "other_phase":
        f = next(iter(frames.values()))
        f["radial_hats"] = f["radial_hats"] @ Rotation.from_euler("z", 30, degrees=True).as_matrix().T
    elif unsupported == "nearby_loop":
        design.helices[0].loop_skips = [NS(bp_index=CASES[0]["connector"]["from_bp"])]
    else:
        design.extensions = []
    before = positions(atoms)
    assert apply_terminal_t_motifs(design, atoms, bonds) == []
    np.testing.assert_array_equal(positions(atoms), before)


def test_two_helix_frame_preserves_handedness_for_both_strand_directions():
    for direction in ["FORWARD", "REVERSE"]:
        frame = two_helix_frame(np.zeros(3), np.array([2.25, 0., 0.]), [0., 0., 1.], direction)
        assert np.linalg.det(frame) == pytest.approx(1.)
        np.testing.assert_allclose(frame.T @ frame, np.eye(3), atol=1e-14)


def test_geometry_override_bypasses_native_motif_placement(monkeypatch):
    from backend.core.models import Design
    from backend.core.atomistic import build_atomistic_model
    calls = []
    monkeypatch.setattr("backend.core.terminal_t_motifs.apply_terminal_t_motifs", lambda *args: calls.append(True))
    build_atomistic_model(Design())
    assert calls == [True]
    for kwargs in [dict(ext_pos_override={}), dict(xb_pos_override={}), dict(apply_design_geometry=False), dict(_terminal_t_motifs=False), dict(_two_base_default=False)]:
        build_atomistic_model(Design(), **kwargs)
    assert calls == [True]
