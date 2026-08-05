"""The three integrator axes resolve independently, and every measured objection is stated.

These pin exp51's findings (experiments/exp51_integrator_factorial/RESULTS.md) into the
code that emits confs, because the whole point of separating the axes was that nothing was
checking them against a measurement.
"""
from backend.core.md_integrator import (
    RIGID_ALL,
    RIGID_NONE,
    auto_hmr,
    auto_rigid_bonds,
    integrator_warnings,
    resident_decision,
    resolve_integrator,
)


class TestAuto:
    def test_hmr_defaults_on_only_at_4fs(self):
        # Below 4 fs it is a measured loss, so it is never defaulted on.
        assert auto_hmr(4.0) is True
        assert auto_hmr(2.0) is False
        assert auto_hmr(1.0) is False

    def test_rigid_defaults_to_constrained_above_1fs(self):
        assert auto_rigid_bonds(4.0) == RIGID_ALL
        assert auto_rigid_bonds(2.0) == RIGID_ALL
        assert auto_rigid_bonds(1.0) == RIGID_NONE


class TestResolve:
    def test_axes_are_independent(self):
        # The combination the old code could not emit at all.
        c = resolve_integrator(4.0, rigid_bonds="all", hmr=False)
        assert (c.timestep_fs, c.rigid_bonds, c.hmr) == (4.0, RIGID_ALL, False)
        assert c.rigid_explicit and c.hmr_explicit

    def test_1fs_can_be_rigid(self):
        # exp51: stable, drift indistinguishable from flexible. The old writers forced
        # rigidBonds none at 1 fs unconditionally.
        c = resolve_integrator(1.0, rigid_bonds="all")
        assert c.rigid_bonds == RIGID_ALL
        assert c.hmr is False          # still auto-off at 1 fs

    def test_none_means_auto_and_is_marked_as_such(self):
        c = resolve_integrator(4.0)
        assert c.rigid_bonds == RIGID_ALL and c.hmr is True
        assert not c.rigid_explicit and not c.hmr_explicit

    def test_explicit_false_hmr_is_not_auto(self):
        # False must not be confused with "unset" — that distinction is the whole toggle.
        c = resolve_integrator(4.0, hmr=False)
        assert c.hmr is False and c.hmr_explicit is True

    def test_garbage_rigid_falls_back_to_auto_rather_than_raising(self):
        # This runs inside conf emission; the request validator already rejects bad input,
        # and a typo must not take a job down at write time.
        c = resolve_integrator(2.0, rigid_bonds="sometimes")
        assert c.rigid_bonds == RIGID_ALL and c.rigid_explicit is False

    def test_rigid_is_case_insensitive(self):
        assert resolve_integrator(2.0, rigid_bonds="ALL").rigid_bonds == RIGID_ALL


class TestWarnings:
    def _ids(self, choice, **kw):
        return {w["id"] for w in integrator_warnings(choice, **kw)}

    def test_sanctioned_combinations_are_silent(self):
        for dt in (1.0, 2.0, 4.0):
            assert integrator_warnings(resolve_integrator(dt)) == []

    def test_1fs_rigid_is_silent_because_exp51_measured_it_stable(self):
        assert integrator_warnings(resolve_integrator(1.0, rigid_bonds="all")) == []

    def test_4fs_without_hmr_warns(self):
        ids = self._ids(resolve_integrator(4.0, hmr=False))
        assert "relax_4fs_without_hmr" in ids

    def test_4fs_flexible_warns_and_cites_the_step_zero_failure(self):
        w = integrator_warnings(resolve_integrator(4.0, rigid_bonds="none"))
        flex = next(x for x in w if x["id"] == "relax_flexible_above_1fs")
        assert "step 0" in flex["detail"]

    def test_2fs_flexible_warns_with_the_milder_wording(self):
        w = integrator_warnings(resolve_integrator(2.0, rigid_bonds="none"))
        flex = next(x for x in w if x["id"] == "relax_flexible_above_1fs")
        assert "step 0" not in flex["detail"]
        assert "5x worse" in flex["detail"]

    def test_hmr_below_4fs_warns(self):
        assert "relax_hmr_below_4fs" in self._ids(resolve_integrator(2.0, hmr=True))
        assert "relax_hmr_below_4fs" in self._ids(resolve_integrator(1.0, hmr=True))

    def test_nothing_is_ever_blocking(self):
        # Warn, never block — the audit was only possible because the unsanctioned
        # combinations could be run.
        for dt in (1.0, 2.0, 4.0):
            for rigid in ("all", "none"):
                for hmr in (True, False):
                    for w in integrator_warnings(resolve_integrator(dt, rigid, hmr)):
                        assert w["kind"] == "warning"

    def test_source_names_the_field_so_the_wizard_can_place_it(self):
        w = integrator_warnings(resolve_integrator(4.0, hmr=False))
        assert w[0]["source"] == "CreateJobRequest.relax_hmr"
        p = integrator_warnings(resolve_integrator(4.0, hmr=False), scope="production")
        assert p[0]["source"] == "CreateJobRequest.production_hmr"
        assert "production run" in p[0]["detail"]


class TestResidentDecision:
    """GPU-resident is decided by size and compatibility — never by the timestep.

    exp52 (experiments/exp52_gpu_resident_coupling) measured the matched pairs on one
    system: resident is accepted at every sanctioned integrator setting, engages, and is
    1.86-2.06x FASTER at 32.7k atoms.
    """

    def test_the_timestep_is_not_an_input(self):
        from inspect import signature
        assert "timestep_fs" not in signature(resident_decision).parameters

    def test_size_gate_decides_when_nobody_chose(self):
        assert resident_decision(n_atoms=3_139_238).on is True
        off = resident_decision(n_atoms=32_754)
        assert off.on is False and off.decided_by == "size"
        assert "crossover" in off.reason

    def test_an_explicit_choice_beats_the_size_gate_both_ways(self):
        assert resident_decision(n_atoms=1_000, force_resident=True).on is True
        assert resident_decision(n_atoms=3_139_238, force_resident=False).on is False
        assert resident_decision(n_atoms=1_000, force_resident=True).decided_by == "user"

    def test_hard_incompatibilities_beat_the_user(self):
        for kw in ({"gbis": True}, {"vacuum": True}, {"fixed_atoms": True},
                   {"carved_fill": 0.5}):
            d = resident_decision(force_resident=True, **kw)
            assert d.on is False, kw
            assert d.overridden is True, kw
            assert d.reason, kw

    def test_a_well_filled_carved_cell_is_not_blocked(self):
        assert resident_decision(n_atoms=3_139_238, carved_fill=0.95).on is True

    def test_every_refusal_says_why(self):
        # "Why is this off when I asked for it on?" must be answerable from the decision.
        d = resident_decision(force_resident=True, gbis=True)
        assert "implicit solvent" in d.reason

    def test_no_atom_count_yet_defaults_on_rather_than_guessing_small(self):
        # The plan runs before solvation. Reporting "off" there would show a value the
        # real run will not use.
        assert resident_decision().on is True
