"""RunPod supervisor + the routes_md dispatch.

The properties that keep you solvent:

* **Start** on a RunPod job must NOT require a local NAMD (it runs on the pod), and must
  NOT fall through to the local runner (it would seize the user's desktop GPU).
* **Stop** on a RunPod job must NOT fall into the Alpine ``scancel`` path — that path
  finds no cluster session, reports "stopped", and LEAVES THE POD BILLING.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.core import runpod_supervisor as sup
from backend.core.md_job import MdSegmentStatus, MdStatus, new_job


def _run(coro):
    return asyncio.run(coro)


def _job_with_package(tmp_path, n_atoms=225_504, with_manifest=True):
    job = new_job("d", "equilibrium_aware_namd", "d", "package/d_namd_solvated")
    job.segments = [
        MdSegmentStatus(name="d_01", stage="relax", percent=10.0, steps=100)
    ]
    pkg = job.package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    # A REALISTIC psfgen header: one REMARKS line per applied patch, so !NTITLE is
    # huge and !NATOM sits far into the file. 6hb has 604 title lines (!NATOM at byte
    # 18,729); flat_1x50 has 7,342 and !NATOM lands beyond 64 KB. A fixed-size head read
    # finds it in NEITHER — that bug shipped and broke every real job.
    title = "\n".join(f" REMARKS patch {i} applied" for i in range(8000))
    (pkg / "d.psf").write_text(
        f"PSF\n\n    8000 !NTITLE\n{title}\n\n {n_atoms} !NATOM\n"
    )
    (pkg / "d_hmr.psf").write_text("decoy — must NOT be picked for the atom count\n")
    if with_manifest:
        (pkg / "manifest.json").write_text(
            json.dumps({"minimization": {"name": "d_00_min_enm_k0p5"}})
        )
    else:
        (pkg / "d_00_min_enm_k0p5.conf").write_text("minimize 4800\n")
    return job


class TestPackageIntrospection:
    def test_reads_the_real_solvated_atom_count(self, tmp_path):
        """Sizing depends on this: 6hb 225,504 / flat 1,442,735 / VoltronCore 5,656,632.
        The DNA-only count would pick a card far too small."""
        job = _job_with_package(tmp_path, n_atoms=5_656_632)
        assert sup.n_atoms_for(job, tmp_path) == 5_656_632

    def test_ignores_the_hmr_psf(self, tmp_path):
        """Both PSFs exist in every fast package and are the same byte size. Picking the
        HMR one would read a mass-repartitioned decoy."""
        job = _job_with_package(tmp_path)
        assert sup.n_atoms_for(job, tmp_path) == 225_504

    def test_min_name_from_the_manifest(self, tmp_path):
        job = _job_with_package(tmp_path)
        assert sup.min_name_for(job, tmp_path) == "d_00_min_enm_k0p5"

    def test_min_name_falls_back_to_the_conf_when_no_manifest(self, tmp_path):
        job = _job_with_package(tmp_path, with_manifest=False)
        assert sup.min_name_for(job, tmp_path) == "d_00_min_enm_k0p5"

    def test_natom_is_found_past_a_huge_ntitle_block(self, tmp_path):
        """REGRESSION. psfgen writes one REMARKS line per patch, so !NATOM is ~19 KB into
        6hb's PSF and >64 KB into flat_1x50's. The original 4096-byte head read found it
        in neither and every real job died with AttributeError: 'NoneType'."""
        job = _job_with_package(tmp_path, n_atoms=1_442_735)
        psf = job.package_dir(tmp_path) / "d.psf"
        assert psf.stat().st_size > 100_000, (
            "fixture must have a realistically big header"
        )
        assert psf.read_text()[:4096].find("!NATOM") == -1, (
            "must NOT be in the first 4 KB"
        )
        assert sup.n_atoms_for(job, tmp_path) == 1_442_735

    def test_a_package_with_no_psf_is_a_clear_error_not_a_crash(self, tmp_path):
        job = new_job("d", "equilibrium_aware_namd", "d", "package/empty")
        job.package_dir(tmp_path).mkdir(parents=True)
        with pytest.raises(RuntimeError, match="no PSF"):
            sup.n_atoms_for(job, tmp_path)


class FakeClient:
    def __init__(self):
        self.terminated: list[str] = []

    async def terminate_pod(self, pod_id):
        self.terminated.append(pod_id)

    async def list_pods(self):
        return []


class TestStopDestroysThePod:
    def test_stop_terminates_the_recorded_pod(self, tmp_path):
        """A cancelled task whose pod survives is a GPU billing forever with nothing
        watching it. stop_job kills the pod id directly, belt-and-braces."""
        client = FakeClient()
        sup._PODS["j1"] = "pod-xyz"  # noqa: SLF001 — as if provisioning had happened
        try:
            assert _run(sup.stop_job("j1", client=client)) is True
            assert client.terminated == ["pod-xyz"]
            assert sup.pod_id_for("j1") is None
        finally:
            sup._PODS.pop("j1", None)  # noqa: SLF001

    def test_stop_without_a_client_still_clears_state(self, tmp_path):
        """Disconnected: we cannot confirm the kill. State is cleared, and the ROUTE
        warns the user — silence here would hide a live pod."""
        sup._PODS["j2"] = "pod-abc"  # noqa: SLF001
        try:
            assert _run(sup.stop_job("j2", client=None)) is True
        finally:
            sup._PODS.pop("j2", None)  # noqa: SLF001

    def test_stopping_an_unknown_job_is_harmless(self):
        assert _run(sup.stop_job("nope", client=FakeClient())) is False


class TestOrphanReaper:
    def test_reaps_a_nadoc_pod_nobody_is_tracking(self):
        """A dev-server reload or a crash orphans the pod: it keeps running, keeps
        billing, and nothing is watching it."""

        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod

                return [
                    parse_pod(
                        {
                            "id": "ghost",
                            "desiredStatus": "RUNNING",
                            "name": "nadoc-6hb-abc",
                        }
                    )
                ]

        c = C()
        assert _run(sup.reap_orphan_pods(c))[0] == ["ghost"]
        assert c.terminated == ["ghost"]

    def test_leaves_pods_the_user_started_by_hand_alone(self):
        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod

                return [
                    parse_pod(
                        {
                            "id": "mine",
                            "desiredStatus": "RUNNING",
                            "name": "my-jupyter-box",
                        }
                    )
                ]

        c = C()
        assert _run(sup.reap_orphan_pods(c))[0] == []
        assert c.terminated == []

    def test_reaps_an_exited_pod(self):
        """REGRESSION: an EXITED pod is a STOPPED container still on the account, still
        billing for its disk — not a destroyed one. The reaper used to skip it as
        'already dead', which is how pod 2tnfzwx9j3mvhm survived every reap."""

        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod

                return [
                    parse_pod(
                        {
                            "id": "zombie",
                            "desiredStatus": "EXITED",
                            "name": "nadoc-6hb-abc",
                        }
                    )
                ]

        c = C()
        assert _run(sup.reap_orphan_pods(c))[0] == ["zombie"]
        assert c.terminated == ["zombie"]

    def test_does_not_reap_an_already_destroyed_pod(self):
        """TERMINATED is gone: re-terminating is a pointless API call."""

        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod

                return [
                    parse_pod(
                        {
                            "id": "gone",
                            "desiredStatus": "TERMINATED",
                            "name": "nadoc-6hb-abc",
                        }
                    )
                ]

        c = C()
        assert _run(sup.reap_orphan_pods(c))[0] == []
        assert c.terminated == []

    def test_does_not_reap_a_pod_it_is_currently_tracking(self):
        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod

                return [
                    parse_pod(
                        {
                            "id": "live",
                            "desiredStatus": "RUNNING",
                            "name": "nadoc-6hb-abc",
                        }
                    )
                ]

        sup._PODS["j3"] = "live"  # noqa: SLF001
        try:
            c = C()
            assert _run(sup.reap_orphan_pods(c))[0] == []
            assert c.terminated == []
        finally:
            sup._PODS.pop("j3", None)  # noqa: SLF001


class TestAutoResumeOnSpotReclaim:
    """A spot pod WILL be taken away mid-run — that is why it costs half price.

    What makes that survivable: every completed step's .coor lives on the NETWORK
    VOLUME, which outlives the pod, so relaunching skips them. A reclaim is therefore a
    RESUME, not a failure. Without the loop below a long run stops dead at the first
    reclaim and waits for a human — i.e. an overnight run does nothing all night.
    """

    def _job(self, tmp_path):
        return _job_with_package(tmp_path)

    def _drive(self, tmp_path, monkeypatch, outcomes):
        """Run start_job with run_job_on_pod stubbed to yield `outcomes` in order."""
        calls = {"n": 0}
        job = self._job(tmp_path)

        async def fake_run(j, ws, **kw):
            i = calls["n"]
            calls["n"] += 1
            status = outcomes[min(i, len(outcomes) - 1)]
            j.status = status
            j.resumable = status == MdStatus.paused
            return status

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)
        monkeypatch.setattr(sup, "RESUME_BACKOFF_S", 0)

        async def go():
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
            task = sup._RUNNING[job.job_id]  # noqa: SLF001
            await task

        asyncio.run(go())
        return job, calls["n"]

    def test_a_reclaim_auto_resumes_and_the_job_completes(self, tmp_path, monkeypatch):
        job, n = self._drive(
            tmp_path,
            monkeypatch,
            [MdStatus.paused, MdStatus.paused, MdStatus.completed],
        )
        assert n == 3, "must relaunch on each reclaim, not stop at the first"
        assert job.status == MdStatus.completed
        assert job.resubmit_count == 2

    def test_a_completed_run_is_not_relaunched(self, tmp_path, monkeypatch):
        _job, n = self._drive(tmp_path, monkeypatch, [MdStatus.completed])
        assert n == 1

    def test_a_real_failure_is_not_retried_forever(self, tmp_path, monkeypatch):
        """A NAMD failure is NOT a reclaim. Relaunching it would burn pods on a job that
        cannot succeed."""
        job, n = self._drive(tmp_path, monkeypatch, [MdStatus.failed])
        assert n == 1
        assert job.status == MdStatus.failed

    def test_auto_resume_is_capped(self, tmp_path, monkeypatch):
        """An interrupted SEGMENT restarts from its top (no .coor until it finishes), so
        a pathologically unlucky run could thrash. Cap it and tell the user to use an
        on-demand pod."""
        monkeypatch.setattr(sup, "MAX_AUTO_RESUMES", 3)
        job, n = self._drive(tmp_path, monkeypatch, [MdStatus.paused])
        assert n == 4, "3 resumes + the original"
        assert job.status == MdStatus.paused
        assert "on-demand" in (job.error or "")

    def test_a_user_stop_halts_the_resume_loop(self, tmp_path, monkeypatch):
        """Otherwise Stop would be fought by the auto-resume, and the pod would come
        straight back — billing."""
        calls = {"n": 0}
        job = self._job(tmp_path)

        async def fake_run(j, ws, **kw):
            calls["n"] += 1
            j.status = MdStatus.paused
            j.resumable = True
            j.user_stopped = True  # as if Stop was pressed mid-run
            return MdStatus.paused

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)
        monkeypatch.setattr(sup, "RESUME_BACKOFF_S", 0)

        async def go():
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert calls["n"] == 1, "a user stop must not be auto-resumed"


class TestBudgetThreading:
    """The wizard's spend cap must actually reach the pod.

    Before this, ``run_job_on_pod`` was always called with the module constant
    ``DEFAULT_BUDGET_USD`` — the user could neither see the cap nor change it. The cap is what
    derives the pod's kill-switch wall-clock, so a cap that does not arrive is a run with a
    budget the user never authorised.
    """

    def _capture(self, tmp_path, monkeypatch, job):
        seen = {}

        async def fake_run(j, ws, **kw):
            seen.update(kw)
            j.status = MdStatus.completed
            return MdStatus.completed

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)

        async def go():
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        return seen

    def test_the_jobs_budget_reaches_the_pod(self, tmp_path, monkeypatch):
        job = _job_with_package(tmp_path)
        job.runpod_budget_usd = 5.0
        assert self._capture(tmp_path, monkeypatch, job)["budget_usd"] == 5.0

    def test_no_budget_falls_back_to_the_default(self, tmp_path, monkeypatch):
        job = _job_with_package(tmp_path)
        assert (
            self._capture(tmp_path, monkeypatch, job)["budget_usd"]
            == sup.DEFAULT_BUDGET_USD
        )

    def test_zero_budget_is_rejected_not_promoted_to_default(self, tmp_path, monkeypatch):
        """A falsey-dollar cap must never silently become the $15 default."""
        job = _job_with_package(tmp_path)
        job.runpod_budget_usd = 0.0
        with pytest.raises(ValueError, match="greater than"):
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")

    def test_budget_lifetime_does_not_authorize_another_full_cap(
        self, tmp_path, monkeypatch
    ):
        """Hitting the cap is a spend boundary, not a spot reclaim.

        The old loop immediately rented another pod with a fresh full cap, making the
        wizard's advertised cap multiply by up to MAX_AUTO_RESUMES.
        """
        calls = {"n": 0}
        job = _job_with_package(tmp_path)

        async def fake_run(j, ws, **kw):
            calls["n"] += 1
            j.status = MdStatus.paused
            j.resumable = True
            j.error = "Pod hit its maximum lifetime; resume to continue."
            return MdStatus.paused

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)

        async def go():
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert calls["n"] == 1
        assert job.status == MdStatus.paused
        assert job.resumable is True


class TestReloadHandoffKeepsTheDurableClaim:
    def test_cancelled_supervisor_does_not_mark_handed_off_job_stopped(
        self, tmp_path, monkeypatch
    ):
        """The replacement process can adopt only records still claiming a live pod."""
        from backend.core import runpod_api

        job = _job_with_package(tmp_path)
        job.execution_target = "runpod"
        job.status = MdStatus.running
        job.runpod_pod_id = "pod-survives-reload"
        entered = asyncio.Event()

        async def fake_run(j, ws, **kw):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)

        async def go():
            runpod_api.set_handoff(True)
            try:
                sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
                task = sup._RUNNING[job.job_id]  # noqa: SLF001
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                runpod_api.set_handoff(False)

        asyncio.run(go())
        saved = type(job).load(job.job_id, tmp_path)
        assert saved.status == MdStatus.running
        assert saved.runpod_pod_id == "pod-survives-reload"
        assert saved.user_stopped is False

    def test_the_job_wins_over_the_call_default(self, tmp_path, monkeypatch):
        """A cap recorded on the job was a decision about THIS run; a caller default is not."""
        job = _job_with_package(tmp_path)
        job.runpod_budget_usd = 3.0
        seen = {}

        async def fake_run(j, ws, **kw):
            seen.update(kw)
            j.status = MdStatus.completed
            return MdStatus.completed

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)

        async def go():
            sup.start_job(
                job,
                tmp_path,
                client=FakeClient(),
                network_volume_id="v",
                budget_usd=99.0,
            )
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert seen["budget_usd"] == 3.0


class TestTheWizardsChoicesSurvive:
    """The three answers the wizard collects before the pod exists must reach launch.

    ``runpod_gpu_key`` in particular was already being SENT by the frontend and silently
    dropped by pydantic — the user picked a card and the server never heard about it.
    """

    def test_old_job_json_without_the_new_keys_still_loads(self, tmp_path):
        from backend.core.md_job import MdJob

        job = _job_with_package(tmp_path)
        job.save(tmp_path)
        path = job.job_dir(tmp_path) / "job.json"
        raw = json.loads(path.read_text())
        for k in ("runpod_gpu_key", "runpod_budget_usd", "runpod_volume_id"):
            raw.pop(k, None)
        path.write_text(json.dumps(raw))

        back = MdJob.load(job.job_id, tmp_path)
        assert back.runpod_gpu_key is None
        assert back.runpod_budget_usd is None
        assert back.runpod_volume_id is None

    def test_the_choices_round_trip(self, tmp_path):
        from backend.core.md_job import MdJob

        job = _job_with_package(tmp_path)
        job.runpod_gpu_key = "NVIDIA RTX 6000 Ada Generation"
        job.runpod_budget_usd = 7.5
        job.runpod_volume_id = "77pnhye88p"
        job.save(tmp_path)

        back = MdJob.load(job.job_id, tmp_path)
        assert back.runpod_gpu_key == "NVIDIA RTX 6000 Ada Generation"
        assert back.runpod_budget_usd == 7.5
        assert back.runpod_volume_id == "77pnhye88p"


class TestRunpodGpuResidentDefault:
    """The rented-card default must not reuse the local 3080 Ti atom crossover."""

    def test_relaxation_defaults_gpu_resident_on(self):
        from backend.api import routes_md

        body = routes_md.CreateJobRequest(execution_target="runpod")
        resolved = routes_md._apply_runpod_gpu_resident_default(body)  # noqa: SLF001
        assert resolved.gpu_resident == "on"

    def test_production_defaults_gpu_resident_on(self):
        from backend.api import routes_md

        body = routes_md.ProductionRunRequest(
            execution_target="runpod", length_ns=1.0
        )
        resolved = routes_md._apply_runpod_gpu_resident_default(body)  # noqa: SLF001
        assert resolved.gpu_resident == "on"

    @pytest.mark.parametrize("choice", ["auto", "off", "on"])
    def test_explicit_advanced_choice_wins(self, choice):
        from backend.api import routes_md

        body = routes_md.CreateJobRequest(
            execution_target="runpod", gpu_resident=choice
        )
        resolved = routes_md._apply_runpod_gpu_resident_default(body)  # noqa: SLF001
        assert resolved.gpu_resident == choice

    def test_local_default_remains_auto(self):
        from backend.api import routes_md

        body = routes_md.CreateJobRequest(execution_target="local")
        resolved = routes_md._apply_runpod_gpu_resident_default(body)  # noqa: SLF001
        assert resolved.gpu_resident is None


class TestAClaimedPodIsNotAnOrphan:
    """The bug this closes cost a live 200 ns run.

    Reaping by "absent from the in-memory registry" is wrong in exactly the case the
    registry cannot speak for: a fresh process. After a dev-server reload it is empty, so
    the first reconnect destroyed the very run the reload was supposed to preserve. The
    job RECORD is the durable claim — that is why the pod id is persisted the instant a
    pod exists.
    """

    def _pod(self, pid="pod-live", name="nadoc-2hb-abc"):
        from backend.core.runpod_api import parse_pod

        return parse_pod({"id": pid, "desiredStatus": "RUNNING", "name": name})

    def _client(self, pods):
        class C(FakeClient):
            async def list_pods(self):
                return pods

        return C()

    def _job_on_pod(self, tmp_path, pod_id="pod-live", status=MdStatus.running):
        job = _job_with_package(tmp_path)
        job.execution_target = "runpod"
        job.runpod_pod_id = pod_id
        job.status = status
        job.save(tmp_path)
        return job

    def test_a_running_jobs_pod_is_adopted_not_killed(self, tmp_path):
        job = self._job_on_pod(tmp_path)
        c = self._client([self._pod()])
        killed, adoptable = _run(sup.reap_orphan_pods(c, tmp_path))
        assert killed == [], "a pod a running job claims must NOT be terminated"
        assert c.terminated == []
        assert [j.job_id for j in adoptable] == [job.job_id]

    def test_a_pod_no_job_claims_is_still_reaped(self, tmp_path):
        """The wallet guarantee has to survive the fix: a genuine orphan still dies."""
        self._job_on_pod(tmp_path, pod_id="some-other-pod")
        c = self._client([self._pod(pid="ghost")])
        killed, adoptable = _run(sup.reap_orphan_pods(c, tmp_path))
        assert killed == ["ghost"]
        assert adoptable == []

    def test_a_finished_jobs_pod_is_reaped(self, tmp_path):
        """A terminal job has no business holding a pod — its record is a stale handle,
        not a claim."""
        self._job_on_pod(tmp_path, status=MdStatus.completed)
        c = self._client([self._pod()])
        killed, adoptable = _run(sup.reap_orphan_pods(c, tmp_path))
        assert killed == ["pod-live"]
        assert adoptable == []

    def test_without_a_workspace_it_behaves_as_before(self, tmp_path):
        """No workspace => no claims knowable => reap. Fail toward not leaking pods."""
        self._job_on_pod(tmp_path)
        c = self._client([self._pod()])
        killed, _ = _run(sup.reap_orphan_pods(c))
        assert killed == ["pod-live"]


class TestReattach:
    def test_reattach_registers_the_job_and_its_pod(self, tmp_path, monkeypatch):
        """A re-attached run must land in the SAME registry as a launched one, or Stop and
        the shutdown teardown would both walk straight past it."""
        job = _job_with_package(tmp_path)
        job.execution_target = "runpod"
        job.runpod_pod_id = "pod-live"
        seen = {}

        async def fake_adopt(j, ws, **kw):
            seen["job"] = j.job_id
            kw["on_pod"]("pod-live")
            seen["registered"] = sup.pod_id_for(j.job_id)
            seen["running"] = sup.is_running(j.job_id)
            return MdStatus.completed

        monkeypatch.setattr(sup, "reattach_job_on_pod", fake_adopt)

        async def go():
            sup.reattach_job(job, tmp_path, client=FakeClient())
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert seen["job"] == job.job_id
        assert seen["registered"] == "pod-live"
        assert seen["running"] is True

    def test_a_failed_adopt_releases_the_pod_claim(self, tmp_path, monkeypatch):
        """Otherwise the job claims a pod forever: every later reconnect would try to adopt
        it again and never reap it — a leak dressed up as a rescue."""
        job = _job_with_package(tmp_path)
        job.execution_target = "runpod"
        job.runpod_pod_id = "pod-gone"
        job.save(tmp_path)

        async def boom(j, ws, **kw):
            raise RuntimeError("pod is already destroyed")

        monkeypatch.setattr(sup, "reattach_job_on_pod", boom)

        async def go():
            sup.reattach_job(job, tmp_path, client=FakeClient())
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert job.runpod_pod_id is None
        assert job.status == MdStatus.paused
        assert job.resumable is True
        assert "resume" in (job.error or "").lower()

    def test_does_not_double_attach(self, tmp_path, monkeypatch):
        job = _job_with_package(tmp_path)
        job.runpod_pod_id = "pod-live"
        calls = {"n": 0}

        async def fake_adopt(j, ws, **kw):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return MdStatus.completed

        monkeypatch.setattr(sup, "reattach_job_on_pod", fake_adopt)

        async def go():
            sup.reattach_job(job, tmp_path, client=FakeClient())
            sup.reattach_job(job, tmp_path, client=FakeClient())  # must no-op
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert calls["n"] == 1

    def test_dead_reattached_chain_automatically_restarts_on_a_fresh_pod(
        self, tmp_path, monkeypatch
    ):
        """A reload can adopt the pod after its detached chain has died.  Pausing there
        still strands an overnight run; the network-volume checkpoint must be relaunched."""
        job = _job_with_package(tmp_path)
        job.execution_target = "runpod"
        job.runpod_pod_id = "pod-with-dead-chain"
        job.runpod_volume_id = "volume1"
        restarted = []

        async def interrupted(j, ws, **kw):
            j.status = MdStatus.paused
            j.resumable = True
            j.error = "Pod stopped mid-run; resume to continue from the checkpoint."
            return MdStatus.paused

        def capture_start(j, ws, **kw):
            restarted.append((j.job_id, kw["network_volume_id"]))

        monkeypatch.setattr(sup, "reattach_job_on_pod", interrupted)
        monkeypatch.setattr(sup, "start_job", capture_start)

        async def go():
            sup.reattach_job(job, tmp_path, client=FakeClient())
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert restarted == [(job.job_id, "volume1")]

    def test_budget_exhaustion_after_reattach_is_not_automatically_restarted(
        self, tmp_path, monkeypatch
    ):
        job = _job_with_package(tmp_path)
        job.runpod_pod_id = "pod-at-budget"
        job.runpod_volume_id = "volume1"
        restarted = []

        async def exhausted(j, ws, **kw):
            j.status = MdStatus.paused
            j.resumable = True
            j.error = "Pod hit its maximum lifetime; resume to continue."
            return MdStatus.paused

        monkeypatch.setattr(sup, "reattach_job_on_pod", exhausted)
        monkeypatch.setattr(sup, "start_job", lambda *a, **k: restarted.append(True))

        async def go():
            sup.reattach_job(job, tmp_path, client=FakeClient())
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert restarted == []
