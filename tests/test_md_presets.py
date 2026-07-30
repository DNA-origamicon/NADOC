"""Relax presets: the four named protocols the panel offers."""
from __future__ import annotations

import pytest

from backend.core.md_presets import (DEFAULT_PRESET, EXPLICIT_PROTOCOL, FAST_SHAPE,
                                     FULL_PHYSICS, IMPLICIT_GBIS, IMPLICIT_PROTOCOL,
                                     PRESET_ORDER, PRESETS, RETIRED_FROM_MENU, STANDARD,
                                     apply_preset, get_preset, preset_catalogue,
                                     protocol_for)


def test_four_presets_in_cheapest_first_order():
    assert PRESET_ORDER == (FAST_SHAPE, IMPLICIT_GBIS, STANDARD, FULL_PHYSICS)
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


def test_vacuum_preset_is_marked_unavailable_with_a_reason():
    """It must not silently look runnable — the vacuum pipeline does not exist yet."""
    p = PRESETS[FAST_SHAPE]
    assert p.available is False
    assert "vacuum" in p.unavailable_reason.lower()
    assert "31 A" in p.unavailable_reason      # the parameter we DO know
    assert all(PRESETS[i].available for i in (IMPLICIT_GBIS, STANDARD, FULL_PHYSICS))


def test_solvated_presets_ask_for_a_full_water_box():
    """A carve forces NVT, which rules out the free stage both presets want."""
    for pid in (STANDARD, FULL_PHYSICS):
        assert PRESETS[pid].defaults["water_shell_nm"] == 0.0


def test_full_physics_disables_early_stop_and_pads_wider():
    assert PRESETS[FULL_PHYSICS].defaults["early_stop_relax"] is False
    assert PRESETS[STANDARD].defaults["early_stop_relax"] is True
    assert (PRESETS[FULL_PHYSICS].defaults["padding_nm"]
            > PRESETS[STANDARD].defaults["padding_nm"])


# ── merge semantics ───────────────────────────────────────────────────────────
def test_apply_preset_fills_unset_fields():
    out = apply_preset(STANDARD, {"mg_conc_mM": 12.5}, explicit={"mg_conc_mM"})
    assert out["mg_conc_mM"] == 12.5              # untouched
    assert out["padding_nm"] == 1.2               # from the preset
    assert out["early_stop_relax"] is True


def test_explicit_user_settings_always_win():
    out = apply_preset(FULL_PHYSICS,
                       {"padding_nm": 3.0, "early_stop_relax": True},
                       explicit={"padding_nm", "early_stop_relax"})
    assert out["padding_nm"] == 3.0
    assert out["early_stop_relax"] is True         # not clobbered by the preset's False


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


def test_only_the_gbis_preset_is_implicit_solvent():
    assert protocol_for(IMPLICIT_GBIS) == IMPLICIT_PROTOCOL
    for pid in (FAST_SHAPE, STANDARD, FULL_PHYSICS):
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
    assert not any(PRESETS[p].requires_cpu_namd
                   for p in (FAST_SHAPE, STANDARD, FULL_PHYSICS))


def test_availability_is_false_when_no_cpu_namd_build_exists(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    monkeypatch.setattr(runner, "find_namd", lambda prefer_cpu=False: (
        _ for _ in ()).throw(RuntimeError("needs a CPU (non-CUDA) NAMD build")))
    ok, why = preset_availability(PRESETS[IMPLICIT_GBIS])
    assert ok is False
    assert "CPU (non-CUDA)" in why


def test_availability_is_true_when_a_cpu_build_is_present(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    monkeypatch.setattr(runner, "find_namd", lambda prefer_cpu=False: "/opt/namd3")
    assert preset_availability(PRESETS[IMPLICIT_GBIS]) == (True, "")


def test_statically_unavailable_presets_short_circuit_the_host_probe(monkeypatch):
    """fast_shape has no pipeline at all — never probe the toolchain for it."""
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    def _boom(**_kw):
        raise AssertionError("must not probe for a statically-unavailable preset")

    monkeypatch.setattr(runner, "find_namd", _boom)
    ok, why = preset_availability(PRESETS[FAST_SHAPE])
    assert ok is False and "vacuum" in why.lower()


def test_explicit_presets_never_probe_the_toolchain(monkeypatch):
    import backend.core.namd_runner as runner
    from backend.core.md_presets import preset_availability

    def _boom(**_kw):
        raise AssertionError("explicit-solvent presets must not need a CPU build")

    monkeypatch.setattr(runner, "find_namd", _boom)
    for pid in (STANDARD, FULL_PHYSICS):
        assert preset_availability(PRESETS[pid]) == (True, "")
