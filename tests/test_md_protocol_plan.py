"""The computed protocol plan behind the Job Wizard.

The theme of this file: the plan must never DESCRIBE the protocol, it must REPORT it.
Several tests below deliberately assert a computed value against the code that computes
it, rather than against a literal — a literal here is exactly the drift the wizard exists
to remove (the notes said 12 ladder segments while the code built 20, and said the ladder
barostat was 200/100 fs when it is 1000/500).
"""

from __future__ import annotations

import inspect
import json

import pytest

from backend.core import md_plan
from backend.core import md_protocols as P
from backend.core.md_cutoff import CutoffParams


def _ctx(**kw) -> md_plan.PlanContext:
    return md_plan.PlanContext(name_stem="demo", **kw)


# ── Conf parsing ──────────────────────────────────────────────────────────────


def test_parse_conf_directives_lowercases_keys_and_keeps_values():
    got = md_plan.parse_conf_directives("timestep           4.0\nrigidBonds  all\n")
    assert got == {"timestep": "4.0", "rigidbonds": "all"}


def test_parse_conf_directives_collapses_repeats_to_a_list_in_file_order():
    """extraBondsFile repeats, and the ORDER carries meaning.

    Keeping only the last value would hide the elastic-network file behind the magnesium
    extrabonds file — the single most important restraint fact in the whole ladder.
    """
    got = md_plan.parse_conf_directives(
        "extraBondsFile     mgh_extrabonds.txt\nextraBondsFile     demo_k0.5.enm.extra\n"
    )
    assert got["extrabondsfile"] == ["mgh_extrabonds.txt", "demo_k0.5.enm.extra"]


def test_parse_conf_directives_drops_comments_and_blank_lines():
    got = md_plan.parse_conf_directives("# a comment\n\ncutoff  10.0   # trailing\n")
    assert got == {"cutoff": "10.0"}


# ── Stage table ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fast", [True, False])
def test_plan_lists_every_ladder_segment_plus_minimisation(fast):
    """Asserted against the builder, never against a literal count."""
    _min_name, segments = P.mgh_slow_release_segments(
        "demo", timestep_fs=4.0 if fast else 2.0
    )
    rows = md_plan.relaxation_stages(_ctx(fast=fast))
    assert len(rows) == len(segments) + 1
    assert rows[0]["role"] == "minimization"
    assert [r["name"] for r in rows[1:]] == [s.name for s in segments]


def test_plan_timestep_matches_the_conf_that_will_actually_be_written():
    """The honesty test.

    Every physics-bearing directive in the plan is compared against a freshly written conf
    for the same segment.  If someone later teaches the plan to compute a value instead of
    reading it, this fails.  ``effective_timestep_fs`` is checked separately because the
    plan reports it as a top-level fact (the wizard multiplies it by the step count to get
    simulated nanoseconds), not just as a conf directive.
    """
    ctx = _ctx(fast=True)
    _min_name, segments = P.mgh_slow_release_segments("demo", timestep_fs=4.0)
    rows = {r["name"]: r for r in md_plan.relaxation_stages(ctx)}

    watched = (
        "timestep",
        "rigidbonds",
        "fullelectfrequency",
        "stepspercycle",
        "pairlistdist",
        "cutoff",
        "switchdist",
        "langevinpistonperiod",
        "langevinpistondecay",
        "langevindamping",
        "constraints",
        "run",
    )
    for spec in segments:
        written = md_plan.parse_conf_directives(
            P._segment_conf(spec, "demo", ctx.box, ctx.mgh_extrabonds, fast=ctx.fast)
        )
        row = rows[spec.name]
        for key in watched:
            assert row["params"].get(key) == written.get(key), f"{spec.name}:{key}"
        assert row["timestep_fs"] == P.effective_timestep_fs(spec, ctx.fast)
        assert row["params"]["timestep"] == f"{row['timestep_fs']:g}"


def test_every_ladder_segment_emits_constraints_off():
    """Surprising but true, and worth pinning.

    The ENM restraint reaches NAMD purely through ``extraBondsFile``; the ``constraints``
    machinery (consref/conskfile/constraintScaling) is never engaged, because
    ``_segment_conf`` only takes that branch when a scale is set WITHOUT an extrabonds
    file, and the ladder always sets both together.  A reader who assumes
    ``constraints on`` means "restrained" would misread every column.

    The SETTLE stage is the sole exception and the reason the branch exists at all: it
    carries no ENM, so the constraints channel is free for the position restraint that
    holds the solute while the barostat works.
    """
    for row in md_plan.relaxation_stages(_ctx(fast=True))[1:]:
        if row["role"] == "settle":
            continue
        assert row["params"]["constraints"] == "off", row["name"]


def test_the_settle_stage_is_the_one_that_uses_the_constraints_channel():
    """And it must not also engage the ENM — the two would fight over the same solute."""
    settle = [
        r for r in md_plan.relaxation_stages(_ctx(fast=True)) if r["role"] == "settle"
    ]
    assert len(settle) == 1
    params = settle[0]["params"]
    assert params["constraints"] == "on"
    assert params["conskcol"] == "B"
    assert "fixedatoms" not in params
    assert (
        "extrabondsfile" not in params or ".enm.extra" not in params["extrabondsfile"]
    )


def test_restraint_ladder_steps_down_through_the_extrabonds_file():
    """k = 0.5 -> 0.1 -> 0.01 -> none, visible only in extraBondsFile."""
    seen = []
    for row in md_plan.relaxation_stages(_ctx(fast=True))[1:]:
        files = row["params"].get("extrabondsfile")
        files = files if isinstance(files, list) else [files]
        enm = [f for f in files if f and "enm.extra" in f]
        if not seen or (enm and enm[-1] != seen[-1]):
            seen.extend(enm[-1:] or [])
    assert seen == [
        "demo_k0.5.enm.extra",
        "demo_k0.1.enm.extra",
        "demo_k0.01.enm.extra",
    ]
    assert not any(
        "enm.extra" in str(f)
        for f in [
            md_plan.relaxation_stages(_ctx(fast=True))[-1]["params"].get(
                "extrabondsfile"
            )
        ]
    )


# ── Diffs ─────────────────────────────────────────────────────────────────────


def test_stage_diff_is_empty_for_the_first_stage():
    assert md_plan.stage_diff(None, {"timestep": "4"}) == {}


def test_stage_diff_reports_appearance_and_disappearance():
    """A directive that only exists on one side is the MOST important kind of difference.

    The barostat block vanishing, or the elastic network appearing, is precisely what a
    stage-to-stage comparison is for.  Dropping those would be the worst omission.
    """
    got = md_plan.stage_diff(
        {"langevinpiston": "on", "margin": "3"}, {"langevinpiston": "off"}
    )
    assert got == {"langevinpiston": ["on", "off"], "margin": ["3", "(absent)"]}


def test_stage_diff_ignores_output_bookkeeping():
    """Output paths differ on every single stage; leaving them in buries the physics."""
    got = md_plan.stage_diff(
        {"outputname": "a", "dcdfile": "a.dcd", "timestep": "2"},
        {"outputname": "b", "dcdfile": "b.dcd", "timestep": "4"},
    )
    assert got == {"timestep": ["2", "4"]}


def test_diff_at_a_rung_boundary_swaps_the_elastic_network_file():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    boundary = next(r for r in rows if r["name"].endswith("_02_300K_NPT_ENM_k0p1_p10"))
    old, new = boundary["diff_vs_previous"]["extrabondsfile"]
    assert old[-1] == "demo_k0.5.enm.extra"
    assert new[-1] == "demo_k0.1.enm.extra"


def test_diff_within_a_rung_reports_only_the_chunk_length():
    """Two chunks of the same rung differ in length and I/O cadence, nothing else."""
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    chunk = next(r for r in rows if r["name"].endswith("_01_300K_NPT_ENM_k0p5_p50"))
    assert set(chunk["diff_vs_previous"]) <= {
        "run",
        "dcdfreq",
        "outputenergies",
        "xstfreq",
        "restartfreq",
    }


# ── Conditions that skip or alter a stage ─────────────────────────────────────


def test_a_carved_package_loses_the_settle_stage_and_the_barostat():
    """The two costs of a water-shell carve, which nothing surfaced before."""
    full = md_plan.relaxation_stages(_ctx(fast=True))
    carved = md_plan.relaxation_stages(_ctx(fast=True, carved=True), nvt_only=True)

    assert any(r["role"] == "settle" for r in full)
    assert not any(r["role"] == "settle" for r in carved)
    assert len(carved) == len(full) - 1
    assert all(r["params"]["langevinpiston"] == "off" for r in carved[1:])

    conds = {
        c["id"]: c
        for c in md_plan.protocol_conditions(
            carved=True,
            gbis=False,
            force_soft=False,
            gentle_ladder=False,
            early_stop=True,
            gpu_resident_mode="auto",
            stages=carved,
        )
    }
    assert "settle_skipped" in conds and "barostat_off" in conds


def test_the_soft_start_lands_on_the_first_stage_whose_atoms_move():
    """Not the settle stage — nothing can strain-relieve while the solute is restrained."""
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    gentle = [r for r in rows[1:] if r["gentle"]]
    assert len(gentle) == 1
    assert gentle[0]["role"] == "ladder"
    assert gentle[0]["restraint_ref_file"] is None
    assert gentle[0]["timestep_fs"] == 2.0

    conds = {
        c["id"]
        for c in md_plan.protocol_conditions(
            carved=False,
            gbis=False,
            force_soft=False,
            gentle_ladder=False,
            early_stop=True,
            gpu_resident_mode="auto",
            stages=rows,
        )
    }
    assert "soft_start" in conds


def test_gpu_resident_is_reported_as_conditional_until_the_atom_count_is_known():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    ladder = next(r for r in rows if r["role"] == "ladder")
    assert "gpuresident" in ladder["conditional_params"]
    assert str(P._RESIDENT_MIN_ATOMS) in ladder["conditional_params"][
        "gpuresident"
    ].replace(",", "")


def test_a_known_atom_count_turns_gpu_resident_from_a_condition_into_a_fact():
    small = md_plan.relaxation_stages(_ctx(fast=True, n_atoms=1_000))
    big = md_plan.relaxation_stages(_ctx(fast=True, n_atoms=500_000))
    small_ladder = next(r for r in small if r["role"] == "ladder")
    big_ladder = next(r for r in big if r["role"] == "ladder")

    assert small_ladder["conditional_params"] == {}
    assert "gpuresident" not in small_ladder["params"]
    assert big_ladder["params"]["gpuresident"] == "on"


def test_condition_and_retry_text_quotes_the_live_constants():
    """Every threshold shown to the user is imported from the module that enforces it.

    Retyping one is how a UI ends up confidently displaying a limit the code abandoned.
    """
    from backend.core import namd_runner as R

    rows = md_plan.relaxation_stages(_ctx(fast=True))
    conds = {
        c["id"]: c
        for c in md_plan.protocol_conditions(
            carved=False,
            gbis=False,
            force_soft=False,
            gentle_ladder=False,
            early_stop=True,
            gpu_resident_mode="auto",
            stages=rows,
        )
    }
    cut = CutoffParams()
    early = conds["early_stop"]["detail"]
    assert f"{cut.window}-frame" in early
    assert f"{cut.min_frames} frames" in early
    assert f"{cut.eps_pot_drift:.2%}" in early
    assert f"{cut.eps_wc_fluct:.2%}" in early
    assert f"{P._RESIDENT_MIN_ATOMS:,}" in conds["gpu_resident_gate"]["detail"]
    assert f"{P._RESIDENT_MIN_FILL:.0%}" in conds["gpu_resident_gate"]["detail"]

    retries = {r["id"]: r for r in md_plan.retry_policy()}
    assert retries["retry_cell_shrink"]["max_attempts"] == R.MAX_CELL_SHRINK_RESUMES
    assert retries["retry_host_oom"]["max_attempts"] == R.MAX_HOST_OOM_RESUMES
    assert retries["retry_instability"]["max_attempts"] == R.MAX_INSTABILITY_RESUMES
    assert f"{R.PISTON_SOFTEN_FACTOR:g}x" in retries["retry_cell_shrink"]["detail"]


def test_early_stop_off_says_so_instead_of_going_silent():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    conds = {
        c["id"]
        for c in md_plan.protocol_conditions(
            carved=False,
            gbis=False,
            force_soft=False,
            gentle_ladder=False,
            early_stop=False,
            gpu_resident_mode="auto",
            stages=rows,
        )
    }
    assert "early_stop_off" in conds and "early_stop" not in conds


# ── Deferred values ───────────────────────────────────────────────────────────


def test_minimisation_steps_are_declared_a_floor_not_a_value():
    notes = {
        n["key"]: n
        for n in md_plan.deferred_notes(
            minimize_steps=4_800, n_atoms=None, padding_nm=2.0
        )
    }
    assert "minimize" in notes
    detail = notes["minimize"]["detail"]
    assert f"{P.minimize_steps_for_atoms(224_000, 4_800):,}" in detail
    assert str(P.MIN_STEPS_PER_ATOMS) in detail


def test_a_known_atom_count_removes_the_minimisation_caveat():
    notes = {
        n["key"]
        for n in md_plan.deferred_notes(
            minimize_steps=4_800, n_atoms=224_000, padding_nm=2.0
        )
    }
    assert "minimize" not in notes
    assert "cellBasisVector" in notes


def test_the_cell_is_always_deferred_and_never_shown_as_a_zero_box():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    for row in rows:
        assert not (set(row["params"]) & md_plan.BOX_KEYS)


# ── Production ────────────────────────────────────────────────────────────────


def test_production_chunks_split_the_requested_length_exactly():
    rows = md_plan.production_stages(
        _ctx(fast=True), total_steps=25_000_000, timestep_fs=4.0
    )
    assert [r["steps"] for r in rows] == [2_500_000, 10_000_000, 12_500_000]
    assert sum(r["ns"] for r in rows) == pytest.approx(100.0)


def test_production_names_and_labels_pin_the_shared_builder():
    """These strings are user-visible (job list, timeline) and reach the manifest."""
    spec = md_plan.production_segment_spec(
        "demo",
        stage_idx=5,
        pct=50.0,
        frac=0.40,
        total_steps=25_000_000,
        timestep_fs=4.0,
        previous="demo_04_300K_NPT_MGHH_only_p100",
    )
    assert spec.name == "demo_05_production_100ns_k0_p50"
    assert spec.stage == "100 ns fast production run"
    assert spec.dcd_freq == P.PRODUCTION_DCD_FREQ
    assert spec.scale is None and spec.min_wc_ref_relative == 0.25


@pytest.mark.parametrize(
    "dt,label", [(4.0, "fast"), (2.0, "medium"), (1.0, "conservative")]
)
def test_production_stage_label_names_the_integrator_tier(dt, label):
    assert md_plan.production_stage_label(dt) == label


def test_the_real_production_path_builds_its_specs_through_md_plan():
    """Guards LESSONS H16 structurally.

    The wizard's preview and the run that happens must come from one function.  Two
    independent constructions is how a fix lands on one call site while the other keeps
    the old behaviour, with both looking correct.
    """
    from backend.api import routes_md

    src = inspect.getsource(routes_md._append_production_segments)
    assert "md_plan.production_segment_spec" in src
    assert "md_plan.PRODUCTION_CHUNKS" in src


def test_production_surfaces_the_silent_ladder_asymmetries():
    """A production run is NOT 'the last ladder stage with the restraints removed'."""
    ladder = md_plan.relaxation_stages(_ctx(fast=True))
    prod = md_plan.production_stages(
        _ctx(fast=True, structure_psf="demo_hmr.psf"),
        total_steps=25_000_000,
        timestep_fs=4.0,
        stage_idx=5,
    )
    found = {
        a["key"]: (a["relaxation"], a["production"])
        for a in md_plan.production_asymmetries(ladder[-1]["params"], prod[0]["params"])
    }

    assert found["fullelectfrequency"] == ("2", "1")
    assert found["stepspercycle"] == ("20", "10")
    assert found["pairlistdist"] == ("13.5", "12.0")
    assert found["langevinpistonperiod"] == ("1000.0", "200.0")
    assert found["langevinpistondecay"] == ("500.0", "100.0")
    assert all(
        a["note"]
        for a in md_plan.production_asymmetries(ladder[-1]["params"], prod[0]["params"])
    )


def test_an_asymmetry_that_stops_existing_stops_being_reported():
    """So aligning the two protocols later makes the row vanish rather than lie."""
    same = {"stepspercycle": "10", "fullelectfrequency": "1"}
    assert md_plan.production_asymmetries(same, dict(same)) == []


def test_production_carries_no_elastic_network():
    prod = md_plan.production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0
    )
    files = prod[0]["params"].get("extrabondsfile")
    files = files if isinstance(files, list) else [files]
    assert not any("enm.extra" in str(f) for f in files)
    assert prod[0]["params"]["constraints"] == "off"


# ── The production CHILD (what the Job Wizard actually creates) ───────────────
#
# Two production routes exist and they build different packages.  `production_stages`
# above describes the legacy APPEND route (chunked segments bolted onto the parent job);
# `replica_production_stages` describes `POST /md/jobs/{parent}/production-run`, which the
# wizard's Create button hits and which builds a replica package.  The wizard used to
# preview the first while creating the second.


def test_a_production_child_is_a_reseed_bridge_and_ONE_production_conf():
    """The replica package has exactly two confs — not the append route's three chunks.

    Previewing the chunk ladder meant the wizard's first column carried 10 % of the step
    count of a run that was never going to be split.
    """
    rows = md_plan.replica_production_stages(
        _ctx(fast=True), total_steps=25_000_000, timestep_fs=4.0
    )
    assert [r["role"] for r in rows] == ["reseed", "production"]
    assert [r["index"] for r in rows] == [0, 1]
    assert rows[0]["steps"] == 0
    assert rows[1]["steps"] == 25_000_000
    assert rows[1]["ns"] == pytest.approx(100.0)


def test_the_child_stage_names_match_the_builder_that_writes_them():
    """The names the runner and the restart chain address these stages by."""
    rows = md_plan.replica_production_stages(
        _ctx(fast=True), total_steps=25_000_000, timestep_fs=4.0
    )
    assert rows[0]["name"] == "demo_00_reseed"
    assert rows[1]["name"] == "demo_01_production_100ns_k0"
    # The production conf continues from the reseed, not straight from the checkpoint.
    assert rows[1]["params"]["bincoordinates"] == "output/demo_00_reseed.coor"


def test_the_replica_builder_and_the_preview_come_from_ONE_spec_builder():
    """Guards LESSONS H16 for the spawn path, as the append path is already guarded.

    Both must construct the production SegmentSpec the same way, or a fix lands on the
    preview and the run keeps the old behaviour — with both looking correct.
    """
    from backend.core import md_ensemble

    src = inspect.getsource(md_ensemble.build_replica_package)
    spec = md_plan.replica_production_spec(
        _ctx(), total_steps=25_000_000, timestep_fs=4.0, previous="demo_00_reseed"
    )
    assert spec.name == "demo_01_production_100ns_k0"
    # The builder's own arithmetic, mirrored: 100 % of the steps in one segment.
    assert spec.percent == 100.0 and spec.scale is None
    assert spec.min_c1_paired == 0.90 and spec.min_wc_ref_relative == 0.25
    assert "_00_reseed" in src and "_01_production_" in src


def test_only_the_production_stage_accepts_a_hand_edit():
    """The reseed conf is written without an overrides pass, so an edit there is dropped.

    The table renders that column read-only rather than accepting an edit it would
    silently discard — the same reason PROTECTED_DIRECTIVES cells are locked.
    """
    rows = md_plan.replica_production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0
    )
    assert rows[0]["accepts_overrides"] is False
    assert rows[1]["accepts_overrides"] is True


def test_a_child_override_lands_on_slot_1_the_way_the_builder_reads_it():
    """`build_replica_package` applies `overrides_for_stage(stage_overrides, 1)`."""
    rows = md_plan.replica_production_stages(
        _ctx(fast=True),
        total_steps=1_000_000,
        timestep_fs=4.0,
        stage_overrides={"1": {"langevinDamping": "2.5"}},
    )
    assert rows[1]["params"]["langevindamping"] == "2.5"
    assert rows[1]["overridden"]["langevindamping"] == ["1", "2.5"]
    # And the reseed is untouched by it.
    assert rows[0]["overridden"] == {}


def test_a_child_keeps_its_elastic_network_when_one_was_asked_for():
    rows = md_plan.replica_production_stages(
        _ctx(fast=True),
        total_steps=1_000_000,
        timestep_fs=4.0,
        enm_file="demo_prod_k0.1.enm.extra",
    )
    files = rows[1]["params"]["extrabondsfile"]
    files = files if isinstance(files, list) else [files]
    assert any("enm.extra" in str(f) for f in files)


def test_a_continuation_carries_velocities_instead_of_redrawing_them():
    """Chaining a production off a completed production is a true continuation.

    Redrawing velocities on a warm NPT endpoint injects force-uncorrelated velocities
    that overflow the startup RATTLE constraint.
    """
    spawn = md_plan.replica_production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0
    )
    chain = md_plan.replica_production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0, continuation=True
    )
    assert "reinitvels" in spawn[0]["params"]
    assert chain[0]["params"].get("binvelocities") == "equilibrated.vel"
    assert chain[0]["stage"] == "Velocity continuation"


# ── The declash step-count defect (pinned, deliberately NOT fixed) ────────────


def test_declash_stages_run_half_their_intended_length():
    """DEFECT PIN — current behaviour, not desired behaviour.

    ``prepare_mgh_slow_release`` sizes the ladder's step counts from the REQUESTED fast
    flag (4 fs -> 1.2M steps per rung), but a declash design keeps ``fast=True`` while
    marking every segment ``gentle``, and a gentle segment runs at 2 fs.  So each rung
    simulates 2.4 ns instead of the intended 4.8 ns.

    Left in place on purpose: fixing it doubles the wall-clock of every declash relaxation
    and makes new runs non-comparable with every declash trajectory already on disk.  That
    is a deliberate decision, not a silent one.  The wizard DISPLAYS the real number
    (steps x the timestep the segment actually runs at), so the shortfall is visible.

    When the fix lands, this test should be inverted, not deleted.
    """
    rows = md_plan.relaxation_stages(_ctx(fast=True), gentle=True)
    ladder = [r for r in rows if r["role"] == "ladder"]
    assert all(r["timestep_fs"] == 2.0 for r in ladder)

    rung = [r for r in ladder if "_01_" in r["name"]]
    assert sum(r["ns"] for r in rung) == pytest.approx(2.4, abs=0.01)  # intended: 4.8

    healthy = [
        r
        for r in md_plan.relaxation_stages(_ctx(fast=True))
        if r["role"] == "ladder" and "_02_" in r["name"]
    ]
    assert sum(r["ns"] for r in healthy) == pytest.approx(4.8, abs=0.01)


# ── The endpoint: preset resolution and provenance ────────────────────────────


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def _plan(client, **body) -> dict:
    r = client.post("/api/md/protocol-plan", json={"kind": "relaxation", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_endpoint_reports_the_stage_count_the_builder_produces(client):
    plan = _plan(client, relax_preset="standard")
    _min_name, segments = P.mgh_slow_release_segments("demo", timestep_fs=4.0)
    assert plan["totals"]["n_stages"] == len(segments) + 1


def test_provenance_distinguishes_a_preset_default_from_a_user_choice(client):
    """Without this the wizard shows a number with no way to tell if changing it matters."""
    from_preset = _plan(client, relax_preset="literature")["request"]["padding_nm"]
    assert from_preset == {
        "value": 2.0,
        "provenance": "preset",
        "reason": "set by the Match the literature (Aksimentiev) preset",
    }

    from_user = _plan(client, relax_preset="literature", padding_nm=1.0)["request"][
        "padding_nm"
    ]
    assert from_user["value"] == 1.0 and from_user["provenance"] == "user"


def test_protocol_is_reported_as_derived_never_as_a_choice(client):
    entry = _plan(client, relax_preset="design_speed")["request"]["protocol"]
    assert entry["provenance"] == "derived"
    assert "never selected separately" in entry["reason"]


def test_screening_mode_is_reported_as_forced_with_what_it_overrode(client):
    """The panel's ion fields were live controls whose values prep then discarded."""
    plan = _plan(
        client, relax_preset="standard", salt_mode="screening", mg_conc_mM=50.0
    )
    mg = plan["request"]["mg_conc_mM"]
    assert mg["provenance"] == "forced"
    assert mg["value"] == 12.5
    assert mg["overridden_from"] == 50.0


def test_custom_salt_mode_leaves_the_ion_fields_alone(client):
    plan = _plan(client, relax_preset="standard", salt_mode="custom", mg_conc_mM=50.0)
    assert plan["request"]["mg_conc_mM"] == {
        "value": 50.0,
        "provenance": "user",
        "reason": "",
    }


def test_the_literature_preset_runs_the_papers_integrator_everywhere(client):
    plan = _plan(client, relax_preset="literature")
    assert plan["request"]["production_timestep_fs"]["value"] == 2.0
    assert all(s["params"]["timestep"] == "2" for s in plan["stages"][1:])
    assert all(s["params"]["rigidbonds"] == "all" for s in plan["stages"][1:])


def test_the_literature_preset_declares_the_carve_refusal_up_front(client):
    """Stated BEFORE anything is created — not discovered as a failed job later."""
    conds = {c["id"]: c for c in _plan(client, relax_preset="literature")["conditions"]}
    assert "settle" in conds["carve_refused"]["detail"]
    assert "carve_refused" not in {
        c["id"] for c in _plan(client, relax_preset="design_speed")["conditions"]
    }


def test_the_carve_refusal_is_a_policy_not_a_verdict(client):
    """It must NOT block creating the run.

    This plan has no idea whether the design fits — that needs a solvation profile, far
    too expensive for an endpoint re-requested on every keystroke. Marking it `blocking`
    made the wizard refuse to create ANY literature run, fitting or not, with no way
    forward. The fit check belongs to the launch pre-flight, which already runs it.
    """
    conds = {c["id"]: c for c in _plan(client, relax_preset="literature")["conditions"]}
    assert conds["carve_refused"]["kind"] != "blocking"
    assert not [
        c
        for c in _plan(client, relax_preset="literature")["conditions"]
        if c["kind"] == "blocking"
    ]


def test_the_carve_refusal_names_the_ways_forward(client):
    """A refusal the user cannot act on is just a wall.

    It must ALSO say that a run which does not fit is warned-and-attempted, not blocked —
    whether a system fits is a property of today's hardware, and the pre-flight is an
    estimate rather than a measurement.
    """
    detail = {
        c["id"]: c for c in _plan(client, relax_preset="literature")["conditions"]
    }["carve_refused"]["detail"]
    assert "padding" in detail  # lower it
    assert "oxDNA or mrDNA" in detail  # change resolution — the reference's own answer
    assert "RunPod or the cluster" in detail  # or run it somewhere bigger
    assert "run it anyway" in detail  # and you are never simply blocked


def test_the_literature_preset_LOCKS_the_carve_against_an_explicit_request(client):
    """Not an option — a carved run is a different experiment wearing this tier's name.

    Reported as `forced`, which is what makes the wizard render the control read-only with
    the reason rather than offering one that silently does nothing.
    """
    plan = _plan(client, relax_preset="literature", allow_water_shell_carve=True)
    entry = plan["request"]["allow_water_shell_carve"]
    assert entry["value"] is False
    assert entry["provenance"] == "forced"
    assert "owns this setting" in entry["reason"]
    # ...and the condition still stands, because the override did not take.
    assert "carve_refused" in {c["id"] for c in plan["conditions"]}


def test_locking_is_surgical_the_rest_of_the_tier_stays_overridable(client):
    """A preset is a starting point; only the naming-critical field is a cage."""
    plan = _plan(client, relax_preset="literature", padding_nm=1.0)
    assert plan["request"]["padding_nm"] == {
        "value": 1.0,
        "provenance": "user",
        "reason": "",
    }


def test_a_tier_that_permits_carving_reports_it_as_an_ordinary_choice(client):
    plan = _plan(client, relax_preset="design_speed", allow_water_shell_carve=False)
    assert plan["request"]["allow_water_shell_carve"] == {
        "value": False,
        "provenance": "user",
        "reason": "",
    }


def test_the_fast_preset_stops_settled_stages_and_the_literature_one_does_not(client):
    fast = {c["id"] for c in _plan(client, relax_preset="design_speed")["conditions"]}
    lit = {c["id"] for c in _plan(client, relax_preset="literature")["conditions"]}
    assert "early_stop" in fast and "early_stop_off" not in fast
    assert "early_stop_off" in lit and "early_stop" not in lit


def test_an_unknown_kind_is_rejected(client):
    r = client.post("/api/md/protocol-plan", json={"kind": "nonsense"})
    assert r.status_code == 400


def test_a_production_plan_needs_a_parent(client):
    r = client.post("/api/md/protocol-plan", json={"kind": "production"})
    assert r.status_code == 400
    assert "parent_job_id" in r.json()["detail"]


# ── The production plan, end to end ───────────────────────────────────────────

READY = "demo_04_300K_NPT_MGHH_only_p100"


@pytest.fixture()
def parent_job(tmp_path, monkeypatch):
    """A completed relaxation with a real package, so the plan can read it back."""
    import backend.api.routes_md as rm
    from backend.core.md_job import MdSegmentStatus, MdStatus, new_job

    monkeypatch.setattr(rm, "_workspace", lambda: tmp_path)
    job = new_job(
        "demo", "equilibrium_aware_namd", name_stem="demo", package_subdir="pkg"
    )
    job.status = MdStatus.completed
    job.prep_params = {
        "relax_preset": "literature",
        "mg_conc_mM": 12.5,
        "ion_conc_mM": 0.0,
    }
    job.segments = [
        MdSegmentStatus(
            name=READY,
            stage="300K NPT MgHH only",
            percent=100.0,
            steps=2_400_000,
            status="done",
        )
    ]
    job.save(tmp_path)

    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    for ext in ("coor", "vel", "xsc"):
        (pkg / "output" / f"{READY}.{ext}").write_text(ext)
    (pkg / "demo.psf").write_text(f"{224000:10d} !NATOM\n")
    (pkg / "manifest.json").write_text(
        json.dumps(
            {
                "name_stem": "demo",
                "protocol": "equilibrium_aware_namd",
                "relax_preset": "literature",
                "box_ang": [180.5, 190.25, 210.0],
                "mgh_extrabonds": True,
                "solvation": {
                    "padding_nm": 2.0,
                    "water_shell_nm": 0.0,
                    "carved": False,
                    "npt_allowed": True,
                    "sized_for_free_ns": 100.0,
                },
                "relax_protocol_settings": {"timestep_fs": 2.0},
                "fast_relaxation": {"enabled": False},
                "production_timestep_fs": 2.0,
                "minimization": {"name": "demo_00_min", "steps": 4800},
                "segments": [
                    {
                        "name": READY,
                        "stage": "300K NPT MgHH only",
                        "percent": 100.0,
                        "steps": 2_400_000,
                        "temp": 300.0,
                        "damping": 5.0,
                        "scale": None,
                        "npt": True,
                        "previous": "demo_03_k0p01_p100",
                    }
                ],
            }
        )
    )
    return job


def _prod_plan(client, parent_job, **body) -> dict:
    r = client.post(
        "/api/md/protocol-plan",
        json={"kind": "production", "parent_job_id": parent_job.job_id, **body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_the_production_plan_is_the_two_confs_the_child_package_contains(
    client, parent_job
):
    """Not the append route's three chunks — the wizard creates a replica package."""
    plan = _prod_plan(client, parent_job)
    assert [s["role"] for s in plan["stages"]] == ["reseed", "production"]
    assert plan["run_stage_index"] == 1
    assert plan["totals"]["n_stages"] == 2


def test_the_production_plan_carries_the_relaxation_stage_it_continues(
    client, parent_job
):
    plan = _prod_plan(client, parent_job)
    assert plan["source_stage"] == {
        "name": READY,
        "stage": "300K NPT MgHH only",
        "kind": "relaxation",
        "params": plan["source_stage"]["params"],
    }
    assert plan["continuation"] is False
    # Real directives, emitted by the same conf writer the ladder used — not a description.
    assert plan["source_stage"]["params"]["langevindamping"] == "5"
    # And the difference that matters is computed, not claimed.
    assert plan["comparison"]["langevindamping"] == ["5", "1"]


def test_the_production_plan_states_what_it_inherits_rather_than_offering_it(
    client, parent_job
):
    """A child hardlinks its parent's topology and copies its cell — none of it is choosable."""
    inh = _prod_plan(client, parent_job)["inherited"]
    assert inh["seed_checkpoint"] == READY
    assert inh["relax_preset"] == "literature"
    assert inh["box_ang"] == [180.5, 190.25, 210.0]
    assert inh["padding_nm"] == 2.0
    assert inh["mg_conc_mM"] == 12.5
    assert inh["ladder_timestep_fs"] == 2.0
    # Read from the package's own PSF, so GPU-resident is a fact rather than deferred.
    assert inh["n_atoms"] == 224_000


def test_an_untouched_production_setting_reports_where_it_really_came_from(
    client, parent_job
):
    """Without this every production control rendered with no chip at all."""
    req = _prod_plan(client, parent_job)["production_request"]
    # The package pinned 2 fs at prep; the create-request merge would have said 4.
    assert req["production_timestep_fs"] == {
        "value": 2.0,
        "provenance": "inherited",
        "reason": "recorded when the relaxation package was prepared",
    }
    assert req["length_ns"]["provenance"] == "default"
    assert req["length_ns"]["value"] == 100.0
    # 'auto' resolved against the parent's protocol, with the reason it decided that way.
    assert req["enm_restraints"] == {
        "value": "on",
        "provenance": "derived",
        "reason": req["enm_restraints"]["reason"],
    }
    assert "literature" in req["enm_restraints"]["reason"]


def test_a_touched_production_setting_reports_itself_as_the_users(client, parent_job):
    req = _prod_plan(
        client, parent_job, length_ns=25, langevin_damping=2.0, enm_restraints="off"
    )["production_request"]
    assert req["length_ns"] == {"value": 25.0, "provenance": "user", "reason": ""}
    assert req["langevin_damping"]["provenance"] == "user"
    assert req["enm_restraints"]["provenance"] == "user"


def test_the_production_integrator_axes_reach_the_previewed_conf(client, parent_job):
    """The stage table has to reflect the chosen axes, not the auto ones.

    Same defect class as the ladder's, fixed there in exp51: the table showed the auto
    values while the job ran the chosen ones.
    """
    plan = _prod_plan(
        client, parent_job, production_timestep_fs=2.0, production_rigid_bonds="none"
    )
    run = plan["stages"][plan["run_stage_index"]]
    assert run["params"]["timestep"] == "2"
    assert run["params"]["rigidbonds"] == "none"


def test_the_form_and_the_preview_agree_about_the_default_run_length(
    client, parent_job
):
    """`ProductionRequest` falls back to 1 ns, which would preview a run the form isn't
    offering. The wizard reads this number rather than carrying its own."""
    plan = _prod_plan(client, parent_job)
    assert plan["defaults"]["length_ns"] == 100.0
    assert plan["timestep_plan"]["length_ns"] == 100.0


def test_every_production_condition_names_the_control_that_owns_it(client, parent_job):
    """`source` is the ONLY link between a condition and a settings field.

    A source naming a private Python helper renders nowhere near the control the user has
    to change, which for `box_fit` (the one blocking condition here) means a refusal with
    nothing on screen to act on.
    """
    plan = _prod_plan(client, parent_job)
    by_id = {c["id"]: c.get("source", "") for c in plan["conditions"]}
    assert by_id["production_restraints"] == "ProductionRunRequest.enm_restraints"
    assert by_id["production_damping"] == "ProductionRunRequest.langevin_damping"
    assert by_id["box_fit"] == "ProductionRunRequest.length_ns"
    assert by_id["timestep_independence"] == "CreateJobRequest.production_timestep_fs"


def test_the_velocity_seed_is_declared_deferred_unless_it_is_pinned(client, parent_job):
    """It is drawn when the job is created, so the reseed column shows a placeholder."""
    keys = [d["key"] for d in _prod_plan(client, parent_job)["deferred"]]
    assert keys == ["seed"]
    assert _prod_plan(client, parent_job, seed=4242)["deferred"] == []


def test_a_hand_edit_on_the_production_stage_shows_up_as_a_departure(
    client, parent_job
):
    plan = _prod_plan(
        client, parent_job, stage_overrides={"1": {"langevinDamping": "3.5"}}
    )
    run = plan["stages"][plan["run_stage_index"]]
    assert run["params"]["langevindamping"] == "3.5"
    assert run["overridden"]["langevindamping"][1] == "3.5"


def test_a_production_plan_still_writes_nothing_to_disk(client, parent_job, tmp_path):
    """It is re-requested on every keystroke behind a 250 ms debounce."""
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    _prod_plan(client, parent_job, length_ns=7)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


# ── Chaining: a completed PRODUCTION as the parent ────────────────────────────
#
# The backend has always been able to (`_production_seed_checkpoint` branches on
# `run_kind`, `build_replica_package` stages the parent's restart set and preserves
# velocities).  What it did NOT do was describe it correctly: a chained plan read its
# chemistry off a production-only manifest and reported "unrecorded", ran the parent's
# production segment back through the LADDER's conf writer, and told the user its
# velocities would be redrawn — the opposite of what happens.

PROD_SEG = "demo_01_production_200ns_k0"


@pytest.fixture()
def chain_parent(tmp_path, monkeypatch, parent_job):
    """A completed production CHILD of `parent_job`, ready to be continued."""
    import backend.api.routes_md as rm
    from backend.core.md_job import MdSegmentStatus, MdStatus, new_job

    monkeypatch.setattr(rm, "_workspace", lambda: tmp_path)
    child = new_job(
        "demo",
        "equilibrium_aware_namd",
        name_stem="demo",
        package_subdir="prodpkg",
        parent_job_id=parent_job.job_id,
        ensemble_seed=1234,
        ensemble_index=0,
        run_kind="production",
    )
    child.status = MdStatus.completed
    child.segments = [
        MdSegmentStatus(
            name=PROD_SEG,
            stage="200 ns production replica",
            percent=100.0,
            steps=50_000_000,
            status="done",
        )
    ]
    child.save(tmp_path)

    pkg = child.package_dir(tmp_path)
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    for ext in ("coor", "vel", "xsc"):
        (pkg / "output" / f"{PROD_SEG}.{ext}").write_text(ext)
    (pkg / "demo.psf").write_text(f"{224000:10d} !NATOM\n")
    # A production-only manifest: no relax_preset, no solvation, no ion concentrations.
    # That absence is the whole point — the plan has to walk to the root relaxation.
    (pkg / "manifest.json").write_text(
        json.dumps(
            {
                "name_stem": "demo",
                "protocol": "equilibrium_aware_namd",
                "box_ang": [180.5, 190.25, 210.0],
                "mgh_extrabonds": True,
                "production_recipe": {
                    "version": 2,
                    "langevin_damping": 2.0,
                    "enm_restraints": True,
                    "enm_k": 0.1,
                    "enm_file": "demo_prod_k0.1.enm.extra",
                },
                "ensemble": {
                    "parent_job_id": parent_job.job_id,
                    "seed": 1234,
                    "length_ns": 200.0,
                    "steps": 50_000_000,
                    "timestep_fs": 4.0,
                },
                "minimization": {"name": "demo_00_reseed", "steps": 0},
                "segments": [
                    {
                        "name": PROD_SEG,
                        "stage": "200 ns production replica",
                        "percent": 100.0,
                        "steps": 50_000_000,
                        "temp": 300.0,
                        "damping": 2.0,
                        "scale": None,
                        "npt": True,
                        "previous": "demo_00_reseed",
                        "timestep_fs": 4.0,
                    }
                ],
            }
        )
    )
    return child


def test_a_chained_plan_says_it_is_a_continuation(client, chain_parent):
    plan = _prod_plan(client, chain_parent)
    assert plan["continuation"] is True
    assert plan["source_stage"]["kind"] == "production"
    assert plan["source_stage"]["name"] == PROD_SEG
    # The bridge conf preserves velocities instead of redrawing them.
    assert plan["stages"][0]["stage"] == "Velocity continuation"
    assert plan["stages"][0]["params"]["binvelocities"] == "equilibrated.vel"
    assert "reinitvels" not in plan["stages"][0]["params"]


def test_a_chained_plan_reads_its_chemistry_from_the_ROOT_relaxation(
    client, chain_parent, parent_job
):
    """A production child's manifest has no preset, no solvation and no ions.

    Reading the immediate parent's blindly is what made a chained plan report
    "the parent's protocol (unrecorded)" and blank ion concentrations.
    """
    inh = _prod_plan(client, chain_parent)["inherited"]
    assert inh["continuation"] is True
    assert inh["root_job_id"] == parent_job.job_id
    assert inh["chain_position"] == 2
    assert inh["relax_preset"] == "literature"
    assert inh["mg_conc_mM"] == 12.5
    assert inh["padding_nm"] == 2.0
    assert inh["parent_length_ns"] == 200.0


def test_a_continuation_inherits_the_network_the_run_it_continues_was_using(
    client, chain_parent
):
    """Otherwise one trajectory is restrained for its first leg and free for its second.

    `auto` used to look for a relaxation preset, find none on a production manifest, and
    fall through to "unrestrained" — silently dropping the network halfway along a chain.
    """
    req = _prod_plan(client, chain_parent)["production_request"]
    assert req["enm_restraints"]["value"] == "on"
    assert "continues" in req["enm_restraints"]["reason"]
    # …and the thermostat coupling it was running under, for the same reason.
    assert req["langevin_damping"]["value"] == 2.0


def test_an_explicit_choice_still_beats_the_inherited_one(client, chain_parent):
    req = _prod_plan(client, chain_parent, enm_restraints="off", langevin_damping=1.0)[
        "production_request"
    ]
    assert req["enm_restraints"]["value"] == "off"
    assert req["langevin_damping"]["value"] == 1.0


def test_the_chain_reference_column_uses_the_PRODUCTION_conf_writer(
    client, chain_parent
):
    """Running a production segment back through the ladder's writer would invent
    differences that are artefacts of the wrong emitter, not real changes."""
    plan = _prod_plan(client, chain_parent)
    ref = plan["source_stage"]["params"]
    # `stepspercycle` is one of the six ladder-vs-production asymmetries; both columns are
    # productions here, so it must agree rather than showing the ladder's 20.
    run = plan["stages"][plan["run_stage_index"]]["params"]
    assert ref["stepspercycle"] == run["stepspercycle"]
    assert ref["pairlistdist"] == run["pairlistdist"]
    # And the annotated ladder-vs-production notes are suppressed entirely.
    assert plan["asymmetries"] == []


def test_a_continuation_says_its_frames_are_correlated_with_the_parents(
    client, chain_parent
):
    """The single most consequential sentence on the screen, and it is the OPPOSITE of
    the relaxation case — treating two legs of one trajectory as two samples
    double-counts."""
    conds = {c["id"]: c for c in _prod_plan(client, chain_parent)["conditions"]}
    assert "extends that trajectory" in conds["seed_checkpoint"]["detail"]
    assert "correlated" in conds["seed_checkpoint"]["detail"]
    # …and the seed's meaning changes with it.
    detail = _prod_plan(client, chain_parent)["deferred"][0]["detail"]
    assert "does not choose them" in detail


def test_a_chain_states_the_health_of_the_frame_it_continues(client, chain_parent):
    """`_completed_production_checkpoint` has NO health gate, unlike the relaxation path.

    Say so rather than implying the checkpoint was vetted.
    """
    conds = {c["id"]: c for c in _prod_plan(client, chain_parent)["conditions"]}
    assert conds["chain_source_health"]["kind"] == "info"
    assert "No health sample" in conds["chain_source_health"]["detail"]


def test_a_degraded_chain_source_is_a_warning_not_a_refusal(
    client, chain_parent, tmp_path
):
    from backend.core.md_job import MdHealthSample

    chain_parent.health_samples = [
        MdHealthSample(
            segment=PROD_SEG,
            stage="200 ns production replica",
            wall_time=0.0,
            c1_paired_fraction=0.42,
            passed=False,
        )
    ]
    chain_parent.save(tmp_path)
    conds = {c["id"]: c for c in _prod_plan(client, chain_parent)["conditions"]}
    assert conds["chain_source_health"]["kind"] == "warning"
    assert "42%" in conds["chain_source_health"]["detail"]
    # Warned, never blocked — the checkpoint is on disk and the user may want it anyway.
    assert conds["chain_source_health"].get("ok") is not False


def test_the_plan_writes_nothing_to_disk(client, tmp_path, monkeypatch):
    """It has to be safe to re-request on every keystroke behind a short debounce."""
    import backend.api.routes_md as rm

    monkeypatch.setattr(rm, "_workspace", lambda: tmp_path)
    _plan(client, relax_preset="literature")
    assert list(tmp_path.iterdir()) == []


# ── Production restraints + thermostat (the literature-comparability fixes) ───


def test_production_runs_a_weaker_thermostat_than_the_ladder():
    """The ladder's 5 ps^-1 is an EQUILIBRATION value.

    Carrying it into production overdamps the dynamics, so diffusion, relaxation and
    correlation times, ion residence and breathing kinetics are all scaled by something
    unrelated to the system — and the group's production runs a NADOC trajectory would be
    compared against use ~1. Equilibrium averages are unaffected, which is why this went
    unnoticed. See project_periodic_md.md H003.
    """
    ladder = md_plan.relaxation_stages(_ctx(fast=True))
    prod = md_plan.production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0
    )
    assert ladder[-1]["params"]["langevindamping"] == f"{P.LADDER_LANGEVIN_DAMPING:g}"
    assert prod[0]["params"]["langevindamping"] == f"{P.PRODUCTION_LANGEVIN_DAMPING:g}"
    assert P.PRODUCTION_LANGEVIN_DAMPING < P.LADDER_LANGEVIN_DAMPING


def test_the_damping_split_shows_up_as_a_production_asymmetry():
    ladder = md_plan.relaxation_stages(_ctx(fast=True))
    prod = md_plan.production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0
    )
    diff = md_plan.stage_diff(ladder[-1]["params"], prod[0]["params"])
    assert diff["langevindamping"] == ["5", "1"]


def test_a_production_run_can_keep_an_elastic_network():
    """The published 'unrestrained' productions are not unrestrained."""
    prod = md_plan.production_stages(
        _ctx(fast=True),
        total_steps=1_000_000,
        timestep_fs=4.0,
        enm_file="demo_prod_k0.1.enm.extra",
    )
    files = prod[0]["params"]["extrabondsfile"]
    assert files == ["mgh_extrabonds.txt", "demo_prod_k0.1.enm.extra"]
    assert prod[0]["params"]["extrabonds"] == "on"


def test_the_network_turns_extrabonds_on_even_without_the_magnesium_shell():
    ctx = md_plan.PlanContext(name_stem="demo", mgh_extrabonds=False)
    prod = md_plan.production_stages(
        ctx, total_steps=1000, timestep_fs=4.0, enm_file="demo_prod_k0.1.enm.extra"
    )
    assert prod[0]["params"]["extrabonds"] == "on"
    assert prod[0]["params"]["extrabondsfile"] == "demo_prod_k0.1.enm.extra"


def test_production_stays_unrestrained_when_no_network_is_asked_for():
    """The historical behaviour has to remain reachable, or old trajectories stop being
    comparable with new ones."""
    prod = md_plan.production_stages(_ctx(fast=True), total_steps=1000, timestep_fs=4.0)
    assert prod[0]["params"]["extrabondsfile"] == "mgh_extrabonds.txt"


# ── protocol_fidelity is the package's own methods delta ──────────────────────


def _items(**kw):
    base = dict(fast=True, carved=False, padding_nm=2.0, charge_audit={})
    return {d["item"] for d in P.protocol_fidelity(**{**base, **kw})["deviations"]}


def test_every_always_on_deviation_is_declared():
    """These are true of EVERY package and were all missing, which made the manifest
    read as a shorter delta than it is — the exact failure this block exists to stop."""
    items = _items()
    assert "langevinDamping (production)" in items
    assert "stepspercycle / pairlistdist" in items
    assert "production barostat" in items
    assert "stage chunking" in items


def test_early_stop_is_declared_only_when_it_is_on():
    assert "stage length" in _items(early_stop=True)
    assert "stage length" not in _items(early_stop=False)


def test_the_early_stop_deviation_says_the_ladder_was_shortened():
    d = next(
        x
        for x in P.protocol_fidelity(
            fast=True, carved=False, padding_nm=2.0, charge_audit={}, early_stop=True
        )["deviations"]
        if x["item"] == "stage length"
    )
    assert "TRUNCATED" in d["ours"]
    assert "19.2 ns" in d["why"]  # names what the nominal figure would have been


def test_production_restraints_are_declared_either_way():
    """Both answers are a deviation: none at all differs from the published runs, and
    the network NADOC can build is sparser than theirs."""
    assert "production restraints" in _items(production_enm=False)
    assert "production elastic network" in _items(production_enm=True)
    # A relaxation package has not chosen yet, so it declares neither.
    assert not ({"production restraints", "production elastic network"} & _items())


def test_the_unrestrained_deviation_cites_the_papers():
    d = next(
        x
        for x in P.protocol_fidelity(
            fast=True,
            carved=False,
            padding_nm=2.0,
            charge_audit={},
            production_enm=False,
        )["deviations"]
        if x["item"] == "production restraints"
    )
    assert "PNAS" in d["theirs"] and "NAR" in d["theirs"]
    assert "SOFTER" in d["why"]


def test_the_chunking_deviation_reports_the_real_split():
    d = next(
        x
        for x in P.protocol_fidelity(
            fast=True,
            carved=False,
            padding_nm=2.0,
            charge_audit={},
            chunk_pcts=P.LADDER_CHUNK_PCTS,
        )["deviations"]
        if x["item"] == "stage chunking"
    )
    assert f"{len(P.LADDER_CHUNK_PCTS)} chunks" in d["ours"]


def test_the_declash_trigger_is_flagged_for_re_audit():
    """The gentle tier was set by a 25 ps probe and costs a doubled ladder; the note has
    to survive refactors, because the arithmetic bug and the trigger must be settled
    together."""
    src = inspect.getsource(P.prepare_mgh_slow_release)
    assert "MARKED FOR RE-AUDIT" in src
    assert "exp49" in src


# ── Per-stage overrides: every parameter of every stage is editable ───────────


def test_an_override_replaces_a_directive_in_place():
    """In place, so the conf keeps its reading order and its comments."""
    conf = "timestep           2\nrigidBonds         all\n"
    got = md_plan.parse_conf_directives(P.apply_conf_overrides(conf, {"timestep": "4"}))
    assert got == {"timestep": "4", "rigidbonds": "all"}


def test_an_absent_directive_is_appended_under_a_marked_heading():
    out = P.apply_conf_overrides("timestep 2\n", {"myKnob": "7"})
    assert "myKnob             7" in out
    assert "Per-stage overrides" in out  # never silently mixed in with the protocol


def test_a_null_override_deletes_the_directive():
    """How a user turns OFF something the protocol turned on."""
    got = md_plan.parse_conf_directives(
        P.apply_conf_overrides(
            "timestep 2\nlangevinPiston on\n", {"langevinPiston": None}
        )
    )
    assert got == {"timestep": "2"}


def test_no_overrides_returns_the_conf_untouched():
    """The writers carry byte-identical guarantees the ensemble path depends on."""
    conf = "timestep           2\n# a comment\n"
    assert P.apply_conf_overrides(conf, None) is conf
    assert P.apply_conf_overrides(conf, {}) is conf


def test_overriding_a_repeated_directive_replaces_the_whole_set():
    """'these files, INSTEAD of those' — a partial replacement would be ambiguous."""
    conf = "extraBondsFile     a.txt\nextraBondsFile     b.txt\n"
    got = md_plan.parse_conf_directives(
        P.apply_conf_overrides(conf, {"extraBondsFile": "c.txt"})
    )
    assert got["extrabondsfile"] == "c.txt"


@pytest.mark.parametrize("key", sorted(P.PROTECTED_DIRECTIVES))
def test_plumbing_directives_are_refused(key):
    """Not physics — the names the runner and the restart chain address a stage by.
    Rewriting one detaches the stage from its job instead of changing what it simulates."""
    with pytest.raises(ValueError, match="cannot be overridden"):
        P.apply_conf_overrides("timestep 2\n", {key: "x"})


def test_the_wildcard_is_merged_first_so_a_stage_entry_refines_it():
    """Which is what makes "this for the whole ladder, except stage 3" expressible."""
    ov = {"*": {"timestep": "2", "run": "10"}, "3": {"timestep": "1"}}
    assert P.overrides_for_stage(ov, 3) == {"timestep": "1", "run": "10"}
    assert P.overrides_for_stage(ov, 7) == {"timestep": "2", "run": "10"}
    assert P.overrides_for_stage(None, 3) == {}


def test_overrides_are_keyed_by_index_not_name():
    """A stage's NAME carries the design stem, which the wizard does not know until prep
    and which would change under it. The index is stable between the preview and the run
    because both compute the ladder from the same builder."""
    ov = {"3": {"run": "50"}}
    assert P.overrides_for_stage(ov, 3) == {"run": "50"}
    assert P.overrides_for_stage(ov, "demo_03_300K_NPT_ENM_k0p01_p10") == {}


def test_an_edited_stage_reports_what_the_protocol_would_have_said():
    """The second highlight. `diff_vs_previous` is "what moves as the ladder advances";
    this is "where have I departed from the protocol", which is the reviewer's question."""
    rows = md_plan.relaxation_stages(
        _ctx(fast=True), stage_overrides={"3": {"langevinDamping": "2"}}
    )
    assert rows[3]["overridden"] == {"langevindamping": ["5", "2"]}
    assert rows[3]["params"]["langevindamping"] == "2"
    # ...and only that stage.
    assert all(not r["overridden"] for i, r in enumerate(rows) if i != 3)


def test_a_wildcard_override_marks_every_stage():
    rows = md_plan.relaxation_stages(
        _ctx(fast=True), stage_overrides={"*": {"langevinDamping": "2"}}
    )
    assert all(r["overridden"] == {"langevindamping": ["5", "2"]} for r in rows[1:])


def test_an_unedited_plan_marks_nothing_overridden():
    assert all(not r["overridden"] for r in md_plan.relaxation_stages(_ctx(fast=True)))


def test_production_stages_take_overrides_too():
    rows = md_plan.production_stages(
        _ctx(fast=True),
        total_steps=1_000_000,
        timestep_fs=4.0,
        stage_overrides={"1": {"langevinDamping": "5"}},
    )
    assert rows[0]["overridden"] == {"langevindamping": ["1", "5"]}


def test_a_hand_edit_is_declared_as_a_protocol_deviation():
    """The point of the whole exercise: an edit is a departure from EVERY protocol, so it
    has to appear in the package's own methods delta rather than only in the confs."""
    d = next(
        x
        for x in P.protocol_fidelity(
            fast=True,
            carved=False,
            padding_nm=2.0,
            charge_audit={},
            stage_overrides={"*": {"timestep": "2"}},
        )["deviations"]
        if x["item"] == "hand-edited stages"
    )
    assert d["overrides"] == {"*": {"timestep": "2"}}
    assert "deliberate departure" in d["why"]


def test_no_edits_means_no_hand_edited_deviation():
    assert "hand-edited stages" not in _items()


def test_the_plan_endpoint_rejects_a_protected_override(client):
    r = client.post(
        "/api/md/protocol-plan",
        json={"kind": "relaxation", "stage_overrides": {"1": {"outputName": "x"}}},
    )
    assert r.status_code == 400
    assert "cannot be overridden" in r.json()["detail"]


def test_the_plan_endpoint_reports_which_stages_were_edited(client):
    plan = _plan(
        client, stage_overrides={"*": {"langevinDamping": "2"}, "3": {"run": "9"}}
    )
    assert plan["edited_stages"] == ["*", "3"]
    assert "outputname" in plan["protected_directives"]
