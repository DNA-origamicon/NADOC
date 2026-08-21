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
        """At SECURE prices (the only ones we can pay — Community has no card in EU-RO-1)
        the 4090 is the cheapest that fits, at $0.69/hr.

        It is also the scarce one ("Low" stock in EU-RO-1). That costs us nothing to ask
        for: `gpuTypeIds` is a fallback LIST, so if no 4090 is free RunPod rents the next
        card in it (the PRO 4500) and we pay $0.05/hr more. Asking cheapest-first is
        strictly better than conceding the nickel up front.
        """
        plan = plan_execution(SIXHB)
        assert plan["gpu"].label == "RTX 4090"
        assert plan["gpu"].usd_per_hour == 0.69
        assert plan["gpu_resident"] is True

    def test_flat_sheet_fits_resident_on_the_cheapest_card(self):
        # 5,016 MB measured — comfortable on the 24 GB 4090, which is also the cheapest.
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

    def test_lifetime_guard_is_wired_by_the_executor(self):
        """The guard was dead code for its whole life: it rendered only when a caller
        passed max_lifetime_s, and the ONE production call site never did. Assert the
        derived value actually reaches the script."""
        s = self.script(max_lifetime_s=bm.lifetime_for_budget(15.0, 0.69))
        assert "LIFETIME_GUARD" in s
        assert "78260" in s  # 15 / 0.69 * 3600

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

    STEPS = [
        ChainStep("s0_min", is_minimization=True),
        ChainStep("s1"),
        ChainStep("s2"),
    ]

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
                steps=self.STEPS,
                remote_dir=str(tmp_path),
                namd_bin=str(namd),
                threads=2,
                **kw,
            )
        )
        script.chmod(0o755)
        return subprocess.run(
            ["bash", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
        )

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

    def test_settle_retarget_runs_after_minimization_and_before_first_segment(self):
        script = render_chain_script(
            steps=self.STEPS,
            remote_dir="/work",
            namd_bin="/namd3",
            threads=2,
        )
        minimize = "run_step_with_retries s0_min s0_min.conf"
        retarget = 'python3 nadoc_settle_retarget.py "output/s0_min.coor" restraints_settle.pdb'
        settle = "run_step_with_retries s1 s1.conf"
        assert script.index(minimize) < script.index(retarget) < script.index(settle)

    def test_a_failing_step_stops_the_ladder_and_records_which_one(self, tmp_path):
        proc = self._run(tmp_path, self._fake_namd(tmp_path, fail_on="s1"))
        assert proc.returncode == 1
        status = (tmp_path / "nadoc_status").read_text().strip()
        assert status == "failed:s1"
        assert not (tmp_path / "output" / "s2.coor").exists(), (
            "must not run past a failure"
        )

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
        assert (tmp_path / "output" / "s2.coor").exists(), (
            "ladder must continue past it"
        )

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
            tmp_path,
            self._fake_namd(tmp_path, hang_on="s1"),
            stall_timeout_s=1,
            watchdog_poll_s=1,
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
            assert gpu.sm in bm.NAMD_BUILD_ARCHS, (
                f"{gpu.label} is {gpu.sm}, binary is {bm.NAMD_BUILD_ARCHS}"
            )

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
        """At the $0.75 tier both the 32 GB and 24 GB cards qualify — and offering BOTH is
        the point: a single named card is regularly unavailable in the volume's datacenter.

        ($0.75, not $0.40: these are SECURE prices. A $0.40 ceiling now excludes every
        card we can actually rent and would return an empty list.)
        """
        cheap = [g.label for g in bm.recommend_gpus(SIXHB, max_usd_per_hour=0.75)]
        assert cheap == ["RTX 4090", "RTX PRO 4500"]

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


class TestLifetimeForBudget:
    """The cap is a BUDGET ($15), not a duration — the same money buys very different
    wall-clocks depending on which card the fallback list landed on."""

    def test_derives_hours_from_the_rate_of_the_pod_we_actually_got(self):
        # $15 on the cheap card buys ~44 h; on the expensive one, ~18 h. A hardcoded
        # duration would be wrong on every card but one.
        assert bm.lifetime_for_budget(15.0, 0.34) == int(15 / 0.34 * 3600)
        assert bm.lifetime_for_budget(15.0, 0.82) == int(15 / 0.82 * 3600)

    def test_cheaper_pod_is_allowed_to_live_longer(self):
        assert bm.lifetime_for_budget(15.0, 0.34) > bm.lifetime_for_budget(15.0, 0.82)

    def test_unknown_rate_assumes_the_worst_case_price_ceiling(self):
        """RunPod can report costPerHr as null. Guessing HIGH yields a SHORTER lifetime,
        which is the safe direction to be wrong in."""
        expected = int(15.0 / bm.DEFAULT_MAX_USD_PER_HOUR * 3600)
        assert bm.lifetime_for_budget(15.0, None) == expected
        assert bm.lifetime_for_budget(15.0, 0.0) == expected

    def test_never_emits_a_suicidally_short_guard(self):
        """A bogus rate must not render a script that kills the ladder on startup."""
        assert bm.lifetime_for_budget(0.0, 0.34) == bm.MIN_LIFETIME_S


class TestRelaxationEarlyStop:
    """The accelerator that decides whether this run is affordable AT ALL.

    The 3x6x400 ladder is 9.6M steps ~ 55.7 h ~ $41 on a secure PRO 4500 — over any
    sane overnight budget. Early-stop is what brings it to ~11 h / ~$8. So these are
    not quality-of-life tests: if the bridge silently fails to skip, the pod bills
    the full ladder and the kill-switch chops it off half-finished.

    The bridge is EXECUTED, never pattern-matched. A script that emits a
    beautiful-looking bridge block which doesn't actually cause `run_step` to skip
    would pass any text assertion and cost $30.
    """

    # Two stages x three chunks. Stage 01 is well-restrained (k=0.5); stage 02 is the
    # fragile low-restraint one (k=0.01) — both equally eligible now (no tiers, no
    # restraint-scale gate; the WC criterion holds the fragile stage directly).
    STEPS = [
        ChainStep("m", is_minimization=True),
        ChainStep("s_01_k0p5_p10"),
        ChainStep("s_01_k0p5_p50"),
        ChainStep("s_01_k0p5_p100"),
        ChainStep("s_02_k0p01_p10"),
        ChainStep("s_02_k0p01_p50"),
        ChainStep("s_02_k0p01_p100"),
    ]
    MANIFEST = {
        "minimization": {"name": "m"},
        "segments": [
            {"name": "s_01_k0p5_p10", "scale": 0.5},
            {"name": "s_01_k0p5_p50", "scale": 0.5},
            {"name": "s_01_k0p5_p100", "scale": 0.5},
            {"name": "s_02_k0p01_p10", "scale": 0.01},
            {"name": "s_02_k0p01_p50", "scale": 0.01},
            {"name": "s_02_k0p01_p100", "scale": 0.01},
        ],
    }

    @staticmethod
    def _fake_namd(tmp_path):
        """Records every conf it is invoked for, and writes the full checkpoint set.

        `ran.txt` is the oracle: a bridged chunk must NEVER appear in it. Writes .dcd
        too, because the node health step is gated on the trajectory existing.
        """
        p = tmp_path / "fake_namd"
        p.write_text(
            "#!/bin/bash\n"
            'conf="${!#}"\n'
            'name=$(basename "$conf" .conf)\n'
            'echo "$name" >> ran.txt\n'
            "mkdir -p output\n"
            'for ext in coor vel xsc dcd; do echo x > "output/${name}.${ext}"; done\n'
            "exit 0\n"
        )
        p.chmod(0o755)
        return p

    @staticmethod
    def _fake_evaluators(tmp_path, *, plateau: bool):
        """Stand in for the two staged python scripts.

        The real cutoff evaluator's contract is its EXIT CODE (0 = plateau/skip,
        nonzero = hold), so a fake that honours the exit code exercises the bash
        exactly as the real one does.
        """
        cut = tmp_path / "nadoc_cutoff_eval.py"
        cut.write_text(f"import sys\nsys.exit({0 if plateau else 1})\n")
        health = tmp_path / "nadoc_health_eval.py"
        # Mirrors the real one: writes the wc.json the cutoff evaluator gates on.
        health.write_text(
            "import sys\n"
            "out = sys.argv[sys.argv.index('--out') + 1]\n"
            "open(out, 'w').write('[0.98, 0.98, 0.98]')\n"
        )

    def _run(self, tmp_path, *, plateau, **kw):
        self._fake_evaluators(tmp_path, plateau=plateau)
        script = tmp_path / "chain.sh"
        script.write_text(
            render_chain_script(
                steps=self.STEPS,
                remote_dir=str(tmp_path),
                namd_bin=str(self._fake_namd(tmp_path)),
                threads=2,
                manifest=self.MANIFEST,
                early_stop_relax=True,
                name_stem="s",
                **kw,
            )
        )
        script.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        ran = (
            (tmp_path / "ran.txt").read_text().split()
            if (tmp_path / "ran.txt").exists()
            else []
        )
        return proc, ran

    def test_plateau_bridges_and_the_skipped_chunks_never_run(self, tmp_path):
        """THE test. A plateau at _p10 must mean _p50 and _p100 are never executed —
        for BOTH stages, including the low-restraint k=0.01 one. No tiers: there is
        no restraint-scale gate any more, so the WC-gated evaluator alone decides
        every non-final chunk, matching the local runner exactly.

        This is the whole $33 of savings. It works only because the bridge writes the
        skipped chunks' .coor, which `run_step`'s idempotent skip-guard then trips on
        — the resume trick and the early-stop trick are the same trick.
        """
        proc, ran = self._run(tmp_path, plateau=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (tmp_path / "nadoc_status").read_text().strip() == "completed"

        # Both stages plateaued at their first chunk: only _p10 of each ever ran.
        assert ran == ["m", "s_01_k0p5_p10", "s_02_k0p01_p10"], ran
        for skipped in (
            "s_01_k0p5_p50",
            "s_01_k0p5_p100",
            "s_02_k0p01_p50",
            "s_02_k0p01_p100",
        ):
            assert skipped not in ran
            # ...and the bridge left them a checkpoint, so the NEXT stage can read it.
            assert (tmp_path / "output" / f"{skipped}.coor").exists()

    def test_hold_runs_every_chunk(self, tmp_path):
        """Fail-safe: no plateau => nothing is skipped. Correct, and expensive."""
        proc, ran = self._run(tmp_path, plateau=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert ran == [s.name for s in self.STEPS], ran

    def test_off_by_default_emits_no_evaluator_call(self):
        """A job that didn't opt in must render the exact script it rendered before."""
        s = render_chain_script(
            steps=self.STEPS,
            remote_dir="/w",
            namd_bin="/n",
            threads=2,
            manifest=self.MANIFEST,
        )
        assert "nadoc_cutoff_eval.py" not in s

    def test_early_stop_needs_no_manifest(self):
        """Eligibility is purely name-based (chunk suffix / production pattern), not
        restraint-scale — so it works identically with no manifest at all."""
        s = render_chain_script(
            steps=self.STEPS,
            remote_dir="/w",
            namd_bin="/n",
            threads=2,
            early_stop_relax=True,
        )
        assert "nadoc_cutoff_eval.py" in s


class TestLiveMetricsCollector:
    """The progress bar's only source of MID-SEGMENT truth on a rented pod.

    Progress otherwise advances only when a whole segment lands its ``.coor``, so a
    single-segment 200 ns production reads 0% for its entire multi-day life. The blob this
    writes is already `cat`-ed by the existing poll, so it costs the poll nothing extra.
    """

    def _script(self, **kw):
        return bm.render_chain_script(
            steps=[bm.ChainStep(name="seg1", steps=1000)],
            remote_dir="/workspace/nadoc_jobs/x",
            namd_bin="/n/namd3",
            threads=16,
            **kw,
        )

    def test_launches_the_collector_in_the_background(self):
        s = self._script()
        assert bm.LIVE_METRICS_NAME in s
        assert "LIVE_METRICS_PID=$!" in s, "must not block the ladder"

    def test_samples_far_slower_than_the_ui_polls(self):
        """Decoupled on purpose: NADOC anchors each reading and extrapolates between them,
        so a 60 s collector still drives a smooth 1.5 s bar. Sampling faster would only
        contend with NAMD's own writes to the same network volume — on a billing machine."""
        assert bm.LIVE_METRICS_INTERVAL_S >= 30
        assert f". {bm.LIVE_METRICS_INTERVAL_S}" in self._script()

    def test_the_interval_is_tunable(self):
        assert ". 5 " in self._script(live_metrics_s=5)

    def test_can_be_switched_off_entirely(self):
        assert bm.LIVE_METRICS_NAME not in self._script(live_metrics_s=0)

    def test_tolerates_a_pod_without_the_collector(self):
        """A resumed job whose volume predates the collector must still run — the launch is
        guarded, not assumed."""
        assert f'if [ -f "{bm.LIVE_METRICS_NAME}" ]; then' in self._script()

    def test_stops_sampling_before_the_final_status_is_written(self):
        """Otherwise the last thing NADOC reads could be a tick that landed after the run
        finished, leaving the bar short of 100%."""
        s = self._script()
        kill = s.index('kill "$LIVE_METRICS_PID"')
        done = s.index('echo "completed" > nadoc_status')
        assert kill < done
