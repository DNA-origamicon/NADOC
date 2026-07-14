"""Pure-logic pins for the RunPod NAMD backend (backend/core/runpod_script.py).

Each test here encodes something that was learned by breaking it on a real rented
GPU, not something derived from a spec. Read the failure notes before "simplifying"
any of these.
"""

from __future__ import annotations

import subprocess

import pytest

from backend.core import runpod_script as bm
from backend.core.runpod_script import (
    GPU_TYPES,
    ChainStep,
    completed_steps,
    heartbeat_is_stale,
    namd_threads,
    next_step,
    parse_status_file,
    plan_execution,
    recommend_gpu,
    render_chain_script,
    required_vram_mb,
)

# ── measured reference points (RTX 4090, NAMD 3.0.2p1, 2026-07-13) ────────────
SIXHB = 225_504
FLAT = 1_442_735
VOLTRON = 5_656_632


class TestVramModel:
    """The fits must reproduce the systems they were fitted to."""

    @pytest.mark.parametrize(
        "atoms, resident, measured_mb",
        [
            (SIXHB, False, 854),
            (FLAT, False, 3_496),
            (VOLTRON, False, 12_334),
            (SIXHB, True, 1_114),
            (FLAT, True, 5_016),
        ],
    )
    def test_predicts_measured_vram_within_10pct(self, atoms, resident, measured_mb):
        got = required_vram_mb(atoms, gpu_resident=resident)
        assert got == pytest.approx(measured_mb, rel=0.10), (
            f"{atoms:,} atoms resident={resident}: predicted {got:.0f} MB "
            f"vs measured {measured_mb} MB"
        )

    def test_resident_costs_more_vram_than_offload(self):
        assert required_vram_mb(FLAT, gpu_resident=True) > required_vram_mb(
            FLAT, gpu_resident=False
        )


class TestGpuSizing:
    def test_small_system_gets_the_cheapest_card_resident(self):
        plan = plan_execution(SIXHB)
        assert plan["gpu"].label == "RTX 4090"
        assert plan["gpu_resident"] is True

    def test_flat_sheet_still_fits_resident_on_a_4090(self):
        # 5,016 MB measured, 24.5 GB card => comfortable.
        plan = plan_execution(FLAT)
        assert plan["gpu"].label == "RTX 4090"
        assert plan["gpu_resident"] is True

    def test_voltroncore_is_too_big_for_resident_on_a_4090(self):
        """5.66M atoms needs ~18.6 GB resident; 85% of 24.5 GB is ~20.9 GB, so it
        *nominally* fits — but offload measured 12.3 GB and resident was never
        proven at this size. The point of this test is that the planner makes a
        DEFINITE, inspectable choice rather than silently guessing."""
        plan = plan_execution(VOLTRON)
        assert plan["gpu"] is not None
        assert "RTX 4090" in plan["gpu"].label or plan["gpu"].vram_mb > 24_564

    def test_absurd_system_gets_no_gpu_and_says_why(self):
        plan = plan_execution(200_000_000)
        assert plan["gpu"] is None
        assert "carve" in plan["reason"].lower() or "gbis" in plan["reason"].lower()

    def test_recommend_gpu_returns_the_cheapest_that_fits(self):
        gpu = recommend_gpu(SIXHB, gpu_resident=True)
        cheapest = min(GPU_TYPES, key=lambda g: g.usd_per_hour)
        assert gpu.key == cheapest.key


class TestThreadCount:
    def test_halves_vcpus_because_oversubscribing_smt_halves_throughput(self):
        """MEASURED on the pod: 32 vCPU / 16 physical cores.
             +p16 -> 41.38 ns/day
             +p32 -> 18.85 ns/day   (2.2x SLOWER)
        RunPod advertises vCPUs (SMT threads), so +p must be vcpus//2."""
        assert namd_threads(32) == 16
        assert namd_threads(12) == 6  # the local Ryzen 5 3600
        assert namd_threads(1) == 1  # never zero

    def test_non_smt_host_uses_all_cores(self):
        assert namd_threads(8, smt=False) == 8


class TestChainScript:
    STEPS = [
        ChainStep("job_00_min", is_minimization=True),
        ChainStep("job_01_k0p5_p10"),
        ChainStep("job_02_k0p1_p10"),
    ]

    def script(self, **kw):
        return render_chain_script(
            steps=self.STEPS,
            remote_dir="/workspace/jobs/abc",
            namd_bin="/workspace/namd/namd3",
            threads=16,
            **kw,
        )

    def test_every_step_appears_in_order(self):
        s = self.script()
        idx = [s.index(step.name) for step in self.STEPS]
        assert idx == sorted(idx), "steps must run in ladder order"

    def test_steps_are_idempotent_so_resume_skips_completed_work(self):
        """This is what makes an interruptible (spot) pod usable: after a reclaim we
        relaunch the SAME script and it skips everything already on the volume."""
        s = self.script()
        assert 'if [ -f "output/${name}.coor" ]' in s
        assert "SKIP" in s

    def test_uses_the_spawned_pid_and_never_greps_for_namd_by_name(self):
        """NAMD renames its process to "NAMD masterPe". `pgrep -x namd3` therefore
        matches NOTHING and reports a live job as dead — that is exactly how a
        runaway CPU run survived a `pkill` and ate the machine for an hour."""
        s = self.script()
        assert "kill -0 $pid" in s
        assert "pgrep" not in s
        assert "pkill -9 -x namd" not in s

    def test_has_a_stall_watchdog(self):
        """A NAMD minimisation on a degenerate structure never terminates — the line
        minimiser sits on NaN indefinitely, billing the whole time."""
        s = self.script(stall_timeout_s=900)
        assert "900" in s
        assert "STALL" in s

    def test_max_lifetime_guard_is_emitted_when_asked(self):
        assert "LIFETIME_GUARD" in self.script(max_lifetime_s=7200)
        assert "LIFETIME_GUARD" not in self.script()

    def test_writes_status_and_heartbeat_sentinels(self):
        s = self.script()
        assert "nadoc_status" in s
        assert "nadoc_heartbeat" in s
        assert 'echo "completed" > nadoc_status' in s

    def test_watchdog_stdio_is_detached(self):
        """LOAD-BEARING. The watchdog subshell inherits the script's stdout pipe, and
        its orphaned `sleep` holds that pipe open after NAMD exits — so any reader of
        the script's output blocks for a full poll interval PER STEP and the job looks
        hung. (Caught as a 30s unit test that should have taken 2s.) The watchdog
        reports via files, so it needs no stdio."""
        s = self.script()
        assert "done ) >/dev/null 2>&1 &" in s

    def test_does_not_use_set_e(self):
        """`set -e` would abort before the failure status file is written, and the
        poller would see a pod that vanished with no explanation."""
        s = self.script()
        assert "set -e" not in s
        assert "set -uo pipefail" in s

    def test_paths_are_shell_quoted(self):
        s = render_chain_script(
            steps=[ChainStep("s")],
            remote_dir="/workspace/my jobs/a b",
            namd_bin="/workspace/namd 3/namd3",
            threads=4,
        )
        assert "'/workspace/my jobs/a b'" in s
        assert "'/workspace/namd 3/namd3'" in s


class TestChainScriptActuallyRuns:
    """Execute the generated bash against a FAKE namd.

    The text assertions above would happily pass a script that is syntactically fine
    but semantically broken (bad `local` scoping in the watchdog subshell, a skip
    test that never fires, a status file never written). Resume-after-reclaim is the
    entire value proposition on an interruptible pod, so it gets executed, not
    pattern-matched.
    """

    STEPS = [ChainStep("s0_min", is_minimization=True), ChainStep("s1"), ChainStep("s2")]

    @staticmethod
    def _fake_namd(
        tmp_path,
        *,
        fail_on: str | None = None,
        hang_on: str | None = None,
        shrink_on: str | None = None,
        shrink_times: int = 1,
    ):
        """A stand-in for namd3: writes the .coor its caller expects.

        `shrink_on` makes it emit NAMD's real cell-shrink fatal on its first
        `shrink_times` invocations of that step, then succeed — exactly how a real
        NPT box behaves as it relaxes to equilibrium density.
        """
        p = tmp_path / "fake_namd"
        p.write_text(
            "#!/bin/bash\n"
            'conf="${!#}"\n'  # last arg is the conf file
            'name=$(basename "$conf" .conf)\n'
            f"if [ \"$name\" = '{fail_on or chr(0)}' ]; then exit 7; fi\n"
            f"if [ \"$name\" = '{hang_on or chr(0)}' ]; then sleep 300; fi\n"
            f"if [ \"$name\" = '{shrink_on or chr(0)}' ]; then\n"
            '  n=$(cat ".shrink_$name" 2>/dev/null || echo 0); n=$((n+1))\n'
            '  echo $n > ".shrink_$name"\n'
            f"  if [ $n -le {int(shrink_times)} ]; then\n"
            "    echo 'FATAL ERROR: Periodic cell has become too small for original"
            " patch grid!'\n"
            "    exit 1\n"
            "  fi\n"
            "fi\n"
            "mkdir -p output\n"
            'echo coords > "output/${name}.coor"\n'
            "exit 0\n"
        )
        p.chmod(0o755)
        return p

    def _run(self, tmp_path, namd, **kw):
        script = tmp_path / "chain.sh"
        script.write_text(
            render_chain_script(
                steps=self.STEPS, remote_dir=str(tmp_path),
                namd_bin=str(namd), threads=2, **kw,
            )
        )
        script.chmod(0o755)
        return subprocess.run(["bash", str(script)], cwd=tmp_path,
                              capture_output=True, text=True, timeout=120)

    def test_full_ladder_runs_and_reports_completed(self, tmp_path):
        proc = self._run(tmp_path, self._fake_namd(tmp_path))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (tmp_path / "nadoc_status").read_text().strip() == "completed"
        for step in self.STEPS:
            assert (tmp_path / "output" / f"{step.name}.coor").exists()

    def test_rerun_skips_completed_steps(self, tmp_path):
        """The resume path: relaunch the same script on a reclaimed pod, and every
        step whose .coor is already on the network volume is skipped."""
        namd = self._fake_namd(tmp_path)
        self._run(tmp_path, namd)
        # A namd that would ERROR if invoked proves nothing was re-run.
        exploding = tmp_path / "must_not_run"
        exploding.write_text("#!/bin/bash\nexit 99\n")
        exploding.chmod(0o755)
        proc = self._run(tmp_path, exploding)
        assert proc.returncode == 0, "re-run must skip, not re-execute"
        assert proc.stdout.count("SKIP") == len(self.STEPS)
        assert "START" not in proc.stdout

    def test_partial_progress_resumes_at_the_right_step(self, tmp_path):
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "s0_min.coor").write_text("x")
        proc = self._run(tmp_path, self._fake_namd(tmp_path))
        assert proc.returncode == 0
        assert "SKIP  s0_min" in proc.stdout
        assert "START s1" in proc.stdout

    def test_a_failing_step_stops_the_ladder_and_records_which_one(self, tmp_path):
        proc = self._run(tmp_path, self._fake_namd(tmp_path, fail_on="s1"))
        assert proc.returncode == 1
        status = (tmp_path / "nadoc_status").read_text().strip()
        assert status == "failed:s1"
        assert not (tmp_path / "output" / "s2.coor").exists(), "must not run past a failure"

    def test_cell_shrink_is_retried_not_treated_as_a_failure(self, tmp_path):
        """MEASURED on the 4090: BOTH offload VoltronCore cells died with "Periodic
        cell has become too small for original patch grid". That is an NPT box
        relaxing ~3% to equilibrium density and crossing NAMD's fixed patch grid —
        it is self-healing on restart, NOT a blow-up. A pod that treats it as fatal
        throws away a 25-minute minimisation and bills you for nothing."""
        proc = self._run(
            tmp_path,
            self._fake_namd(tmp_path, shrink_on="s1", shrink_times=1),
            watchdog_poll_s=1,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "SHRINK s1" in proc.stdout
        assert (tmp_path / "nadoc_status").read_text().strip() == "completed"
        assert (tmp_path / "output" / "s2.coor").exists(), "ladder must continue past it"

    def test_cell_shrink_retries_are_bounded(self, tmp_path):
        """A box that shrinks forever is a real failure. Don't loop on the meter."""
        proc = self._run(
            tmp_path,
            self._fake_namd(tmp_path, shrink_on="s1", shrink_times=99),
            watchdog_poll_s=1,
        )
        assert proc.returncode == 1
        assert (tmp_path / "nadoc_status").read_text().strip() == "failed:s1"

    def test_stall_watchdog_kills_a_wedged_step(self, tmp_path):
        """The zombie scenario: NAMD alive, producing no output, forever. Bill stops
        here or it doesn't stop at all."""
        proc = self._run(
            tmp_path, self._fake_namd(tmp_path, hang_on="s1"),
            stall_timeout_s=1, watchdog_poll_s=1,
        )
        assert proc.returncode == 1
        assert (tmp_path / "nadoc_stall").exists()
        assert (tmp_path / "nadoc_status").read_text().strip() == "failed:s1"


class TestStatusParsing:
    def test_running_completed_lifetime(self):
        assert parse_status_file("running")["state"] == "running"
        assert parse_status_file("completed\n")["state"] == "completed"
        assert parse_status_file("lifetime")["state"] == "lifetime"

    def test_failed_carries_the_segment_name(self):
        got = parse_status_file("failed:job_02_k0p1_p10")
        assert got["state"] == "failed"
        assert got["segment"] == "job_02_k0p1_p10"

    def test_garbage_is_unknown_not_an_exception(self):
        assert parse_status_file("")["state"] == "unknown"
        assert parse_status_file("¯\\_(ツ)_/¯")["state"] == "unknown"


class TestResume:
    STEPS = [ChainStep("a", is_minimization=True), ChainStep("b"), ChainStep("c")]

    def test_completed_steps_read_from_a_coor_listing(self):
        listing = "output/a.coor\noutput/b.coor\noutput/b.vel\n"
        assert completed_steps(listing) == {"a", "b"}

    def test_next_step_is_the_first_incomplete_one(self):
        assert next_step(self.STEPS, {"a"}).name == "b"
        assert next_step(self.STEPS, {"a", "b"}).name == "c"

    def test_next_step_is_none_when_the_ladder_is_done(self):
        assert next_step(self.STEPS, {"a", "b", "c"}) is None

    def test_empty_listing_means_start_from_the_beginning(self):
        assert completed_steps("") == set()
        assert next_step(self.STEPS, set()).name == "a"


class TestHeartbeat:
    def test_fresh_heartbeat_is_not_stale(self):
        assert heartbeat_is_stale(1000, 1100, tolerance_s=300) is False

    def test_silent_pod_is_stale(self):
        """On an interruptible pod this is NORMAL — the pod was reclaimed. It means
        'resume', not 'fail'."""
        assert heartbeat_is_stale(1000, 2000, tolerance_s=300) is True

    def test_missing_heartbeat_is_stale(self):
        assert heartbeat_is_stale(None, 500) is True


class TestOnlyOfferCardsTheBinaryCanRun:
    """Each of these cost a real, billing pod to learn."""

    def test_never_offers_a_card_of_the_wrong_cuda_arch(self):
        """THE bug that wasted a pod launch. `build_patched_namd.sh` compiles for ONE
        sm_XX ("single arch: ~4x faster nvcc pass") and the volume's build is sm_89. An
        A100 (sm_80) rented FINE and then died at step 0:

            FATAL ERROR: CUDA error cudaMemcpyToSymbol(constExclusions, ...)
            bindExclusions ... no kernel image is available for execution on the device

        Offering a card the binary cannot run on is not a fallback — it is a guaranteed
        failure that bills."""
        for gpu in bm.recommend_gpus(SIXHB):
            assert gpu.sm in bm.NAMD_BUILD_ARCHS, f"{gpu.label} is {gpu.sm}, binary is {bm.NAMD_BUILD_ARCHS}"

    def test_the_shipped_gpu_table_contains_no_incompatible_cards(self):
        for gpu in bm.GPU_TYPES:
            assert gpu.sm in bm.NAMD_BUILD_ARCHS, (
                f"{gpu.label} ({gpu.sm}) cannot run the sm_89 build — remove it, or "
                f"rebuild NAMD multi-arch and widen NAMD_BUILD_ARCHS"
            )

    def test_a_price_ceiling_stops_it_renting_an_h100_for_a_duplex(self):
        """Unbounded 'fall back to whatever is available' rented a $1.39/hr A100 to relax
        a 225k-atom system whose cheapest viable card is $0.34/hr."""
        for gpu in bm.recommend_gpus(SIXHB):
            assert gpu.usd_per_hour <= bm.DEFAULT_MAX_USD_PER_HOUR

    def test_the_ceiling_is_configurable_for_a_genuinely_big_job(self):
        cheap = bm.recommend_gpus(SIXHB, max_usd_per_hour=0.40)
        assert [g.label for g in cheap] == ["RTX 4090"]

    def test_still_offers_several_cards_so_availability_failures_are_survivable(self):
        """A network volume pins the datacenter; one named card is regularly unavailable
        there (500 "There are no instances currently available")."""
        assert len(bm.recommend_gpus(SIXHB)) >= 2


class TestThreadCap:
    def test_a_128_vcpu_host_does_not_get_p64(self):
        """The A100 pod had 128 vCPUs, so vcpus//2 asked for +p64 — far off the end of
        NAMD's single-GPU scaling curve (measured: +p8 42.98, +p16 41.38, +p32 18.85)."""
        assert bm.namd_threads(128) == bm.MAX_NAMD_THREADS == 16

    def test_a_small_host_is_unaffected(self):
        assert bm.namd_threads(32) == 16
        assert bm.namd_threads(12) == 6
        assert bm.namd_threads(4) == 2
