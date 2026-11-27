"""Reviewed forced-TT/O3 geometry, transport and scope regressions."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.forced_tt_motifs import apply_forced_tt_motifs

CASES = json.loads(gzip.decompress((Path(__file__).parent / "data/forced_tt_motif_cases.json.gz").read_bytes()))["cases"]


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
    c = NS(**case["connector"])
    d = NS(helices=[NS(id=h, loop_skips=[]) for h in frames], strands=[], extensions=[],
           forced_ligations=[NS(id=c.crossover_id, extra_bases="TT")])
    monkeypatch.setattr("backend.core.junction_topology.crossover_connectors", lambda d: [c])
    monkeypatch.setattr("backend.core.deformation.deformed_nucleotide_arrays", lambda h, d: frames[h.id])
    return d, atoms, case["bonds"], frames, c


def positions(atoms):
    return np.array([[a.x, a.y, a.z] for a in atoms])


@pytest.mark.parametrize("case", CASES)
def test_default_reproduces_reviewed_coordinates_and_preserves_fixed_atoms(case, monkeypatch):
    d, atoms, bonds, _, _ = fragment(case, monkeypatch)
    before = positions(atoms)
    report = apply_forced_tt_motifs(d, atoms, bonds)
    assert len(report) == 1
    after = positions(atoms)
    np.testing.assert_allclose(after[case["mobile"]], case["expected_positions"], atol=1e-12, rtol=0)
    fixed = sorted(set(range(len(atoms))) - set(case["mobile"]))
    np.testing.assert_array_equal(before[fixed], after[fixed])
    c3, o3, p, last_o3, exit_p = case["roots"]
    for a, b, length in [(c3, o3, .1433), (o3, p, .16), (last_o3, exit_p, .16)]:
        assert np.linalg.norm(after[a] - after[b]) == pytest.approx(length, abs=1e-12)


@pytest.mark.parametrize("case", CASES)
def test_rigid_motion_and_junction_identifiers_do_not_change_placement(case, monkeypatch):
    rotation = Rotation.from_euler("xyz", [23, -51, 117], degrees=True).as_matrix()
    shift = np.array([5.2, -3.1, 7.4])
    d, atoms, bonds, _, c = fragment(case, monkeypatch, rotation, shift)
    for a in atoms:
        if a.crossover_id == c.crossover_id:
            a.crossover_id = "unrelated-document-junction"
    c.crossover_id = d.forced_ligations[0].id = "unrelated-document-junction"
    assert len(apply_forced_tt_motifs(d, atoms, bonds)) == 1
    np.testing.assert_allclose(positions(atoms)[case["mobile"]], np.array(case["expected_positions"]) @ rotation.T + shift, atol=2e-12, rtol=0)


@pytest.mark.parametrize("unsupported", ["standard", "non_tt", "forward", "phase", "separation", "loop", "extension"])
def test_other_motifs_keep_their_existing_geometry(unsupported, monkeypatch):
    d, atoms, bonds, frames, c = fragment(CASES[0], monkeypatch)
    if unsupported == "standard":
        d.forced_ligations = []
    elif unsupported == "non_tt":
        d.forced_ligations[0].extra_bases = "AT"
    elif unsupported == "forward":
        c.from_dir, c.to_dir = "FORWARD", "REVERSE"
    elif unsupported == "phase":
        frames[c.from_helix]["radial_hats"] *= -1
    elif unsupported == "separation":
        frames[c.to_helix]["axis_points"] += [3., 0., 0.]
    elif unsupported == "loop":
        d.helices[0].loop_skips = [NS(bp_index=c.from_bp)]
    else:
        d.strands = [NS(id="tail", domains=[NS(helix_id=c.from_helix, start_bp=c.from_bp, end_bp=c.from_bp)])]
        d.extensions = [NS(strand_id="tail", sequence="T", end="five_prime")]
    before = positions(atoms)
    assert apply_forced_tt_motifs(d, atoms, bonds) == []
    np.testing.assert_array_equal(positions(atoms), before)


def test_builder_default_and_physical_override_controls(monkeypatch):
    from backend.core.models import Design
    from backend.core.atomistic import build_atomistic_model
    calls = []
    monkeypatch.setattr("backend.core.forced_tt_motifs.apply_forced_tt_motifs", lambda *args: calls.append(True))
    build_atomistic_model(Design())
    assert calls == [True]
    for kwargs in [dict(_forced_tt_motifs=False), dict(_two_base_default=False), dict(apply_design_geometry=False),
                   dict(nuc_pos_override={}), dict(nuc_frame_override={}), dict(axis_override={}),
                   dict(frame_override={}), dict(xb_pos_override={}), dict(ext_pos_override={})]:
        build_atomistic_model(Design(), **kwargs)
    assert calls == [True]
