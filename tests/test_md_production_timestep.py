"""User-selectable production timestep (Advanced card: 1 / 2 / 4 fs).

Fast, pure tests — no NAMD is run.  They pin:
  * the sanctioned-timestep guard (2 fs allowed ONLY with the explicit manual flag),
  * build_production_conf emitting the right integrator block per timestep, and
  * the CreateJobRequest validator rejecting anything but 1/2/4.
See memory/feedback_namd_4fs_production_only.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.md_protocols import (
    SegmentSpec,
    build_production_conf,
    require_sanctioned_production_timestep,
)


def _spec() -> SegmentSpec:
    return SegmentSpec(
        name="d_01_production_2ns_k0_p100", stage="production", percent=100.0,
        steps=500_000, temp=300.0, damping=5.0, scale=None, npt=True,
        previous="d_00_min", dcd_freq=1000,
    )


class TestSanctionedTimestepGuard:
    def test_4_and_1_always_allowed(self) -> None:
        assert require_sanctioned_production_timestep(4.0) == 4.0
        assert require_sanctioned_production_timestep(1.0) == 1.0

    def test_2fs_rejected_without_manual_flag(self) -> None:
        # The AUTOMATIC path must never yield 2 fs — that is the banned drift.
        with pytest.raises(ValueError, match="not sanctioned"):
            require_sanctioned_production_timestep(2.0)

    def test_2fs_allowed_only_with_manual_flag(self) -> None:
        assert require_sanctioned_production_timestep(2.0, allow_manual_2fs=True) == 2.0

    def test_intermediate_values_never_allowed(self) -> None:
        for dt in (2.5, 3.0, 3.5):
            with pytest.raises(ValueError):
                require_sanctioned_production_timestep(dt, allow_manual_2fs=True)


class TestBuildProductionConfTimestep:
    def test_4fs_is_hmr_gpuresident_rigid_all(self) -> None:
        conf = build_production_conf(_spec(), "d", (10.0, 10.0, 10.0), False,
                                     timestep_fs=4.0, structure_psf="d_hmr.psf")
        assert "timestep           4" in conf
        assert "rigidBonds         all" in conf
        assert "GPUresident        on" in conf
        assert "structure          d_hmr.psf" in conf   # uses the repartitioned PSF

    def test_2fs_is_gpuresident_rigid_all_but_plain_psf(self) -> None:
        conf = build_production_conf(_spec(), "d", (10.0, 10.0, 10.0), False,
                                     timestep_fs=2.0)
        assert "timestep           2" in conf
        assert "rigidBonds         all" in conf
        assert "GPUresident        on" in conf
        assert "structure          d.psf" in conf       # standard masses, no HMR

    def test_1fs_is_conservative_reference(self) -> None:
        conf = build_production_conf(_spec(), "d", (10.0, 10.0, 10.0), False,
                                     timestep_fs=1.0)
        assert "timestep           1" in conf
        assert "rigidBonds         none" in conf
        # GPUresident is NOT asserted here any more: exp52 measured it accepted, engaged
        # and 2.06x faster at 1 fs with flexible bonds, so it belongs to the size gate,
        # not to the timestep. See TestProductionGpuResident below.

    def test_timestep_none_reproduces_fast_binary(self) -> None:
        # Backward compat: no timestep_fs → derive from fast (4 fs) / not-fast (1 fs).
        fast = build_production_conf(_spec(), "d", (10.0, 10.0, 10.0), False,
                                     fast=True, structure_psf="d_hmr.psf")
        explicit = build_production_conf(_spec(), "d", (10.0, 10.0, 10.0), False,
                                         timestep_fs=4.0, structure_psf="d_hmr.psf")
        assert fast == explicit


def _job_with_manifest(tmp_path: Path, manifest: dict):
    from backend.core.md_job import MdJob, MdStatus
    job = MdJob(
        job_id="tsjob0001", design_name="d", protocol="equilibrium_aware_namd",
        status=MdStatus.completed, created_at=0.0, package_subdir="package/pkg",
        name_stem="stem", segments=[], current_segment_idx=0,
    )
    pkg = job.package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    return job


class TestProductionFastPlanHonorsManifest:
    """The wire that matters: a stored production_timestep_fs drives the plan's dt."""

    @pytest.mark.parametrize("stored,expected_ts,expected_fast", [
        (4.0, 4.0, True),
        (2.0, 2.0, False),   # GPUresident but not the HMR "fast" path
        (1.0, 1.0, False),
    ])
    def test_manifest_timestep_wins(self, tmp_path, monkeypatch, stored,
                                    expected_ts, expected_fast) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": stored,
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_fs"] == expected_ts
        assert plan["fast"] is expected_fast

    def test_absent_field_falls_back_to_fast_derived_4fs(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_fs"] == 4.0


    def test_auto_derived_4fs_on_declash_falls_back_quietly(self, tmp_path, monkeypatch) -> None:
        """No pin = nothing was promised, so the quiet fallback is still correct.

        This is what keeps the change from breaking every declash design's production
        launch: only an explicit pin is a conflict.
        """
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {          # no production_timestep_fs key
            "fast_relaxation": {"enabled": True}, "declash": True,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan.get("timestep_conflict") is None   # no such thing any more
        assert plan["timestep_fs"] == 1.0

    def test_1fs_is_the_only_timestep_a_declash_package_can_run(
        self, tmp_path, monkeypatch,
    ) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 1.0,
            "fast_relaxation": {"enabled": True}, "declash": True,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan.get("timestep_conflict") is None   # no such thing any more
        assert plan["timestep_fs"] == 1.0


    def test_request_timestep_overrides_the_prep_time_manifest_value(
        self, tmp_path, monkeypatch,
    ) -> None:
        """The dropdown is read at PRODUCTION time; the manifest value was baked in at PREP.

        Until the request carried a timestep, changing the dropdown before pressing Start
        Production moved neither the run nor the estimate — a 2 fs selection produced a
        1 fs trajectory.  Observed on 2hb_1xT.
        """
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 1.0,          # baked in at prep
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(
            job, routes_md.ProductionRequest(steps=1000, production_timestep_fs=4.0))
        assert plan["timestep_fs"] == 4.0
        assert plan["fast"] is True

    def test_absent_request_timestep_still_inherits_the_manifest(
        self, tmp_path, monkeypatch,
    ) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 2.0,
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(
            job, routes_md.ProductionRequest(steps=1000))     # no dt on the request
        assert plan["timestep_fs"] == 2.0

    def test_request_timestep_is_validated_to_the_sanctioned_set(self) -> None:
        from backend.api import routes_md
        with pytest.raises(ValueError):
            routes_md.ProductionRequest(steps=1000, production_timestep_fs=3.0)
        assert routes_md.ProductionRequest(steps=1000).production_timestep_fs is None

    def test_pinned_4fs_without_declash_runs_as_asked(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 4.0,
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan.get("timestep_conflict") is None   # no such thing any more
        assert plan["timestep_fs"] == 4.0
        assert plan["fast"] is True


class TestCreateJobRequestValidator:
    def test_accepts_1_2_4(self) -> None:
        from backend.api.routes_md import CreateJobRequest
        for dt in (1.0, 2.0, 4.0):
            assert CreateJobRequest(production_timestep_fs=dt).production_timestep_fs == dt

    def test_defaults_to_4(self) -> None:
        from backend.api.routes_md import CreateJobRequest
        assert CreateJobRequest().production_timestep_fs == 4.0

    def test_rejects_unsanctioned(self) -> None:
        from pydantic import ValidationError

        from backend.api.routes_md import CreateJobRequest
        with pytest.raises(ValidationError):
            CreateJobRequest(production_timestep_fs=3.0)


class TestProductionGpuResident:
    """Production hard-coded ``GPUresident on`` for the 2 fs and 4 fs branches.

    It was the one place the atom-count size gate never reached, and it ignored the
    Advanced-card dropdown outright — so ⚡ Optimize could report "GPU-resident: off"
    while the run used it anyway.  Seen on 2hb_1xT: a 32.5k-atom 2 fs production sat at
    1.357 ms/step with resident engaged, unchanged after optimising.
    """

    def _spec(self):
        from backend.core.md_protocols import SegmentSpec
        return SegmentSpec(name="p", stage="prod", percent=100, steps=1000, temp=300.0,
                           damping=5.0, scale=None, npt=True, previous="prev")

    def _conf(self, **kw):
        from backend.core.md_protocols import build_production_conf
        return build_production_conf(self._spec(), "S", (80.0, 80.0, 200.0), True,
                                     structure_psf="S_hmr.psf", **kw)

    @pytest.mark.parametrize("ts", [2.0, 4.0])
    def test_auto_turns_resident_OFF_on_a_small_system(self, ts) -> None:
        assert "GPUresident" not in self._conf(timestep_fs=ts, n_atoms=32_566)

    @pytest.mark.parametrize("ts", [2.0, 4.0])
    def test_auto_keeps_resident_on_a_large_system(self, ts) -> None:
        assert "GPUresident        on" in self._conf(timestep_fs=ts, n_atoms=3_139_238)

    @pytest.mark.parametrize("ts", [2.0, 4.0])
    def test_force_off_beats_the_size_gate(self, ts) -> None:
        assert "GPUresident" not in self._conf(
            timestep_fs=ts, n_atoms=3_139_238, force_resident=False)

    @pytest.mark.parametrize("ts", [2.0, 4.0])
    def test_force_on_beats_the_size_gate(self, ts) -> None:
        assert "GPUresident        on" in self._conf(
            timestep_fs=ts, n_atoms=32_566, force_resident=True)

    def test_unknown_atom_count_keeps_the_old_resident_default(self) -> None:
        """n_atoms=None means 'unknown', not 'small' — byte-compatible with callers
        (md_ensemble) that do not size the system."""
        assert "GPUresident        on" in self._conf(timestep_fs=4.0)

    def test_1fs_follows_the_size_gate_like_every_other_timestep(self) -> None:
        # REPLACES test_1fs_conservative_reference_is_never_resident, which asserted that
        # a 1 fs conf is never resident EVEN WHEN force_resident=True — i.e. it pinned the
        # user's own choice being silently discarded. exp52 (2026-08-05) ran the matched
        # pair on one system: resident is accepted at 1 fs with rigidBonds none, engages,
        # and is 2.06x faster at 32.7k atoms. The timestep does not decide this.
        assert "GPUresident" not in self._conf(timestep_fs=1.0, n_atoms=32_754)
        assert "GPUresident        on" in self._conf(timestep_fs=1.0, n_atoms=3_139_238)
        assert "GPUresident        on" in self._conf(timestep_fs=1.0, force_resident=True)
        assert "GPUresident" not in self._conf(timestep_fs=4.0, force_resident=False)

    def test_an_explicit_choice_beats_the_size_gate_at_every_timestep(self) -> None:
        for dt in (1.0, 2.0, 4.0):
            assert "GPUresident        on" in self._conf(timestep_fs=dt,
                                                         n_atoms=1_000,
                                                         force_resident=True)
            assert "GPUresident" not in self._conf(timestep_fs=dt,
                                                   n_atoms=3_139_238,
                                                   force_resident=False)

    def test_rigidbonds_still_follows_the_timestep_not_the_resident_choice(self) -> None:
        """Resident is WHERE integration runs; rigidBonds is physics. Turning resident
        off must not quietly soften the integrator."""
        off = self._conf(timestep_fs=2.0, n_atoms=32_566, force_resident=False)
        assert "rigidBonds         all" in off
        assert "timestep           2" in off


class TestProductionPlanResolvesResident:
    def test_request_beats_manifest_beats_auto(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "gpu_resident_mode": "on",
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        # request wins
        plan = routes_md._production_fast_plan(
            job, routes_md.ProductionRequest(steps=1000, gpu_resident="off"))
        assert plan["force_resident"] is False
        # absent on the request → the package's prep-time mode
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["force_resident"] is True

    def test_auto_leaves_the_decision_to_the_size_gate(self, tmp_path, monkeypatch) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "gpu_resident_mode": "auto",
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["force_resident"] is None      # None = auto = decide from n_atoms

    def test_bad_mode_is_rejected(self) -> None:
        from backend.api import routes_md
        with pytest.raises(ValueError):
            routes_md.ProductionRequest(steps=1000, gpu_resident="yes-please")




class TestRelaxProtocolDoesNotConstrainProduction:
    """The relaxation's integrator must not dictate production's.

    A ladder exists to deliver equilibrated COORDINATES.  Once it has, production is free
    to sample them at any sanctioned timestep.  An earlier rule refused 2/4 fs outright on
    a declash package, on two premises that do not hold:
      * "no HMR PSF" — production builds one on demand from the package's own PSF; it was
        an artefact the fast ladder happened to leave behind, never a prerequisite.
      * "residual single-stranded contacts crash RATTLE" — that describes the STARTING
        structure, which is exactly what the ladder removed.  Measured: a rigidBonds-all
        2 fs production off a declash relax ran 412k steps with no RATTLE failure.
    """

    @pytest.mark.parametrize("dt", [1.0, 2.0, 4.0])
    def test_every_sanctioned_timestep_is_allowed_after_a_declash_relax(
        self, tmp_path, monkeypatch, dt,
    ) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": dt,
            "fast_relaxation": {"enabled": False}, "declash": True,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_fs"] == dt, "the relax protocol must not cap production's dt"
        assert plan.get("timestep_conflict") is None

    def test_4fs_on_extra_bases_warns_but_does_not_block(self, tmp_path, monkeypatch) -> None:
        """The Fix-B caveat is real (HMR lightens C5' on unpaired inserts), but it is an
        empirical stability question the run answers — inform, do not forbid."""
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 4.0,
            "fast_relaxation": {"enabled": False}, "declash": True,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_fs"] == 4.0
        assert plan["timestep_warning"] and "RATTLE" in plan["timestep_warning"]

    def test_no_warning_when_the_package_is_not_a_declash_build(
        self, tmp_path, monkeypatch,
    ) -> None:
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 4.0,
            "fast_relaxation": {"enabled": True}, "declash": False,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_warning"] is None

    def test_4fs_after_a_declash_relax_yields_the_FAST_path_not_just_the_label(
        self, tmp_path, monkeypatch,
    ) -> None:
        """`fast` must mean "4 fs HMR path", not "4 fs AND the relax was fast".

        Removing the hard conflict was not enough: `fast` stayed
        `(timestep_fs == 4.0) and not declash`, the same coupling in another variable.
        The replica builder reads `fast` as "may I use an HMR PSF", so with declash it
        got False, skipped HMR, and emitted a SILENT 1 fs conf — a requested 4 fs run
        measured ~80 ns/day (exactly the 1 fs rate) with nothing saying why.
        """
        from backend.api import routes_md
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        job = _job_with_manifest(tmp_path, {
            "production_timestep_fs": 4.0,
            "fast_relaxation": {"enabled": False}, "declash": True,
        })
        plan = routes_md._production_fast_plan(job, routes_md.ProductionRequest(steps=1000))
        assert plan["timestep_fs"] == 4.0
        assert plan["fast"] is True, "declash must not veto the 4 fs HMR path"


class TestHealthPassedUsesTheLastSamplePerSegment:
    """Health is now sampled WHILE a segment runs, so one segment has many samples.

    `_production_ready_checkpoint` built its passed-set with
    `{h.segment for h in health_samples if h.passed}` — "any sample passed". A structure
    that degrades across a long run would then still count as healthy. Real numbers from
    the 200 ns 4 fs production: c1=0.950 (passed) at 90 ns, c1=0.850 (FAILED) at the end.
    An `any` test offers that degraded checkpoint as production-ready.
    """

    def _samples(self):
        from backend.core.md_job import MdHealthSample
        mk = lambda t, c, ok: MdHealthSample(                      # noqa: E731
            wall_time=t, stage="production", segment="seg_A",
            c1_paired_fraction=c, c1_mean_ang=9.6, c1_p90_ang=10.8,
            wc_ref_relative_fraction=0.7, wc_mean_hbond_ang=5.3,
            passed=ok, blocking=False, reason="")
        return [mk(1.0, 0.950, True), mk(2.0, 0.850, False)]       # improved → degraded

    def test_a_segment_that_ended_failing_is_not_counted_as_passed(self) -> None:
        samples = self._samples()
        last = {}
        for h in samples:
            last[h.segment] = h
        passed = {seg for seg, h in last.items() if h.passed}
        assert passed == set(), "the FINAL sample failed — the segment must not count as passed"
        # the old rule would have said otherwise:
        assert {h.segment for h in samples if h.passed} == {"seg_A"}

    def test_a_segment_that_ended_passing_still_counts(self) -> None:
        samples = list(reversed(self._samples()))   # degraded → recovered
        last = {}
        for h in samples:
            last[h.segment] = h
        assert {seg for seg, h in last.items() if h.passed} == {"seg_A"}

    def test_single_sample_behaviour_is_unchanged(self) -> None:
        """With one sample per segment (the pre-change world) both rules agree."""
        samples = self._samples()[:1]
        last = {h.segment: h for h in samples}
        assert ({seg for seg, h in last.items() if h.passed}
                == {h.segment for h in samples if h.passed})
