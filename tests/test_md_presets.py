"""Relax presets: the named protocols the panel and the Job Wizard offer."""

from __future__ import annotations

import pytest

from backend.core.md_presets import (
    DEFAULT_PRESET,
    DESIGN_SPEED,
    EXPLICIT_PROTOCOL,
    FAST_SHAPE,
    FULL_PHYSICS,
    IMPLICIT_GBIS,
    IMPLICIT_PROTOCOL,
    LITERATURE,
    PRESET_ORDER,
    PRESETS,
    RETIRED_FROM_MENU,
    STANDARD,
    apply_preset,
    get_preset,
    preset_catalogue,
    protocol_for,
)


def test_presets_are_listed_cheapest_first():
    assert PRESET_ORDER == (
        FAST_SHAPE,
        IMPLICIT_GBIS,
        DESIGN_SPEED,
        STANDARD,
        LITERATURE,
        FULL_PHYSICS,
    )
    assert set(PRESETS) == set(PRESET_ORDER)


def test_standard_is_the_default():
    assert DEFAULT_PRESET == STANDARD
    assert get_preset(None).id == STANDARD
    assert get_preset("").id == STANDARD
    assert get_preset("no-such-preset").id == STANDARD
    assert [p for p in preset_catalogue() if p["is_default"]][0]["id"] == STANDARD


def test_labels_are_the_ones_the_panel_shows():
    labels = {p["id"]: p["label"] for p in preset_catalogue()}
    assert labels[FAST_SHAPE] == "Fast Shape Check (Vacuum)"
    assert labels[STANDARD] == "Standard (Aksimentiev)"
    assert labels[FULL_PHYSICS] == "Slow (full physics)"
    assert labels[IMPLICIT_GBIS] == "Implicit Solvent (GBIS)"


def test_the_vacuum_tier_is_retired_with_a_reason():
    """It shipped and was retired the same day.  The tutorial's §3.2 unfolds caDNAno's
    abstract parallel-helix lattice; NADOC derives physical geometry, so there is nothing
    to unfold — and the step's repulsion surrogate scores ZERO bonds on a dense honeycomb,
    letting bundles swell away from the Mg-screened equilibrium.  It must not silently
    look runnable."""
    p = PRESETS[FAST_SHAPE]
    assert p.available is False
    assert "caDNAno" in p.unavailable_reason
    assert "ZERO" in p.unavailable_reason  # the measured failure, not a hunch
    assert all(PRESETS[i].available for i in (STANDARD, FULL_PHYSICS))


def test_solvated_presets_ask_for_a_full_water_box():
    """A carve forces NVT, which rules out the free stage both presets want."""
    for pid in (STANDARD, FULL_PHYSICS):
        assert PRESETS[pid].defaults["water_shell_nm"] == 0.0


def test_full_physics_disables_early_stop_and_pads_wider():
    assert PRESETS[FULL_PHYSICS].defaults["early_stop_relax"] is False
    assert PRESETS[STANDARD].defaults["early_stop_relax"] is True
    assert (
        PRESETS[FULL_PHYSICS].defaults["padding_nm"]
        > PRESETS[STANDARD].defaults["padding_nm"]
    )


# ── the two wizard tiers: reproduce the paper, or get an answer about the design ──
def test_literature_trades_nothing_for_speed():
    """Every accelerator NADOC has measured is OFF, and the paper's own integrator is on.

    This preset exists so "I ran the published protocol" is a checkable claim rather than
    a hopeful one.  Each assertion below is a place where NADOC's default deviates.
    """
    d = PRESETS[LITERATURE].defaults
    assert d["early_stop_relax"] is False  # never truncate a stage you will publish
    assert d["fast"] is False  # no hydrogen-mass repartitioning
    assert d["padding_nm"] == 2.0  # the tutorial's bounding box +/- 20 A
    assert d["salt_mode"] == "screening"  # Mg(H2O)6 neutralises, no sodium
    assert d["minimize_steps"] == 4_800  # the tutorial's literal figure
    assert "Methods Mol Biol 1811" in PRESETS[LITERATURE].reference


def test_literature_refuses_a_water_shell_carve():
    """A carve leaves vacuum in the cell, which forces constant volume, which removes both
    the Note-4 fixed-DNA settle stage and the box-size trace the reference uses to judge
    equilibration — and leaves no bulk phase for the published ionic condition to be a
    concentration OF.  Auto-fitting one would quietly turn "the published protocol" into
    something else.  Every other preset lets prep carve rather than fail.
    """
    assert PRESETS[LITERATURE].defaults["allow_water_shell_carve"] is False
    assert all(
        "allow_water_shell_carve" not in PRESETS[p].defaults
        for p in PRESET_ORDER
        if p != LITERATURE
    )


def test_literature_LOCKS_the_carve_rather_than_merely_defaulting_it():
    """Not an option, not a default.

    Every other setting a preset supplies is a starting point the user may overrule. This
    one is not: a carved run is a different experiment, so allowing an override would make
    the tier's own NAME untrue. It is the only locked field in the catalogue.
    """
    assert PRESETS[LITERATURE].locked == frozenset({"allow_water_shell_carve"})
    assert all(not PRESETS[p].locked for p in PRESET_ORDER if p != LITERATURE)


def test_a_locked_field_beats_an_explicit_request():
    out = apply_preset(
        LITERATURE,
        {"allow_water_shell_carve": True},
        explicit={"allow_water_shell_carve"},
    )
    assert out["allow_water_shell_carve"] is False


def test_locking_does_not_leak_into_the_presets_other_settings():
    """A lock is surgical — everything else stays overridable."""
    out = apply_preset(
        LITERATURE,
        {"padding_nm": 1.0, "early_stop_relax": True},
        explicit={"padding_nm", "early_stop_relax"},
    )
    assert out["padding_nm"] == 1.0
    assert out["early_stop_relax"] is True
    assert out["allow_water_shell_carve"] is False


def test_the_catalogue_tells_the_ui_which_fields_are_locked():
    """So the wizard can render the control read-only instead of offering a dead one."""
    by_id = {p["id"]: p for p in preset_catalogue()}
    assert by_id[LITERATURE]["locked"] == ["allow_water_shell_carve"]
    assert by_id[STANDARD]["locked"] == []


def test_design_speed_turns_every_measured_accelerator_on():
    d = PRESETS[DESIGN_SPEED].defaults
    assert d["fast"] is True  # HMR + 4 fs + GPU-resident
    assert d["early_stop_relax"] is True
    assert d["padding_nm"] == 1.2  # the cheap bounding-box cell
    assert d["protocol"] == EXPLICIT_PROTOCOL  # same chemistry, only scheduling moves


def test_the_two_wizard_tiers_disagree_on_every_speed_axis():
    """If they ever agreed on one, that axis would be a control with no effect."""
    fast, lit = PRESETS[DESIGN_SPEED].defaults, PRESETS[LITERATURE].defaults
    for key in ("fast", "early_stop_relax", "padding_nm"):
        assert fast[key] != lit[key], key


def test_every_preset_default_names_a_real_request_field():
    """A typo'd key silently no-ops: the merge filters on the request model's fields.

    Nothing else would notice — the job would be created, run, and quietly ignore the
    setting the preset promised.
    """
    from backend.api.routes_md import CreateJobRequest

    fields = set(CreateJobRequest.model_fields)
    for pid in PRESET_ORDER:
        unknown = set(PRESETS[pid].defaults) - fields
        assert not unknown, f"{pid} defaults unknown request fields: {sorted(unknown)}"


# ── merge semantics ───────────────────────────────────────────────────────────
def test_apply_preset_fills_unset_fields():
    out = apply_preset(STANDARD, {"mg_conc_mM": 12.5}, explicit={"mg_conc_mM"})
    assert out["mg_conc_mM"] == 12.5  # untouched
    assert out["padding_nm"] == 2.0  # from the preset (the tutorial's ±20 Å)
    assert out["early_stop_relax"] is True


def test_explicit_user_settings_always_win():
    out = apply_preset(
        FULL_PHYSICS,
        {"padding_nm": 3.0, "early_stop_relax": True},
        explicit={"padding_nm", "early_stop_relax"},
    )
    assert out["padding_nm"] == 3.0
    assert out["early_stop_relax"] is True  # not clobbered by the preset's False


def test_apply_preset_does_not_mutate_its_input():
    req = {"padding_nm": 9.9}
    apply_preset(STANDARD, req, explicit=set())
    assert req == {"padding_nm": 9.9}


def test_unknown_preset_applies_the_default_rather_than_nothing():
    out = apply_preset("bogus", {}, explicit=set())
    assert out["padding_nm"] == PRESETS[STANDARD].defaults["padding_nm"]


@pytest.mark.parametrize("pid", list(PRESET_ORDER))
def test_catalogue_entries_are_serialisable_and_complete(pid):
    entry = next(p for p in preset_catalogue() if p["id"] == pid)
    assert entry["label"] and entry["summary"] and entry["reference"]
    assert isinstance(entry["defaults"], dict)
    assert isinstance(entry["available"], bool)


# ── protocol is DERIVED, never a second control ───────────────────────────────
def test_every_preset_names_the_protocol_it_runs():
    """The merge's invariant: there is no way to select a preset and a contradicting
    protocol, because the protocol is a property of the preset."""
    for pid in PRESET_ORDER:
        assert PRESETS[pid].defaults.get("protocol"), f"{pid} has no protocol"
        assert protocol_for(pid) == PRESETS[pid].defaults["protocol"]


def test_each_solvent_model_has_its_own_protocol():
    from backend.core.md_presets import VACUUM_PROTOCOL

    assert protocol_for(IMPLICIT_GBIS) == IMPLICIT_PROTOCOL
    assert protocol_for(FAST_SHAPE) == VACUUM_PROTOCOL
    for pid in (STANDARD, FULL_PHYSICS):
        assert protocol_for(pid) == EXPLICIT_PROTOCOL


def test_the_legacy_protocol_is_retired_from_the_menu():
    """`mgh_slow_release` is `equilibrium_aware_namd` with the topology gate OFF — a
    validation choice, not a protocol.  It stays valid for the API and existing jobs,
    but no preset offers it."""
    assert "mgh_slow_release" in RETIRED_FROM_MENU
    assert all(p["protocol"] != "mgh_slow_release" for p in preset_catalogue())


def test_catalogue_exposes_the_protocol_for_the_panel():
    by_id = {p["id"]: p for p in preset_catalogue()}
    assert by_id[IMPLICIT_GBIS]["protocol"] == IMPLICIT_PROTOCOL
    assert by_id[STANDARD]["protocol"] == EXPLICIT_PROTOCOL


def test_protocol_for_unknown_preset_is_the_explicit_default():
    assert protocol_for("nope") == EXPLICIT_PROTOCOL
    assert protocol_for(None) == EXPLICIT_PROTOCOL


# ── host-aware availability (the GBIS regression) ─────────────────────────────
def test_gbis_requires_a_cpu_namd_build():
    """GBIS is unsupported on the NAMD 3 CUDA nonbonded kernel, so a host with only the
    CUDA build cannot run it.  Marking it available regardless meant the job was
    accepted, solvated, queued — and only then failed on the first segment."""
    assert PRESETS[IMPLICIT_GBIS].requires_cpu_namd is True
    assert not any(
        PRESETS[p].requires_cpu_namd for p in (FAST_SHAPE, STANDARD, FULL_PHYSICS)
    )


def test_availability_is_false_when_no_cpu_namd_build_exists(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    monkeypatch.setattr(
        runner,
        "find_namd",
        lambda prefer_cpu=False: (_ for _ in ()).throw(
            RuntimeError("needs a CPU (non-CUDA) NAMD build")
        ),
    )
    ok, why = preset_availability(PRESETS[IMPLICIT_GBIS])
    assert ok is False
    assert "CPU (non-CUDA)" in why


def test_availability_is_true_when_a_cpu_build_is_present(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    monkeypatch.setattr(runner, "find_namd", lambda prefer_cpu=False: "/opt/namd3")
    assert preset_availability(PRESETS[IMPLICIT_GBIS]) == (True, "")


def test_a_statically_unavailable_preset_would_short_circuit_the_host_probe(
    monkeypatch,
):
    """No preset is statically unavailable today, but the short-circuit is what stops a
    future one from paying for a toolchain probe it can never use — so pin the rule
    against a synthetic preset rather than deleting the guarantee with the last case."""
    import backend.core.namd_runner as runner
    from backend.core.md_presets import RelaxPreset, preset_availability

    def _boom(**_kw):
        raise AssertionError("must not probe for a statically-unavailable preset")

    monkeypatch.setattr(runner, "find_namd", _boom)
    ghost = RelaxPreset(
        id="ghost",
        label="Ghost",
        summary="",
        available=False,
        unavailable_reason="pipeline does not exist",
        requires_cpu_namd=True,
    )
    ok, why = preset_availability(ghost)
    assert ok is False and why == "pipeline does not exist"


def test_explicit_presets_never_probe_the_toolchain(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    def _boom(**_kw):
        raise AssertionError("explicit-solvent presets must not need a CPU build")

    monkeypatch.setattr(runner, "find_namd", _boom)
    for pid in (STANDARD, FULL_PHYSICS):
        assert preset_availability(PRESETS[pid]) == (True, "")
