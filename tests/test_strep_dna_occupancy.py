"""Exact pocket occupancy, native geometry, atomic edits and full hybrid export."""

import json
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.api import state, doc_context
from backend.api.main import app
from backend.api.crud import _geometry_for_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import nucleotide_positions_arrays
from backend.core.gold_strep_dna import (
    build_dna_set,
    pocket_geometry,
    validate_fixed_core_design,
)
from backend.core.models import BiotinDNA, Design, Nanoparticle
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.streptavidin import build_streptavidin_coating


def coated(mode="adsorption", count=3):
    return Nanoparticle(
        diameter_nm=10,
        coating=build_streptavidin_coating(10, mode=mode, count_override=count),
    )


def occupied(mode="adsorption", count=3, dna=2):
    p = coated(mode, count)
    entries = build_dna_set(p, "ACGT" * 4, dna_per_strep=dna)
    p.biotin_dna = [r for r, _, _ in entries]
    p.oxdna_fixed_core = True
    return Design(
        nanoparticles=[p],
        helices=[h for _, h, _ in entries],
        strands=[s for _, _, s in entries],
    )


@pytest.mark.parametrize(
    "mode,count,dna",
    [
        ("adsorption", 1, 4),
        ("biotin_tether", 1, 3),
        ("adsorption", 3, 2),
        ("adsorption", 7, 1),
    ],
)
def test_exact_occupancy_native_geometry_and_clearance(mode, count, dna):
    d = occupied(mode, count, dna)
    p = d.nanoparticles[0]
    assert len(p.biotin_dna) == len(p.coating.poses) * dna
    assert len({(r.tetramer_index, r.chain) for r in p.biotin_dna}) == len(p.biotin_dna)
    if mode == "biotin_tether":
        assert all(r.chain != "A" for r in p.biotin_dna)
    xyz = np.array(
        [[a.x, a.y, a.z] for a in p.coating.protein.atoms if a.res_name != "BTN"]
    )
    cloud = np.vstack(
        [xyz @ m.to_array()[:3, :3].T + m.to_array()[:3, 3] for m in p.coating.poses]
    )
    tree = cKDTree(cloud)
    all_points = []
    for r, h in zip(p.biotin_dna, d.helices):
        frames = nucleotide_positions_arrays(h)
        b, base = frames["positions"][::2], frames["base_positions"][::2]
        axis = h.axis_end.to_array() - h.axis_start.to_array()
        axis /= np.linalg.norm(axis)
        assert np.allclose(np.diff(b, axis=0) @ axis, BDNA_RISE_PER_BP)
        radial = b - frames["axis_points"][::2]
        assert np.allclose(np.linalg.norm(radial, axis=1), 1.0)
        assert np.allclose(
            np.sum(radial[:-1] * radial[1:], axis=1), np.cos(h.twist_per_bp_rad)
        )
        anchor, exit_axis = pocket_geometry(p, r.chain, r.tetramer_index)
        assert np.allclose(b[0], anchor + r.linker_nm * exit_axis)
        # Independent, finer sampling of backbone/base segments than the placer.
        start = np.vstack([b[:-1], b])
        end = np.vstack([b[1:], base])
        points = (
            start[:, None, :]
            + np.linspace(0, 1, 30)[None, :, None] * (end - start)[:, None, :]
        ).reshape(-1, 3)
        assert np.linalg.norm(points, axis=1).min() >= 5.45
        assert tree.query(points)[0].min() >= 0.45
        for other in all_points:
            assert cKDTree(other).query(points)[0].min() >= 0.75
        all_points.append(points)
    validate_fixed_core_design(Design.model_validate_json(d.model_dump_json()))


def test_rotation_preserves_all_native_beads_and_attachment_ends():
    d = occupied(count=2, dna=2)
    p = d.nanoparticles[0]
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler("xyz", [70, 35, 119], degrees=True).as_matrix()
    matrix[:3, 3] = [5, -2, 3]
    moved = replace_gold_nanosphere(d, p.id, pose=matrix.ravel().tolist())
    for old, new, record in zip(d.helices, moved.helices, p.biotin_dna):
        before = nucleotide_positions_arrays(old)["positions"]
        after = nucleotide_positions_arrays(new)["positions"]
        assert np.allclose(after, before @ matrix[:3, :3].T + matrix[:3, 3])
        a, v = pocket_geometry(
            moved.nanoparticles[0], record.chain, record.tetramer_index
        )
        assert np.allclose(after[0], a + record.linker_nm * v)


def test_saved_legacy_record_and_invalid_occupancy():
    assert BiotinDNA(strand_id="s", helix_id="h", chain="C").tetramer_index == 0
    d = occupied(count=2, dna=2)
    d.nanoparticles[0].biotin_dna[0].tetramer_index = 5
    with pytest.raises(ValueError, match="missing streptavidin"):
        validate_fixed_core_design(d)
    d = occupied(count=1, dna=2)
    d.nanoparticles[0].biotin_dna[1].chain = d.nanoparticles[0].biotin_dna[0].chain
    with pytest.raises(ValueError, match="same streptavidin pocket"):
        validate_fixed_core_design(d)


def test_extended_seed_keeps_native_attachment_and_preserves_legacy_convention():
    from backend.physics.oxdna_nanoparticle import seed_fixed_dna
    from backend.core.constants import NM_TO_OXDNA

    d = occupied(count=1, dna=1)
    h = d.helices[0]
    frames = nucleotide_positions_arrays(h)
    resolved = {(h.id, i, 'FORWARD'): {} for i in range(h.length_bp)}
    output = seed_fixed_dna(d, resolved)
    points = np.array([n['backbone_position'] for n in output.values()])
    assert np.allclose(points[0], frames['positions'][0])
    assert np.allclose(np.linalg.norm(np.diff(points, axis=0), axis=1), .7564/NM_TO_OXDNA)
    d.nanoparticles[0].biotin_dna[0].placement_version = 1
    legacy = seed_fixed_dna(d, resolved)
    assert np.allclose(next(iter(legacy.values()))['backbone_position'], h.axis_start.to_array())


def test_api_coating_first_exact_counts_undo_redo_and_atomic_failure():
    doc_context.set_current_doc(None)
    p = Nanoparticle(diameter_nm=10)
    state.set_design(Design(nanoparticles=[p]))
    client = TestClient(app)
    url = f"/api/design/nanoparticles/{p.id}"
    try:
        body = {"sequence": "ACGT" * 4, "dna_per_strep": 2}
        before = state.get_design().model_dump_json()
        assert client.post(url + "/biotin-dna", json=body).status_code == 422
        assert state.get_design().model_dump_json() == before
        assert (
            client.patch(url, json={"coating": {"count_override": 3}}).status_code
            == 200
        )
        for invalid in (0, 5, 1.5, True):
            assert (
                client.post(
                    url + "/biotin-dna", json={**body, "dna_per_strep": invalid}
                ).status_code
                == 422
            )
        assert (
            client.post(url + "/biotin-dna", json={**body, "pocket": "B"}).status_code
            == 422
        )
        assert client.post(url + "/biotin-dna", json=body).status_code == 200
        assert len(state.get_design().strands) == 6
        assert client.post(url + "/biotin-dna", json=body).status_code == 422
        assert (
            client.patch(url, json={"coating": {"count_override": 1}}).status_code
            == 409
        )
        assert client.post("/api/design/undo").status_code == 200
        assert (
            not state.get_design().strands
            and len(state.get_design().nanoparticles[0].coating.poses) == 3
        )
        assert client.post("/api/design/redo").status_code == 200
        assert len(state.get_design().strands) == 6
        assert client.delete(url + "/biotin-dna").status_code == 200
        assert not state.get_design().strands
        # An enclosing obstacle makes every linker impossible. No partial history.
        blocked = state.get_design().model_copy(deep=True)
        blocked.nanoparticles.append(Nanoparticle(diameter_nm=100))
        state.set_design(blocked)
        before = state.get_design().model_dump_json()
        result = client.post(url + "/biotin-dna", json=body)
        assert (
            result.status_code == 422
            and "Nothing was attached" in result.json()["detail"]
        )
        assert state.get_design().model_dump_json() == before
    finally:
        state.close_session()


@pytest.mark.slow
@pytest.mark.oxdna
@pytest.mark.parametrize("backend", ["CPU", "CUDA"])
def test_multiple_coatings_and_dna_reach_native_engine(tmp_path, backend):
    from backend.core.oxdna_runner import (
        find_oxdna,
        oxdna_supports_cuda,
        prepare_oxdna_job,
    )
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages, render_stage_input

    binary = find_oxdna()
    if not binary:
        pytest.skip("Native oxDNA required")
    if backend == "CUDA" and not oxdna_supports_cuda(binary):
        pytest.skip("CUDA oxDNA required")
    d = occupied(count=3, dna=2)
    specs = build_relaxation_stages(
        mc_steps=10, md_relax_steps=100, equil_steps=100, backend=backend, protein=True
    )
    job = new_oxdna_job(design_name="occupancy", stages=[s.to_status() for s in specs])
    prepare_oxdna_job(d, _geometry_for_design(d), job, tmp_path, specs)
    jd = job.job_dir(tmp_path)
    manifest = json.loads((jd / "nanoparticles.json").read_text())
    assert len(manifest["particles"][0]["protein_attachment_ids"]) == 3
    assert len(manifest["particles"][0]["dna"]) == 6
    for file in ("forces.txt", "equil_forces.txt"):
        force = (jd / file).read_text()
        assert force.count("type = mutual_trap") == 12
        assert force.count("type = trap") == 9
        assert force.count("type = repulsive_sphere_moving") == 1
    conf = jd / "conf.dat"
    for spec in specs:
        folder = jd / spec.name
        folder.mkdir()
        (folder / "input").write_text(
            render_stage_input(
                spec,
                str(jd / "topology.top"),
                str(conf),
                str(jd / (spec.forces_file or "forces.txt")),
                str(jd / "anm.par"),
            )
        )
        run = subprocess.run(
            [binary, "input"], cwd=folder, capture_output=True, text=True, timeout=60
        )
        assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
        conf = folder / "last_conf.dat"
        output = np.loadtxt(conf, skiprows=3)
        assert output.shape == (3 * 484 + 6 * 16, 15) and np.isfinite(output).all()
