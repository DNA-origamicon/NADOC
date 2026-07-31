"""Microsecond-scale production runs: request caps, and the disk/wall-clock forecast.

Fast, pure tests — no NAMD is run.  They pin:
  * the production step/length caps admitting a 1 us run (250M steps at 4 fs) on
    every request model that carries them,
  * the forecast measuring the volume a run will ACTUALLY write to (an archived
    job's external drive, not the workspace disk),
  * trajectory bytes tracking the dcd_freq the run will really use, and
  * the throughput estimate that drives the "this is a large run" confirmation.

Background: the caps used to be 50M steps / 100 ns, so a 1 us run was rejected by
pydantic with a 422 whose ``detail`` is a list of dicts — which the panel rendered
as the useless "Production failed: [object Object]".
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.api.routes_md import (
    MAX_PRODUCTION_NS,
    MAX_PRODUCTION_STEPS,
    ChainStageRequest,
    EnsembleProductionRequest,
    ProductionRequest,
    ProductionRunRequest,
    _throughput_estimate,
)
from backend.core.disk_guard import forecast, namd_run_output_bytes, volume_root

# 1 us at 4 fs.  The number from the original bug report.
ONE_US_STEPS_AT_4FS = 250_000_000

# Every request model that can start or stage a production run.  They must agree:
# a length one of them accepts and another rejects is a bug that only shows up in
# whichever panel happens to use the stricter route.
LENGTH_CARRYING_MODELS = [
    ProductionRequest,
    ProductionRunRequest,
    EnsembleProductionRequest,
    ChainStageRequest,
]

#: Fields a model requires that are unrelated to run length (so the length cap is
#: what the assertion is actually exercising).
REQUIRED_EXTRAS = {ChainStageRequest: {"engine": "namd"}}


def _build(model, **kwargs):
    return model(**{**REQUIRED_EXTRAS.get(model, {}), **kwargs})


class TestProductionCaps:
    @pytest.mark.parametrize("model", LENGTH_CARRYING_MODELS)
    def test_one_microsecond_is_accepted(self, model) -> None:
        assert _build(model, steps=ONE_US_STEPS_AT_4FS).steps == ONE_US_STEPS_AT_4FS
        assert _build(model, length_ns=1000.0).length_ns == pytest.approx(1000.0)

    @pytest.mark.parametrize("model", LENGTH_CARRYING_MODELS)
    def test_caps_are_shared_not_per_model(self, model) -> None:
        assert _build(model, steps=MAX_PRODUCTION_STEPS).steps == MAX_PRODUCTION_STEPS
        assert (_build(model, length_ns=MAX_PRODUCTION_NS).length_ns
                == pytest.approx(MAX_PRODUCTION_NS))
        with pytest.raises(ValidationError):
            _build(model, steps=MAX_PRODUCTION_STEPS + 1)
        with pytest.raises(ValidationError):
            _build(model, length_ns=MAX_PRODUCTION_NS * 2)

    @pytest.mark.parametrize("model", LENGTH_CARRYING_MODELS)
    def test_floor_still_holds(self, model) -> None:
        # Raising the ceiling must not have loosened the other end.
        with pytest.raises(ValidationError):
            _build(model, steps=99)
        with pytest.raises(ValidationError):
            _build(model, length_ns=0.0)

    def test_cap_headroom_stays_inside_namd_int32_numsteps(self) -> None:
        # NAMD parses `numsteps` into a 32-bit int; a cap above that would be
        # accepted here and then silently overflow in the generated conf.
        assert MAX_PRODUCTION_STEPS < 2**31 - 1

    def test_rejection_message_names_the_field(self) -> None:
        # The panel flattens `loc` + `msg` into its toast; a 422 with neither is
        # what produced "[object Object]".
        with pytest.raises(ValidationError) as exc:
            ProductionRunRequest(steps=MAX_PRODUCTION_STEPS + 1)
        (err,) = exc.value.errors()
        assert "steps" in err["loc"]
        assert err["msg"]


class TestForecastMeasuresTheRealVolume:
    def test_volume_root_of_a_missing_dir_resolves_to_its_mount(self, tmp_path) -> None:
        deep = tmp_path / "not" / "created" / "yet"
        root = volume_root(deep)
        assert root.exists()
        assert Path(tmp_path).is_relative_to(root)

    def test_forecast_reports_the_dir_and_volume_it_measured(self, tmp_path) -> None:
        fc = forecast(tmp_path / "job" / "package", 1024)
        assert fc["target_dir"].endswith("package")
        assert fc["volume"] == str(volume_root(tmp_path))
        assert fc["free_bytes"] > 0

    def test_forecast_of_an_absent_target_still_measures_a_real_volume(self, tmp_path) -> None:
        # An archived job's package dir may not exist yet when the panel asks.
        fc = forecast(tmp_path / "does" / "not" / "exist", 0)
        assert fc["free_bytes"] > 0
        assert fc["volume"]


class TestTrajectoryBytesTrackDcdFreq:
    def test_bytes_scale_inversely_with_dcd_freq(self) -> None:
        # 1 us at 4 fs, 62_677 atoms — the 2hb_1xT package from the bug report.
        dense = namd_run_output_bytes([(ONE_US_STEPS_AT_4FS, 2_500)], 62_677)
        sparse = namd_run_output_bytes([(ONE_US_STEPS_AT_4FS, 25_000)], 62_677)
        assert dense / sparse == pytest.approx(10.0, rel=0.01)

    def test_one_microsecond_is_tens_of_gigabytes_not_megabytes(self) -> None:
        # Guards the units: a 1 us run of a small origami is a ~80 GB trajectory at
        # the default interval, which is exactly why it needs confirming.
        gib = 1024 ** 3
        predicted = namd_run_output_bytes([(ONE_US_STEPS_AT_4FS, 2_500)], 62_677)
        assert 60 * gib < predicted < 120 * gib


class TestThroughputEstimate:
    def test_a_microsecond_run_is_predicted_in_days_not_hours(self) -> None:
        est = _throughput_estimate(62_677, 1000.0, 4.0)
        assert est["est_ns_per_day"] > 0
        # Whatever the exact model says, 1 us of a 62k-atom system is a multi-day
        # run — the fact the confirmation popup exists to surface.
        assert est["est_hours"] > 24.0

    def test_halving_the_timestep_doubles_the_wall_clock(self) -> None:
        fast = _throughput_estimate(62_677, 100.0, 4.0)
        slow = _throughput_estimate(62_677, 100.0, 2.0)
        assert slow["est_hours"] == pytest.approx(fast["est_hours"] * 2, rel=0.01)

    def test_a_short_run_stays_under_the_confirmation_threshold(self) -> None:
        # The 2 ns parent of the bug report's job: must NOT trip the popup.
        est = _throughput_estimate(62_677, 2.0, 4.0)
        assert est["est_hours"] < 24.0

    @pytest.mark.parametrize("n_atoms,length_ns", [(0, 100.0), (62_677, 0.0), (-1, 10.0)])
    def test_unknown_size_estimates_nothing_rather_than_guessing(
        self, n_atoms, length_ns,
    ) -> None:
        est = _throughput_estimate(n_atoms, length_ns, 4.0)
        assert est["est_ns_per_day"] is None
        assert est["est_hours"] is None
        assert est["throughput_source"] is None


class TestMeasuredThroughputBeatsTheModel:
    """A run that has actually happened must outrank the atom-count guess.

    The model (``md_optimize.predict_ns_per_day``) is calibrated on one machine and
    read **7.5x low** on this one for the 62.7k-atom 2hb: 29.5 ns/day predicted at
    2 fs against 220 measured, turning a ~2-day run into a "17 day" estimate that
    made the whole confirmation popup untrustworthy.
    """

    def test_a_measurement_wins_over_the_model(self) -> None:
        modelled = _throughput_estimate(62_677, 1000.0, 4.0)
        measured = _throughput_estimate(
            62_677, 1000.0, 4.0, measured=(220.0, 2.0, "d_01_production"))
        assert modelled["throughput_source"] == "model"
        assert measured["throughput_source"] == "measured:d_01_production"
        # 220 ns/day at 2 fs is 440 at 4 fs; the model said ~59.
        assert measured["est_ns_per_day"] == pytest.approx(440.0, rel=0.01)
        assert measured["est_hours"] < modelled["est_hours"]

    def test_a_measurement_is_rescaled_to_the_runs_timestep(self) -> None:
        # ns/day = steps/day x dt, so the same machine at 4 fs does twice the ns.
        at2 = _throughput_estimate(62_677, 100.0, 2.0, measured=(220.0, 2.0, "s"))
        at4 = _throughput_estimate(62_677, 100.0, 4.0, measured=(220.0, 2.0, "s"))
        assert at2["est_ns_per_day"] == pytest.approx(220.0)
        assert at4["est_ns_per_day"] == pytest.approx(440.0)
        assert at2["est_hours"] == pytest.approx(at4["est_hours"] * 2, rel=0.01)

    def test_the_model_still_covers_a_package_that_never_ran(self) -> None:
        est = _throughput_estimate(62_677, 100.0, 4.0, measured=None)
        assert est["throughput_source"] == "model"
        assert est["est_ns_per_day"] > 0

    @pytest.mark.parametrize("bad", [(0.0, 2.0, "s"), (220.0, 0.0, "s"), (-5.0, 2.0, "s")])
    def test_a_nonsense_measurement_falls_back_to_the_model(self, bad) -> None:
        est = _throughput_estimate(62_677, 100.0, 4.0, measured=bad)
        assert est["throughput_source"] == "model"

    def test_nothing_measurable_and_no_atoms_estimates_nothing(self) -> None:
        est = _throughput_estimate(0, 100.0, 4.0, measured=None)
        assert est == {"est_ns_per_day": None, "est_hours": None, "throughput_source": None}


class TestBenchmarkLineParsing:
    """The head-read that makes using a real log cheap on a multi-GB production log."""

    def _log(self, tmp_path, body: str):
        p = tmp_path / "seg.log"
        p.write_text(body)
        return p

    def test_reads_namd3_ns_per_day(self, tmp_path) -> None:
        from backend.core.namd_metrics import benchmark_ns_per_day
        log = self._log(tmp_path, "Info: blah\nBenchmark time: 0.0117889 s/step 220.158 ns/day 0 MB\n")
        assert benchmark_ns_per_day(log) == pytest.approx(220.158)

    def test_reads_the_older_days_per_ns_format(self, tmp_path) -> None:
        from backend.core.namd_metrics import benchmark_ns_per_day
        log = self._log(tmp_path, "Benchmark time: 0.002345 s/step 0.027123 days/ns 16.00 MB\n")
        assert benchmark_ns_per_day(log) == pytest.approx(1.0 / 0.027123)

    def test_takes_the_last_benchmark_line(self, tmp_path) -> None:
        # NAMD prints several; the last is the most equilibrated.
        from backend.core.namd_metrics import benchmark_ns_per_day
        log = self._log(tmp_path, "Benchmark time: 1 s/step 100 ns/day 0 MB\n"
                                  "Benchmark time: 1 s/step 220 ns/day 0 MB\n")
        assert benchmark_ns_per_day(log) == pytest.approx(220.0)

    def test_finds_it_when_gigabytes_of_energy_lines_follow(self, tmp_path) -> None:
        # The real shape: benchmark lines near the HEAD, then the run's whole output.
        from backend.core.namd_metrics import benchmark_ns_per_day
        log = self._log(tmp_path,
                        "Benchmark time: 1 s/step 220 ns/day 0 MB\n" + "ENERGY: 1 2 3\n" * 50_000)
        assert benchmark_ns_per_day(log) == pytest.approx(220.0)

    def test_none_when_the_run_has_not_timed_a_step_yet(self, tmp_path) -> None:
        from backend.core.namd_metrics import benchmark_ns_per_day
        assert benchmark_ns_per_day(self._log(tmp_path, "Info: starting up\n")) is None

    def test_none_on_a_missing_log(self, tmp_path) -> None:
        from backend.core.namd_metrics import benchmark_ns_per_day
        assert benchmark_ns_per_day(tmp_path / "nope.log") is None
