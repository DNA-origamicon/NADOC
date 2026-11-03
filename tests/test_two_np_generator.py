"""Constraint-focused checks for the temporary solid-rod generator."""

import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.headless_build import scratch_session
from backend.api.routes_generate_design import (
    generate_design,
    GenerateRequest,
)
from backend.api.two_np_build import materialize
from backend.core.models import Design, Nanoparticle, Mat4x4, LatticeType
from backend.core.two_np_generator import (
    GeneratorSettings,
    gold_pair,
    pair_frame,
    cross_sections,
    plan_rods,
    scaffold_nt,
)
from backend.core.design_geometry import fitting_geometry
from backend.core.duplex import duplex_wc_ok
from backend.core.protein import resolve_overhang_anchor
from backend.core.validator import validate_design


def source(lattice=LatticeType.HONEYCOMB, displacement=(20, 30, 40), radii=(5, 5)):
    origin = np.array([8.0, -12.0, 3.0])
    ps = []
    for center, radius in zip([origin, origin + np.array(displacement)], radii):
        matrix = np.eye(4)
        matrix[:3, 3] = center
        ps.append(Nanoparticle(diameter_nm=2 * radius, pose=Mat4x4.from_array(matrix)))
    return Design(lattice_type=lattice, nanoparticles=ps)


@pytest.mark.parametrize("delta", [(0, 0, 40), (0, -40, 0), (-40, 0, 0), (20, 30, -40)])
def test_frame_arbitrary_orientation_and_roll(delta):
    s = source(displacement=delta)
    _, centers, _ = gold_pair(s)
    frame = pair_frame(centers, 57)
    np.testing.assert_allclose(frame.T @ frame, np.eye(3), atol=1e-12)
    assert np.linalg.det(frame) == pytest.approx(1)
    np.testing.assert_allclose(frame[:, 2], np.asarray(delta) / np.linalg.norm(delta))
    assert not np.allclose(frame[:, 1], pair_frame(centers, 0)[:, 1])


def test_section_families_are_complete_and_rotationally_symmetric():
    for section in cross_sections(LatticeType.SQUARE):
        cells = {tuple(p) for p in section["cells"]}
        assert cells == {
            (r, c) for r in {p[0] for p in cells} for c in {p[1] for p in cells}
        }
    from backend.core.lattice import honeycomb_position

    for section in cross_sections(LatticeType.HONEYCOMB):
        xy = np.array([honeycomb_position(*cell) for cell in section["cells"]])
        xy -= xy.mean(0)
        angle = 2 * np.pi / (2 if len(xy) in (10, 14) else 3 if len(xy) == 18 else 6)
        rotation = np.array(
            [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
        )
        distances = np.linalg.norm((xy @ rotation.T)[:, None] - xy[None, :], axis=-1)
        assert np.max(np.min(distances, axis=1)) < 1e-6


@pytest.mark.parametrize("lattice", list(LatticeType))
def test_plan_budget_and_extension(lattice):
    s = source(lattice)
    before = s.model_dump_json()
    c, report = plan_rods(s, GeneratorSettings())
    short, _ = plan_rods(s, GeneratorSettings(extend_rod=False))
    assert scaffold_nt(c.design) == report["selected"]["scaffold_used_nt"]
    assert scaffold_nt(c.design) <= report["selected"]["scaffold_size"]
    assert scaffold_nt(c.design) >= scaffold_nt(short.design)
    assert report["selected"]["length_nm"] > np.linalg.norm([20, 30, 40])
    assert s.model_dump_json() == before
    # Cache templates are never handed out as mutable shared designs.
    c.design.helices.clear()
    fresh, _ = plan_rods(s, GeneratorSettings())
    assert fresh.design.helices


def test_8064_chosen_only_for_thicker_complete_section():
    _, report = plan_rods(source(displacement=(0, 0, 40)), GeneratorSettings())
    a, b = report["alternatives"]
    assert report["selected"]["scaffold_size"] == 8064
    assert b["helix_count"] > a["helix_count"]
    _, same = plan_rods(source(), GeneratorSettings())
    assert same["selected"]["scaffold_size"] == 7249


@pytest.mark.parametrize(
    "s, message",
    [
        (Design(), "exactly two"),
        (source(displacement=(0, 0, 9)), "overlap"),
        (source(displacement=(0, 0, 3000)), "Neither 7249"),
    ],
)
def test_unreachable_plans(s, message):
    with pytest.raises(ValueError, match=message):
        plan_rods(s, GeneratorSettings())


def assert_materialized(d, original, roll=0):
    assert validate_design(d).passed
    assert all(
        s.sequence and set(s.sequence) <= set("ACGT")
        for s in d.strands
        if s.id not in {x.id for x in original.strands}
    )
    assert len(d.nanoparticle_connection_versions) == 2
    assert len(d.scaffolds()) == 1 + len(original.scaffolds())
    assert all(duplex_wc_ok(d, dx)[0] for dx in d.duplexes)
    geometry = fitting_geometry(d)
    particles, centers, _ = gold_pair(original)
    frame = pair_frame(centers, roll)
    cluster = next(c for c in d.cluster_transforms if c.name == "Generated rod")
    np.testing.assert_allclose(
        Rotation.from_quat(cluster.rotation).as_matrix()[:, 2], frame[:, 2], atol=1e-10
    )
    for particle, center in zip(particles, centers):
        p = next(p for p in d.nanoparticles if p.id == particle.id)
        np.testing.assert_allclose(p.pose.to_array()[:3, 3], center, atol=1e-10)
        v = next(
            v for v in d.nanoparticle_connection_versions if v.nanoparticle_id == p.id
        )
        assert v.applied and v.relaxed and v.residual_nm < 1e-8
        root, _ = resolve_overhang_anchor(geometry, v.overhang_id, "root")
        assert np.dot(center - root, frame[:, 1]) > 0
        owner = next(
            c
            for c in d.nanoparticle_conjugations
            if any(r.strand_id == v.strand_id for r in c.surface_strands)
        )
        record = next(r for r in owner.surface_strands if r.strand_id == v.strand_id)
        flag = "is_five_prime" if owner.attach_end == "5p" else "is_three_prime"
        terminal = next(
            n for n in geometry if n.get("strand_id") == v.strand_id and n.get(flag)
        )
        expected = (p.pose.to_array() @ np.r_[record.backbone_attachment_local_nm, 1])[
            :3
        ]
        np.testing.assert_allclose(terminal["backbone_position"], expected, atol=1e-8)
        assert (
            min(
                np.linalg.norm(np.array(n["backbone_position"]) - center)
                for n in geometry
            )
            >= p.diameter_nm / 2
        )


@pytest.fixture
def native_asset_client(monkeypatch):
    # Reuse the actual generation job/commit harness, including job cleanup.
    from tests.test_part_asset_routes import client
    yield from client.__wrapped__(monkeypatch)


@pytest.mark.slow
def test_current_loadout_history_scrub_edit_revert_and_undo(native_asset_client):
    from backend.api.crud import _seek_feature_log, revert_to_before_feature
    from backend.core.design_loadouts import encode_snapshot
    from backend.core.models import DesignLoadout
    from backend.api.headless_build import build_bundle
    from tests.test_part_pending_np_connections import append, gold
    from tests.test_native_asset_evaluation import worker, poison
    from tests.test_part_asset_routes import publish, PATH
    from backend.core.part_overlay_commands import command_input
    from backend.api.part_proof_commands import execute

    client = native_asset_client
    original = build_bundle([(0, 0), (0, 1)], 42,
        lattice=LatticeType.HONEYCOMB, name="Existing DNA")
    for i, particle in enumerate(source().nanoparticles):
        identity = f"gold-{i}"
        original = append(original, 'nanoparticle-create', gold(identity), f'particle-{i}')
        original = append(original, 'nanoparticle-patch', {'_proof_version': 1,
            'nanoparticle_version': 1, 'nanoparticle_id': identity,
            'pose': particle.pose.values}, f'pose-{i}')
    payload, size = encode_snapshot(original)
    loadout = DesignLoadout(id="main", name="Working loadout",
        design_snapshot_gz_b64=payload, snapshot_size_bytes=size)
    original = original.copy_with(loadouts=[loadout], active_loadout_id=loadout.id)
    state.load_design(original)
    start = len(original.feature_log)
    generated = publish(client, "POST", "/api/design/generate-design", {
        "expected_revision": state.revision(), "roll_deg": 53, "extend_rod": False})
    assert generated.loadouts == original.loadouts
    assert generated.active_loadout_id == original.active_loadout_id
    # Replay regenerates recovery bytes; authored commands and identities stay exact.
    inputs = {'id', 'op_kind', 'label', 'timestamp', 'params', 'suppressed'}
    assert [e.model_dump(mode='json', include=inputs) for e in generated.feature_log[:start]] == [
        e.model_dump(mode='json', include=inputs) for e in original.feature_log]
    assert len(generated.feature_log) > 15
    assert all(getattr(e, "op_kind", None) != "generate-design" for e in generated.feature_log)
    assert len(generated.duplexes) == 2
    for helix in original.helices:
        assert generated.find_helix(helix.id) == helix
    for strand in original.strands:
        assert generated.find_strand(strand.id) == strand
    assert worker(poison(generated), {"operation": "verify"})["status"] == "verified"
    fields = ("helices", "strands", "nanoparticles", "nanoparticle_conjugations",
              "nanoparticle_connection_versions", "duplexes", "cluster_transforms")
    for i, entry in enumerate(generated.feature_log):
        if entry.feature_type == 'snapshot':
            expected = state.decode_design_snapshot(entry.post_state_gz_b64)
        else:
            # Transform rows are input-only; evaluate them over the prior stage.
            kind, params = command_input(entry)
            expected = execute(kind, expected, params)
        scrubbed = _seek_feature_log(generated, i)
        for field in fields:
            assert getattr(scrubbed, field) == getattr(expected, field), (i, field)
        assert scrubbed.active_loadout_id == original.active_loadout_id

    index = next(i for i, e in enumerate(generated.feature_log)
                 if getattr(e, "op_kind", None) == "nanoparticle-conjugate")
    edited = publish(client, "POST", PATH, {"operation": "edit", "index": index,
        "params": {"spacer_nm": .8}, "expected_revision": state.revision()})
    assert [e.id for e in edited.feature_log] == [e.id for e in generated.feature_log]
    assert edited.active_loadout_id == original.active_loadout_id
    assert worker(poison(edited), {"operation": "verify"})["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump() == generated.model_dump()
    state.redo()
    assert state.get_or_404().model_dump() == edited.model_dump()

    before, revision, depth = state.get_or_404(), state.revision(), state.undo_depth()
    response = client.post(PATH, json={"operation": "edit", "index": start,
        "params": {"length_bp": 0}, "expected_revision": revision})
    assert response.status_code == 202, response.text
    failed_job = response.json()["job_id"]
    result = client.get(f"{PATH}/{failed_job}").json()["result"]
    assert result["status"] != "ready", result
    assert state.get_or_404() is before and state.revision() == revision
    assert state.undo_depth() == depth

    revert_to_before_feature(start)
    reverted = state.get_or_404()
    for field in fields:
        assert getattr(reverted, field) == getattr(original, field)
    assert len(reverted.feature_log) == start
    assert reverted.loadouts == original.loadouts
    assert reverted.active_loadout_id == original.active_loadout_id
    assert worker(poison(reverted), {"operation": "verify"})["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump() == edited.model_dump()
    state.redo()
    assert state.get_or_404().model_dump() == reverted.model_dump()


@pytest.mark.slow
def test_square_reuses_3prime_and_5prime_handles():
    from backend.api.routes_nanoparticles import (
        put_conjugation,
        ThiolConjugationRequest,
    )

    original = source(LatticeType.SQUARE)
    with scratch_session(LatticeType.SQUARE):
        state.set_design(original)
        for p, end, length in zip(original.nanoparticles, ["3p", "5p"], [24, 22]):
            put_conjugation(
                p.id,
                ThiolConjugationRequest(
                    scheme="direct_thiol",
                    sequence=("ACGTCAGT" * 4)[:length],
                    count=1,
                    attach_end=end,
                ),
            )
        original = state.get_or_404().model_copy(deep=True)
        original_sequences = {s.id: s.sequence for s in original.strands}
        candidate, _ = plan_rods(original, GeneratorSettings())
        generated, report = materialize(original, candidate, GeneratorSettings())
        assert all(item["reused"] for item in report["connections"])
        for item in report["connections"]:
            assert (
                generated.find_strand(item["strand_id"]).sequence
                == original_sequences[item["strand_id"]]
            )
        assert_materialized(generated, original)


def test_stale_plan_and_unreachable_leave_state_untouched():
    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()
        with pytest.raises(HTTPException) as error:
            generate_design(GenerateRequest(expected_revision=revision - 1))
        assert error.value.status_code == 409
        assert state.revision() == revision
        assert state.get_or_404().model_dump() == original.model_dump()
        with pytest.raises(HTTPException):
            state.set_design_branch(Design(), expected_revision=revision - 1)
        assert state.get_or_404().model_dump() == original.model_dump()


@pytest.mark.slow
def test_incompatible_radii_reject_without_changing_source():
    with scratch_session():
        original = source(radii=(2, 22))
        state.set_design(original)
        revision = state.revision()
        with pytest.raises(HTTPException) as error:
            generate_design(GenerateRequest(expected_revision=revision))
        assert error.value.status_code == 422
        assert state.revision() == revision
        assert state.get_or_404().model_dump() == original.model_dump()


def test_edit_during_generation_cannot_be_overwritten(monkeypatch):
    import backend.api.routes_generate_design as route

    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()
        edited = original.model_copy(deep=True)
        edited.metadata.name = "Concurrent edit"

        def finish_after_edit(source_design, candidate, settings):
            state.set_design(edited)
            return candidate.design, {}

        monkeypatch.setattr(route, "build_recorded", finish_after_edit)
        with pytest.raises(HTTPException) as error:
            route.generate_design(GenerateRequest(expected_revision=revision))
        assert error.value.status_code == 409
        assert state.get_or_404().model_dump() == edited.model_dump()
        assert not state.get_or_404().loadouts


def test_http_routes_validate_inputs():
    from fastapi.testclient import TestClient
    from backend.api.main import app

    client = TestClient(app)
    for body in [{"duplex_bp": 3}, {"roll_deg": "NaN"}, {"duplex_bp": 18.5}]:
        response = client.post("/api/design/generate-design/plan", json=body)
        assert response.status_code == 422
