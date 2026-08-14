"""Out-of-date oxDNA job detection: design fingerprint, the stale guard, and the
non-destructive feature-log roll (seek).  GPU-free — no oxDNA binary needed (the
guard fires before any binary use)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.api.routes_oxdna as routes_oxdna
from backend.api import state as design_state

# Module-level (collection time) so the app is built with the REAL routers before any
# test that swaps a fake fastapi into sys.modules (test_md_milestone1) runs.
from backend.api.main import app
from backend.core.models import ClusterRigidTransform, DeformationLogEntry
from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
from backend.core.oxdna_staleness import (
    current_active_design_fingerprint,
    effective_feature_log_position,
    job_out_of_date,
    oxdna_design_fingerprint,
)
from tests.conftest import make_6hb_design


@pytest.fixture(autouse=True)
def _clean_default_doc():
    """These tests set the DEFAULT document's active design (the TestClient routes
    read it).  Reset any leaked doc-context contextvar to the default doc first (so
    set_design and the routes agree), and drop the design afterwards so they never
    leak an active design into the shared state (headless oxDNA tests assume a clean
    default doc)."""
    from backend.api import doc_context

    doc_context.set_current_doc(None)
    yield
    design_state.drop_doc(doc_context.DEFAULT_DOC_ID)


# ── Fingerprint ───────────────────────────────────────────────────────────────


def test_fingerprint_deterministic():
    d = make_6hb_design()
    assert oxdna_design_fingerprint(d) == oxdna_design_fingerprint(d)


def test_fingerprint_changes_on_topology_edit():
    d = make_6hb_design()
    fp = oxdna_design_fingerprint(d)
    edited = d.copy_with(strands=d.strands[:-1])  # remove a strand → different build
    assert oxdna_design_fingerprint(edited) != fp


def test_fingerprint_ignores_display_only_fields():
    """Display-only edits must NOT mark a job stale."""
    d = make_6hb_design()
    fp = oxdna_design_fingerprint(d)
    recolored = d.copy_with(
        strands=[
            strand.model_copy(update={"color": "#12ABEF"}) if i == 0 else strand
            for i, strand in enumerate(d.strands)
        ]
    )
    assert oxdna_design_fingerprint(recolored) == fp
    moved_cluster = d.copy_with(
        cluster_transforms=[ClusterRigidTransform(translation=[10.0, 0.0, 0.0])]
    )
    assert oxdna_design_fingerprint(moved_cluster) == fp
    cursor_moved = d.copy_with(feature_log_cursor=3)
    assert oxdna_design_fingerprint(cursor_moved) == fp


def test_fingerprint_ignores_reference_geometry_excluded_from_simulation():
    """A fresh job hashes the simulation projection, not the editor backdrop."""
    d = make_6hb_design()
    reference = d.strands[0]
    with_reference = d.copy_with(
        strands=[
            strand.model_copy(update={"is_reference": True})
            if strand.id == reference.id
            else strand
            for strand in d.strands
        ]
    )

    assert oxdna_design_fingerprint(with_reference) == oxdna_design_fingerprint(
        with_reference.without_reference_geometry()
    )


def test_current_fingerprint_cached_until_design_revision_changes(monkeypatch):
    """Frequent job-card polls hash a large unchanged design only once."""
    from backend.core import oxdna_staleness

    calls = 0
    real = oxdna_staleness.design_build_fingerprint

    def counted(design):
        nonlocal calls
        calls += 1
        return real(design)

    monkeypatch.setattr(oxdna_staleness, "design_build_fingerprint", counted)
    design_state.set_design(make_6hb_design())
    first = current_active_design_fingerprint()
    assert current_active_design_fingerprint() == first
    assert calls == 1

    design_state.set_design(make_6hb_design().copy_with(strands=[]))
    assert current_active_design_fingerprint() != first
    assert calls == 2


# ── Feature-log roll position ─────────────────────────────────────────────────


def test_effective_feature_log_position():
    d = make_6hb_design()
    assert effective_feature_log_position(d.copy_with(feature_log=[])) is None
    log = [DeformationLogEntry(deformation_id=f"x{i}") for i in range(3)]
    assert (
        effective_feature_log_position(
            d.copy_with(feature_log=log, feature_log_cursor=-1)
        )
        == 2
    )
    assert (
        effective_feature_log_position(
            d.copy_with(feature_log=log, feature_log_cursor=1)
        )
        == 1
    )


# ── out-of-date comparison ────────────────────────────────────────────────────


def test_job_out_of_date_comparison():
    assert job_out_of_date("a", "b") is True
    assert job_out_of_date("a", "a") is False
    assert job_out_of_date(None, "a") is False  # unknown → never blocked
    assert job_out_of_date("a", None) is False
    # Upgrade compatibility: legacy colour-inclusive hashes cannot be directly
    # compared with v2 and must not make an unchanged existing job look stale.
    assert job_out_of_date("a" * 64, "v3:" + "b" * 64) is False
    assert job_out_of_date("v2:" + "a" * 64, "v3:" + "b" * 64) is False


# ── Guard helper + routes ─────────────────────────────────────────────────────


def test_assert_job_current_raises_409_when_stale(monkeypatch, tmp_path):

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    d = make_6hb_design()
    design_state.set_design(d)

    stale = new_oxdna_job("d", [], design_fingerprint="not-the-current-fp")
    with pytest.raises(HTTPException) as ei:
        routes_oxdna._assert_job_current(stale)
    assert ei.value.status_code == 409
    assert "design has changed" in ei.value.detail.lower()

    fresh = new_oxdna_job("d", [], design_fingerprint=oxdna_design_fingerprint(d))
    routes_oxdna._assert_job_current(fresh)  # matching fingerprint → no raise


def test_production_refused_when_design_changed(monkeypatch, tmp_path):

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/fake/oxDNA")
    monkeypatch.setattr(routes_oxdna, "start_job", lambda *a, **k: None)

    design_state.set_design(make_6hb_design())
    job = new_oxdna_job("d", [], design_fingerprint="stale-fp")
    job.status = OxdnaStatus.completed
    job.save(tmp_path)

    r = TestClient(app).post(
        f"/api/oxdna/jobs/{job.job_id}/production", json={"steps": 1000}
    )
    assert r.status_code == 409
    assert "design has changed" in r.json()["detail"].lower()


def test_list_route_flags_out_of_date(monkeypatch, tmp_path):

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    d = make_6hb_design()
    design_state.set_design(d)
    fp = oxdna_design_fingerprint(d)

    fresh = new_oxdna_job("d", [], design_fingerprint=fp)
    fresh.status = OxdnaStatus.completed
    fresh.save(tmp_path)
    stale = new_oxdna_job("d", [], design_fingerprint="deadbeef")
    stale.status = OxdnaStatus.completed
    stale.save(tmp_path)

    by_id = {j["job_id"]: j for j in TestClient(app).get("/api/oxdna/jobs").json()}
    assert by_id[fresh.job_id]["out_of_date"] is False
    assert by_id[stale.job_id]["out_of_date"] is True


# ── Roll to a job's exact state (restore snapshot, not seek) ──────────────────


def test_roll_design_restores_snapshot_and_clears_out_of_date(monkeypatch, tmp_path):
    """The reported bug: out-of-date must CLEAR after rolling to the job's state — even
    when the state includes sequences.  This is the OLD-job fallback: a job with no
    recorded feature-log position can't be seeked, so `roll-design` overlays the job's
    exact snapshot (fingerprint re-matches, edits preserved on the return loadout)."""

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)

    # The design the job ran at — with sequences assigned (NOT a feature-log snapshot).
    relaxed = make_6hb_design()
    for s in relaxed.strands:
        s.sequence = "ACGT"
    job_fp = oxdna_design_fingerprint(relaxed)

    job = new_oxdna_job("6hb", [], design_fingerprint=job_fp)
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(relaxed.model_dump_json())

    # The user then edits the design (clears sequences) → job is out of date.
    edited = relaxed.model_copy(deep=True)
    for s in edited.strands:
        s.sequence = ""
    design_state.set_design(edited)
    c = TestClient(app)
    assert c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is True

    # Roll to the job's state → restores the sequenced snapshot, clears the flag.
    r = c.post(f"/api/oxdna/jobs/{job.job_id}/roll-design")
    assert r.status_code == 200, r.text
    assert r.json().get("return_loadout_id")  # later work saved as a branch
    assert r.json()["matches_job"] is True
    restored = design_state.get_or_404()
    assert all(s.sequence == "ACGT" for s in restored.strands)  # sequences came back
    assert oxdna_design_fingerprint(restored) == job_fp
    assert (
        c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is False
    )  # ⚠ cleared

    # Return to latest (select the branch WITHOUT saving the rolled state over it)
    # restores the edited (cleared) state.
    rid = r.json()["return_loadout_id"]
    assert (
        c.post(f"/api/design/loadouts/{rid}/select?save_current=false").status_code
        == 200
    )
    back = design_state.get_or_404()
    assert all(not s.sequence for s in back.strands)


def test_cross_design_roll_uses_job_snapshot_history_not_active_file_history(
    monkeypatch, tmp_path
):
    """Rolling is allowed across files, but the two Feature Logs must never splice."""
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    snapshot = make_6hb_design().model_copy(update={"id": "job-design"})
    job = new_oxdna_job(
        "job-design", [], design_fingerprint=oxdna_design_fingerprint(snapshot)
    )
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(snapshot.model_dump_json())

    active = make_6hb_design().model_copy(update={"id": "other-design"})
    design_state.set_design(active)
    c = TestClient(app)
    assert c.post(
        "/api/design/assign-scaffold-sequence", json={"custom_sequence": "ACGT" * 2000}
    ).status_code == 200
    assert len(design_state.get_or_404().feature_log) > len(snapshot.feature_log)

    response = c.post(f"/api/oxdna/jobs/{job.job_id}/roll-design")
    assert response.status_code == 200, response.text
    rolled = design_state.get_or_404()
    assert rolled.id == "job-design"
    assert rolled.feature_log == snapshot.feature_log


def test_af26_roll_return_lifecycle_overhang_edit(monkeypatch, tmp_path):
    """AF-26 — the full simulate→edit→roll→return lifecycle as ONE driven oracle,
    using the OVERHANG edit (the membership case AF-25 fixed) the existing per-slice
    tests never exercised: build → relax (mock job) → add an overhang → the job goes
    stale → a production attempt is refused 409 → roll seeks back (overhang gone,
    sequences survive, ⚠ clears) → return-to-latest brings the overhang back.

    Drives the headless wrappers ``roll_job_to_run_state`` + ``return_to_latest`` so
    they're validated, not passthroughs."""
    import asyncio

    from backend.api import headless_build as hb
    from backend.api import headless_oxdna_build as hox
    from backend.api.routes_oxdna import ProductionRequest, append_oxdna_production
    from backend.core.models import LatticeType
    from backend.physics.oxdna_interface import count_undefined_bases
    from tests.automation_harness import assert_roll_return_lifecycle
    from tests.conftest import SIX_HB_CELLS
    from tests.test_headless_build import _place_one_overhang

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/fake/oxDNA")
    monkeypatch.setattr(routes_oxdna, "start_job", lambda *a, **k: None)

    # Build a routed, broken, sequenced 6hb on the DEFAULT doc (the routes read it).
    hb.new_design(LatticeType.HONEYCOMB)
    hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()
    hb.assign_scaffold_sequence()
    hb.assign_staple_sequences()
    d = design_state.get_or_404()
    run_fp = oxdna_design_fingerprint(d)
    pos = effective_feature_log_position(d)

    # A completed mock job relaxed at the run state (no GPU — guard fires pre-binary).
    job = new_oxdna_job("6hb", [], design_fingerprint=run_fp, feature_log_position=pos)
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(d.model_dump_json())

    # EDIT after the run: add an overhang → job diverges + goes stale.
    edited = _place_one_overhang(design_state.get_or_404())
    assert edited is not None and len(edited.overhangs) == 1

    c = TestClient(app)

    def _out_of_date() -> bool:
        return c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"]

    def _stale_live_call():
        # Direct route call RAISES HTTPException(409) (the guard) before any binary use.
        return asyncio.run(
            append_oxdna_production(job.job_id, ProductionRequest(steps=1000))
        )

    def _run_state_probe(des) -> bool:
        undef, total = count_undefined_bases(des, exclude_reference=True)
        return len(des.overhangs) == 0 and total > 0 and undef < total

    assert_roll_return_lifecycle(
        roll=lambda: hox.roll_job_to_run_state(job.job_id, tmp_path),
        return_to_latest=hb.return_to_latest,
        out_of_date=_out_of_date,
        stale_live_call=_stale_live_call,
        run_fingerprint=run_fp,
        run_log_position=pos,
        edit_probe=lambda des: len(des.overhangs) == 1,
        run_state_probe=_run_state_probe,
    )


def test_assign_sequences_are_feature_log_steps(tmp_path):
    """Sequence assignment is now a feature-log entry, so a seek (incl. a job roll)
    reproduces the sequenced state instead of dropping it."""
    design_state.set_design(make_6hb_design())
    c = TestClient(app)
    assert (
        c.post(
            "/api/design/assign-scaffold-sequence", json={"scaffold_name": "M13mp18"}
        ).status_code
        == 200
    )
    assert c.post("/api/design/assign-staple-sequences").status_code == 200
    kinds = [getattr(e, "op_kind", None) for e in design_state.get_or_404().feature_log]
    assert "assign-scaffold-sequence" in kinds
    assert "assign-staple-sequences" in kinds


def test_roll_selects_protected_snapshot_loadout_and_keeps_editable_log(monkeypatch, tmp_path):
    """Viewing a run restores its exact historical log in a protected loadout while
    retaining the later editable branch independently."""
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)

    design_state.set_design(make_6hb_design())
    c = TestClient(app)
    c.post("/api/design/assign-scaffold-sequence", json={"scaffold_name": "M13mp18"})
    c.post("/api/design/assign-staple-sequences")
    d = design_state.get_or_404()
    pos = effective_feature_log_position(d)  # the job runs at this log position
    seqs_at_job = [s.sequence for s in d.strands]

    job = new_oxdna_job(
        "t",
        [],
        design_fingerprint=oxdna_design_fingerprint(d),
        feature_log_position=pos,
    )
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(d.model_dump_json())

    # A NEW logged op after the job (re-assign a different scaffold) → diverged + stale.
    c.post(
        "/api/design/assign-scaffold-sequence", json={"custom_sequence": "ACGT" * 2000}
    )
    full_len = len(design_state.get_or_404().feature_log)
    assert full_len > pos + 1
    assert c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is True

    # Roll: exact frozen history becomes the active protected simulation loadout.
    r = c.post(f"/api/oxdna/jobs/{job.job_id}/roll-design")
    assert r.status_code == 200, r.text
    rolled = design_state.get_or_404()
    assert len(rolled.feature_log) == pos + 1
    sim = next(l for l in rolled.loadouts if l.id == rolled.active_loadout_id)
    assert sim.protected is True
    assert sim.simulation_job_id == job.job_id
    assert [
        s.sequence for s in rolled.strands
    ] == seqs_at_job  # model == the job's state
    assert c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is False

    # Explicitly returning to the editable branch restores its independent full log.
    editable_id = r.json()["return_loadout_id"]
    assert c.post(f"/api/design/loadouts/{editable_id}/select?save_current=false").status_code == 200
    editable = design_state.get_or_404()
    assert len(editable.feature_log) == full_len
    assert [s.sequence for s in editable.strands] != seqs_at_job


# ── Overhang-sequence writes are feature-log steps (the 6hb_sim_tests bug) ─────


def _routed_sequenced_6hb_with_overhang():
    """Build a routed/broken/sequenced 6hb on the default doc, then extrude one
    sequence-less overhang.  Returns (design, overhang_id)."""
    from backend.api import headless_build as hb
    from backend.core.models import LatticeType
    from tests.conftest import SIX_HB_CELLS
    from tests.test_headless_build import _place_one_overhang

    hb.new_design(LatticeType.HONEYCOMB)
    hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()
    hb.assign_scaffold_sequence()
    hb.assign_staple_sequences()
    edited = _place_one_overhang(design_state.get_or_404())
    assert edited is not None and len(edited.overhangs) == 1
    return edited, edited.overhangs[0].id


def test_overhang_sequence_patch_is_feature_log_step_and_clears_stale(
    monkeypatch, tmp_path
):
    """The reported 6hb_sim_tests bug: a manually-assigned overhang sequence was NOT a
    feature-log step, so seeking back to a relax job's run state dropped the sequence —
    the fingerprint never re-matched and the out-of-date ⚠ never cleared.  A PATCH
    sequence write is now a snapshot entry; seeking back reproduces it and ⚠ clears."""
    from tests.test_headless_build import _place_one_overhang

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/fake/oxDNA")
    monkeypatch.setattr(routes_oxdna, "start_job", lambda *a, **k: None)

    _design, ovid = _routed_sequenced_6hb_with_overhang()
    c = TestClient(app)

    # Manually assign the overhang sequence — the previously-unlogged write that
    # caused the divergence.  It must now append exactly one 'overhang-sequence' entry.
    n_before = len(design_state.get_or_404().feature_log)
    r = c.patch(f"/api/design/overhang/{ovid}", json={"sequence": "ACGTACGT"})
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.feature_log) == n_before + 1
    assert d.feature_log[-1].op_kind == "overhang-sequence"
    assert next(o for o in d.overhangs if o.id == ovid).sequence == "ACGTACGT"

    run_fp = oxdna_design_fingerprint(d)
    pos = effective_feature_log_position(d)

    job = new_oxdna_job("6hb", [], design_fingerprint=run_fp, feature_log_position=pos)
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(d.model_dump_json())

    # Edit after the run: a SECOND overhang → diverged + stale.
    edited2 = _place_one_overhang(design_state.get_or_404())
    assert edited2 is not None and len(edited2.overhangs) == 2
    assert c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is True

    # Roll: seek the cursor back to the job position.  The first overhang's assigned
    # sequence is reproduced (previously dropped → the bug) and ⚠ clears.
    rr = c.post(f"/api/oxdna/jobs/{job.job_id}/roll-design")
    assert rr.status_code == 200, rr.text
    rolled = design_state.get_or_404()
    assert next(o for o in rolled.overhangs if o.id == ovid).sequence == "ACGTACGT"
    assert oxdna_design_fingerprint(rolled) == run_fp
    assert c.get(f"/api/oxdna/jobs/{job.job_id}").json()["out_of_date"] is False


def test_generate_random_overhang_sequence_is_feature_log_step():
    """generate-random writes a fingerprint field too, so it must also be a logged
    snapshot (otherwise the generated sequence vanishes on a seek, same bug class)."""
    _design, ovid = _routed_sequenced_6hb_with_overhang()
    c = TestClient(app)
    n_before = len(design_state.get_or_404().feature_log)
    r = c.post(f"/api/design/overhang/{ovid}/generate-random")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.feature_log) == n_before + 1
    assert d.feature_log[-1].op_kind == "overhang-sequence"
    gen = next(o for o in d.overhangs if o.id == ovid).sequence
    assert gen and set(gen) <= set("ACGT")
