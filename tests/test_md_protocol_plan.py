"""The computed protocol plan behind the Job Wizard.

The theme of this file: the plan must never DESCRIBE the protocol, it must REPORT it.
Several tests below deliberately assert a computed value against the code that computes
it, rather than against a literal — a literal here is exactly the drift the wizard exists
to remove (the notes said 12 ladder segments while the code built 20, and said the ladder
barostat was 200/100 fs when it is 1000/500).
"""
from __future__ import annotations

import inspect

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
        "extraBondsFile     mgh_extrabonds.txt\nextraBondsFile     demo_k0.5.enm.extra\n")
    assert got["extrabondsfile"] == ["mgh_extrabonds.txt", "demo_k0.5.enm.extra"]


def test_parse_conf_directives_drops_comments_and_blank_lines():
    got = md_plan.parse_conf_directives("# a comment\n\ncutoff  10.0   # trailing\n")
    assert got == {"cutoff": "10.0"}


# ── Stage table ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fast", [True, False])
def test_plan_lists_every_ladder_segment_plus_minimisation(fast):
    """Asserted against the builder, never against a literal count."""
    _min_name, segments = P.mgh_slow_release_segments(
        "demo", timestep_fs=4.0 if fast else 2.0)
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

    watched = ("timestep", "rigidbonds", "fullelectfrequency", "stepspercycle",
               "pairlistdist", "cutoff", "switchdist", "langevinpistonperiod",
               "langevinpistondecay", "langevindamping", "constraints", "run")
    for spec in segments:
        written = md_plan.parse_conf_directives(P._segment_conf(
            spec, "demo", ctx.box, ctx.mgh_extrabonds, fast=ctx.fast))
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
    settle = [r for r in md_plan.relaxation_stages(_ctx(fast=True))
              if r["role"] == "settle"]
    assert len(settle) == 1
    params = settle[0]["params"]
    assert params["constraints"] == "on"
    assert params["conskcol"] == "B"
    assert "fixedatoms" not in params
    assert "extrabondsfile" not in params or ".enm.extra" not in params["extrabondsfile"]


def test_restraint_ladder_steps_down_through_the_extrabonds_file():
    """k = 0.5 -> 0.1 -> 0.01 -> none, visible only in extraBondsFile."""
    seen = []
    for row in md_plan.relaxation_stages(_ctx(fast=True))[1:]:
        files = row["params"].get("extrabondsfile")
        files = files if isinstance(files, list) else [files]
        enm = [f for f in files if f and "enm.extra" in f]
        if not seen or (enm and enm[-1] != seen[-1]):
            seen.extend(enm[-1:] or [])
    assert seen == ["demo_k0.5.enm.extra", "demo_k0.1.enm.extra", "demo_k0.01.enm.extra"]
    assert not any("enm.extra" in str(f)
                   for f in [md_plan.relaxation_stages(_ctx(fast=True))[-1]["params"]
                             .get("extrabondsfile")])


# ── Diffs ─────────────────────────────────────────────────────────────────────

def test_stage_diff_is_empty_for_the_first_stage():
    assert md_plan.stage_diff(None, {"timestep": "4"}) == {}


def test_stage_diff_reports_appearance_and_disappearance():
    """A directive that only exists on one side is the MOST important kind of difference.

    The barostat block vanishing, or the elastic network appearing, is precisely what a
    stage-to-stage comparison is for.  Dropping those would be the worst omission.
    """
    got = md_plan.stage_diff({"langevinpiston": "on", "margin": "3"},
                             {"langevinpiston": "off"})
    assert got == {"langevinpiston": ["on", "off"], "margin": ["3", "(absent)"]}


def test_stage_diff_ignores_output_bookkeeping():
    """Output paths differ on every single stage; leaving them in buries the physics."""
    got = md_plan.stage_diff({"outputname": "a", "dcdfile": "a.dcd", "timestep": "2"},
                             {"outputname": "b", "dcdfile": "b.dcd", "timestep": "4"})
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
        "run", "dcdfreq", "outputenergies", "xstfreq", "restartfreq"}


# ── Conditions that skip or alter a stage ─────────────────────────────────────

def test_a_carved_package_loses_the_settle_stage_and_the_barostat():
    """The two costs of a water-shell carve, which nothing surfaced before."""
    full = md_plan.relaxation_stages(_ctx(fast=True))
    carved = md_plan.relaxation_stages(_ctx(fast=True, carved=True), nvt_only=True)

    assert any(r["role"] == "settle" for r in full)
    assert not any(r["role"] == "settle" for r in carved)
    assert len(carved) == len(full) - 1
    assert all(r["params"]["langevinpiston"] == "off" for r in carved[1:])

    conds = {c["id"]: c for c in md_plan.protocol_conditions(
        carved=True, gbis=False, force_soft=False, gentle_ladder=False,
        early_stop=True, gpu_resident_mode="auto", stages=carved)}
    assert "settle_skipped" in conds and "barostat_off" in conds


def test_the_soft_start_lands_on_the_first_stage_whose_atoms_move():
    """Not the settle stage — nothing can strain-relieve while the solute is restrained."""
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    gentle = [r for r in rows[1:] if r["gentle"]]
    assert len(gentle) == 1
    assert gentle[0]["role"] == "ladder"
    assert gentle[0]["restraint_ref_file"] is None
    assert gentle[0]["timestep_fs"] == 2.0

    conds = {c["id"] for c in md_plan.protocol_conditions(
        carved=False, gbis=False, force_soft=False, gentle_ladder=False,
        early_stop=True, gpu_resident_mode="auto", stages=rows)}
    assert "soft_start" in conds


def test_gpu_resident_is_reported_as_conditional_until_the_atom_count_is_known():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    ladder = next(r for r in rows if r["role"] == "ladder")
    assert "gpuresident" in ladder["conditional_params"]
    assert str(P._RESIDENT_MIN_ATOMS) in ladder["conditional_params"]["gpuresident"].replace(",", "")


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
    conds = {c["id"]: c for c in md_plan.protocol_conditions(
        carved=False, gbis=False, force_soft=False, gentle_ladder=False,
        early_stop=True, gpu_resident_mode="auto", stages=rows)}
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
    conds = {c["id"] for c in md_plan.protocol_conditions(
        carved=False, gbis=False, force_soft=False, gentle_ladder=False,
        early_stop=False, gpu_resident_mode="auto", stages=rows)}
    assert "early_stop_off" in conds and "early_stop" not in conds


# ── Deferred values ───────────────────────────────────────────────────────────

def test_minimisation_steps_are_declared_a_floor_not_a_value():
    notes = {n["key"]: n for n in md_plan.deferred_notes(
        minimize_steps=4_800, n_atoms=None, padding_nm=2.0)}
    assert "minimize" in notes
    detail = notes["minimize"]["detail"]
    assert f"{P.minimize_steps_for_atoms(224_000, 4_800):,}" in detail
    assert str(P.MIN_STEPS_PER_ATOMS) in detail


def test_a_known_atom_count_removes_the_minimisation_caveat():
    notes = {n["key"] for n in md_plan.deferred_notes(
        minimize_steps=4_800, n_atoms=224_000, padding_nm=2.0)}
    assert "minimize" not in notes
    assert "cellBasisVector" in notes


def test_the_cell_is_always_deferred_and_never_shown_as_a_zero_box():
    rows = md_plan.relaxation_stages(_ctx(fast=True))
    for row in rows:
        assert not (set(row["params"]) & md_plan.BOX_KEYS)


# ── Production ────────────────────────────────────────────────────────────────

def test_production_chunks_split_the_requested_length_exactly():
    rows = md_plan.production_stages(_ctx(fast=True), total_steps=25_000_000,
                                     timestep_fs=4.0)
    assert [r["steps"] for r in rows] == [2_500_000, 10_000_000, 12_500_000]
    assert sum(r["ns"] for r in rows) == pytest.approx(100.0)


def test_production_names_and_labels_pin_the_shared_builder():
    """These strings are user-visible (job list, timeline) and reach the manifest."""
    spec = md_plan.production_segment_spec(
        "demo", stage_idx=5, pct=50.0, frac=0.40, total_steps=25_000_000,
        timestep_fs=4.0, previous="demo_04_300K_NPT_MGHH_only_p100")
    assert spec.name == "demo_05_production_100ns_k0_p50"
    assert spec.stage == "100 ns fast production run"
    assert spec.dcd_freq == P.PRODUCTION_DCD_FREQ
    assert spec.scale is None and spec.min_wc_ref_relative == 0.25


@pytest.mark.parametrize("dt,label", [(4.0, "fast"), (2.0, "medium"), (1.0, "conservative")])
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
        total_steps=25_000_000, timestep_fs=4.0, stage_idx=5)
    found = {a["key"]: (a["relaxation"], a["production"])
             for a in md_plan.production_asymmetries(
                 ladder[-1]["params"], prod[0]["params"])}

    assert found["fullelectfrequency"] == ("2", "1")
    assert found["stepspercycle"] == ("20", "10")
    assert found["pairlistdist"] == ("13.5", "12.0")
    assert found["langevinpistonperiod"] == ("1000.0", "200.0")
    assert found["langevinpistondecay"] == ("500.0", "100.0")
    assert all(a["note"] for a in md_plan.production_asymmetries(
        ladder[-1]["params"], prod[0]["params"]))


def test_an_asymmetry_that_stops_existing_stops_being_reported():
    """So aligning the two protocols later makes the row vanish rather than lie."""
    same = {"stepspercycle": "10", "fullelectfrequency": "1"}
    assert md_plan.production_asymmetries(same, dict(same)) == []


def test_production_carries_no_elastic_network():
    prod = md_plan.production_stages(_ctx(fast=True), total_steps=1_000_000,
                                     timestep_fs=4.0)
    files = prod[0]["params"].get("extrabondsfile")
    files = files if isinstance(files, list) else [files]
    assert not any("enm.extra" in str(f) for f in files)
    assert prod[0]["params"]["constraints"] == "off"


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
    assert sum(r["ns"] for r in rung) == pytest.approx(2.4, abs=0.01)   # intended: 4.8

    healthy = [r for r in md_plan.relaxation_stages(_ctx(fast=True))
               if r["role"] == "ladder" and "_02_" in r["name"]]
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
    assert from_preset == {"value": 2.0, "provenance": "preset",
                           "reason": "set by the Match the literature (Aksimentiev) preset"}

    from_user = _plan(client, relax_preset="literature",
                      padding_nm=1.0)["request"]["padding_nm"]
    assert from_user["value"] == 1.0 and from_user["provenance"] == "user"


def test_protocol_is_reported_as_derived_never_as_a_choice(client):
    entry = _plan(client, relax_preset="design_speed")["request"]["protocol"]
    assert entry["provenance"] == "derived"
    assert "never selected separately" in entry["reason"]


def test_screening_mode_is_reported_as_forced_with_what_it_overrode(client):
    """The panel's ion fields were live controls whose values prep then discarded."""
    plan = _plan(client, relax_preset="standard", salt_mode="screening", mg_conc_mM=50.0)
    mg = plan["request"]["mg_conc_mM"]
    assert mg["provenance"] == "forced"
    assert mg["value"] == 12.5
    assert mg["overridden_from"] == 50.0


def test_custom_salt_mode_leaves_the_ion_fields_alone(client):
    plan = _plan(client, relax_preset="standard", salt_mode="custom", mg_conc_mM=50.0)
    assert plan["request"]["mg_conc_mM"] == {"value": 50.0, "provenance": "user",
                                             "reason": ""}


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
        c["id"] for c in _plan(client, relax_preset="design_speed")["conditions"]}


def test_the_carve_refusal_is_a_policy_not_a_verdict(client):
    """It must NOT block creating the run.

    This plan has no idea whether the design fits — that needs a solvation profile, far
    too expensive for an endpoint re-requested on every keystroke. Marking it `blocking`
    made the wizard refuse to create ANY literature run, fitting or not, with no way
    forward. The fit check belongs to the launch pre-flight, which already runs it.
    """
    conds = {c["id"]: c for c in _plan(client, relax_preset="literature")["conditions"]}
    assert conds["carve_refused"]["kind"] != "blocking"
    assert not [c for c in _plan(client, relax_preset="literature")["conditions"]
                if c["kind"] == "blocking"]


def test_the_carve_refusal_names_the_ways_forward(client):
    """A refusal the user cannot act on is just a wall.

    It must ALSO say that a run which does not fit is warned-and-attempted, not blocked —
    whether a system fits is a property of today's hardware, and the pre-flight is an
    estimate rather than a measurement.
    """
    detail = {c["id"]: c for c in
              _plan(client, relax_preset="literature")["conditions"]}["carve_refused"]["detail"]
    assert "padding" in detail                       # lower it
    assert "oxDNA or mrDNA" in detail                # change resolution — the reference's own answer
    assert "RunPod or the cluster" in detail         # or run it somewhere bigger
    assert "run it anyway" in detail                 # and you are never simply blocked


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
    assert plan["request"]["padding_nm"] == {"value": 1.0, "provenance": "user", "reason": ""}


def test_a_tier_that_permits_carving_reports_it_as_an_ordinary_choice(client):
    plan = _plan(client, relax_preset="design_speed", allow_water_shell_carve=False)
    assert plan["request"]["allow_water_shell_carve"] == {
        "value": False, "provenance": "user", "reason": ""}


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
    prod = md_plan.production_stages(_ctx(fast=True), total_steps=1_000_000,
                                     timestep_fs=4.0)
    assert ladder[-1]["params"]["langevindamping"] == f"{P.LADDER_LANGEVIN_DAMPING:g}"
    assert prod[0]["params"]["langevindamping"] == f"{P.PRODUCTION_LANGEVIN_DAMPING:g}"
    assert P.PRODUCTION_LANGEVIN_DAMPING < P.LADDER_LANGEVIN_DAMPING


def test_the_damping_split_shows_up_as_a_production_asymmetry():
    ladder = md_plan.relaxation_stages(_ctx(fast=True))
    prod = md_plan.production_stages(_ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0)
    diff = md_plan.stage_diff(ladder[-1]["params"], prod[0]["params"])
    assert diff["langevindamping"] == ["5", "1"]


def test_a_production_run_can_keep_an_elastic_network():
    """The published 'unrestrained' productions are not unrestrained."""
    prod = md_plan.production_stages(
        _ctx(fast=True), total_steps=1_000_000, timestep_fs=4.0,
        enm_file="demo_prod_k0.1.enm.extra")
    files = prod[0]["params"]["extrabondsfile"]
    assert files == ["mgh_extrabonds.txt", "demo_prod_k0.1.enm.extra"]
    assert prod[0]["params"]["extrabonds"] == "on"


def test_the_network_turns_extrabonds_on_even_without_the_magnesium_shell():
    ctx = md_plan.PlanContext(name_stem="demo", mgh_extrabonds=False)
    prod = md_plan.production_stages(ctx, total_steps=1000, timestep_fs=4.0,
                                     enm_file="demo_prod_k0.1.enm.extra")
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
    d = next(x for x in P.protocol_fidelity(
        fast=True, carved=False, padding_nm=2.0, charge_audit={},
        early_stop=True)["deviations"] if x["item"] == "stage length")
    assert "TRUNCATED" in d["ours"]
    assert "19.2 ns" in d["why"]          # names what the nominal figure would have been


def test_production_restraints_are_declared_either_way():
    """Both answers are a deviation: none at all differs from the published runs, and
    the network NADOC can build is sparser than theirs."""
    assert "production restraints" in _items(production_enm=False)
    assert "production elastic network" in _items(production_enm=True)
    # A relaxation package has not chosen yet, so it declares neither.
    assert not ({"production restraints", "production elastic network"} & _items())


def test_the_unrestrained_deviation_cites_the_papers():
    d = next(x for x in P.protocol_fidelity(
        fast=True, carved=False, padding_nm=2.0, charge_audit={},
        production_enm=False)["deviations"] if x["item"] == "production restraints")
    assert "PNAS" in d["theirs"] and "NAR" in d["theirs"]
    assert "SOFTER" in d["why"]


def test_the_chunking_deviation_reports_the_real_split():
    d = next(x for x in P.protocol_fidelity(
        fast=True, carved=False, padding_nm=2.0, charge_audit={},
        chunk_pcts=P.LADDER_CHUNK_PCTS)["deviations"] if x["item"] == "stage chunking")
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
    assert "Per-stage overrides" in out       # never silently mixed in with the protocol


def test_a_null_override_deletes_the_directive():
    """How a user turns OFF something the protocol turned on."""
    got = md_plan.parse_conf_directives(
        P.apply_conf_overrides("timestep 2\nlangevinPiston on\n", {"langevinPiston": None}))
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
        P.apply_conf_overrides(conf, {"extraBondsFile": "c.txt"}))
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
        _ctx(fast=True), stage_overrides={"3": {"langevinDamping": "2"}})
    assert rows[3]["overridden"] == {"langevindamping": ["5", "2"]}
    assert rows[3]["params"]["langevindamping"] == "2"
    # ...and only that stage.
    assert all(not r["overridden"] for i, r in enumerate(rows) if i != 3)


def test_a_wildcard_override_marks_every_stage():
    rows = md_plan.relaxation_stages(_ctx(fast=True),
                                     stage_overrides={"*": {"langevinDamping": "2"}})
    assert all(r["overridden"] == {"langevindamping": ["5", "2"]} for r in rows[1:])


def test_an_unedited_plan_marks_nothing_overridden():
    assert all(not r["overridden"] for r in md_plan.relaxation_stages(_ctx(fast=True)))


def test_production_stages_take_overrides_too():
    rows = md_plan.production_stages(_ctx(fast=True), total_steps=1_000_000,
                                     timestep_fs=4.0,
                                     stage_overrides={"1": {"langevinDamping": "5"}})
    assert rows[0]["overridden"] == {"langevindamping": ["1", "5"]}


def test_a_hand_edit_is_declared_as_a_protocol_deviation():
    """The point of the whole exercise: an edit is a departure from EVERY protocol, so it
    has to appear in the package's own methods delta rather than only in the confs."""
    d = next(x for x in P.protocol_fidelity(
        fast=True, carved=False, padding_nm=2.0, charge_audit={},
        stage_overrides={"*": {"timestep": "2"}})["deviations"]
        if x["item"] == "hand-edited stages")
    assert d["overrides"] == {"*": {"timestep": "2"}}
    assert "deliberate departure" in d["why"]


def test_no_edits_means_no_hand_edited_deviation():
    assert "hand-edited stages" not in _items()


def test_the_plan_endpoint_rejects_a_protected_override(client):
    r = client.post("/api/md/protocol-plan", json={
        "kind": "relaxation", "stage_overrides": {"1": {"outputName": "x"}}})
    assert r.status_code == 400
    assert "cannot be overridden" in r.json()["detail"]


def test_the_plan_endpoint_reports_which_stages_were_edited(client):
    plan = _plan(client, stage_overrides={"*": {"langevinDamping": "2"}, "3": {"run": "9"}})
    assert plan["edited_stages"] == ["*", "3"]
    assert "outputname" in plan["protected_directives"]
