"""Constraint-focused checks for the temporary solid-rod generator."""

import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.headless_build import scratch_session
from backend.api.routes_generate_design import (
    generate_design,
    plan_design,
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
        angle = 2 * np.pi / (3 if len(xy) == 18 else 6)
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


@pytest.mark.slow
def test_current_loadout_history_scrub_edit_revert_and_undo():
    from backend.api.headless_build import create_bundle
    from backend.api.routes_design_loadouts import create_loadout, LoadoutCreateBody
    from backend.api.crud import (
        _seek_feature_log,
        edit_feature,
        EditFeatureBody,
        revert_to_before_feature,
    )

    with scratch_session():
        state.set_design(source())
        create_bundle(
            [(0, 0), (0, 1)], 42, lattice=LatticeType.HONEYCOMB, name="Existing DNA"
        )
        state.mutate_with_feature_log(
            "nanoparticle-create",
            "Place gold pair",
            {},
            lambda d: d.copy_with(nanoparticles=source().nanoparticles),
        )
        create_loadout(LoadoutCreateBody(name="Working loadout"))
        original = state.get_or_404().model_copy(deep=True)
        start = len(original.feature_log)
        plan = plan_design(GeneratorSettings(roll_deg=53))
        response = generate_design(
            GenerateRequest(expected_revision=plan["revision"], roll_deg=53)
        )
        d = state.get_or_404()
        assert d.loadouts == original.loadouts
        assert d.active_loadout_id == original.active_loadout_id
        assert d.feature_log[:start] == original.feature_log
        assert len(d.feature_log) > 15
        assert all(e.op_kind != "generate-design" for e in d.feature_log)
        assert response["generation"]["connections"]
        for h in original.helices:
            assert d.find_helix(h.id) == h
        for s in original.strands:
            assert d.find_strand(s.id) == s
        assert_materialized(d, original, 53)
        fields = (
            "helices",
            "strands",
            "nanoparticles",
            "nanoparticle_conjugations",
            "nanoparticle_connection_versions",
            "duplexes",
            "cluster_transforms",
        )
        for i, e in enumerate(d.feature_log):
            expected = state.decode_design_snapshot(e.post_state_gz_b64)
            scrubbed = _seek_feature_log(d, i)
            for field in fields:
                assert getattr(scrubbed, field) == getattr(expected, field), (i, field)
            assert scrubbed.active_loadout_id == original.active_loadout_id
        # Earlier parameter edit rebuilds every dependent command and retains
        # feature identities, while unrelated DNA and loadout identity persist.
        pose_index = next(
            i
            for i, e in enumerate(d.feature_log)
            if e.params.get("_generator", {}).get("key") == "rod-pose"
        )
        feature_ids = [e.id for e in d.feature_log]
        edit_feature(pose_index, EditFeatureBody(params={"roll_deg": 0}))
        edited = state.get_or_404()
        assert [e.id for e in edited.feature_log] == feature_ids
        assert edited.active_loadout_id == original.active_loadout_id
        assert_materialized(edited, original, 0)
        before_failure = edited.model_dump_json()
        revision = state.revision()
        with pytest.raises(HTTPException) as error:
            edit_feature(start, EditFeatureBody(params={"length_bp": 2016}))
        assert error.value.status_code == 422
        assert state.revision() == revision
        assert state.get_or_404().model_dump_json() == before_failure
        root_index = next(
            i
            for i, e in enumerate(edited.feature_log)
            if e.op_kind == "overhang-extrude"
        )
        expected = state.decode_design_snapshot(
            edited.feature_log[root_index].design_snapshot_gz_b64
        )
        revert_to_before_feature(root_index)
        reverted = state.get_or_404()
        for field in fields:
            assert getattr(reverted, field) == getattr(expected, field)
        assert len(reverted.feature_log) == root_index
        assert reverted.active_loadout_id == original.active_loadout_id
        state.undo()
        assert state.get_or_404().model_dump() == edited.model_dump()
        revert_to_before_feature(start)
        assert state.get_or_404().model_dump() == original.model_dump()
        state.undo()
        revert_to_before_feature(start + 1)
        edit_feature(start, EditFeatureBody(params={"length_bp": 42}))
        partial = state.get_or_404()
        assert len(partial.feature_log) == start + 1
        assert partial.feature_log[-1].params["length_bp"] == 42
        assert not partial.nanoparticle_conjugations
        assert partial.active_loadout_id == original.active_loadout_id


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
