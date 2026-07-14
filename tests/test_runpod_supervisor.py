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
        assert psf.stat().st_size > 100_000, "fixture must have a realistically big header"
        assert psf.read_text()[:4096].find("!NATOM") == -1, "must NOT be in the first 4 KB"
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
                return [parse_pod({"id": "ghost", "desiredStatus": "RUNNING",
                                   "name": "nadoc-6hb-abc"})]

        c = C()
        assert _run(sup.reap_orphan_pods(c)) == ["ghost"]
        assert c.terminated == ["ghost"]

    def test_leaves_pods_the_user_started_by_hand_alone(self):
        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod
                return [parse_pod({"id": "mine", "desiredStatus": "RUNNING",
                                   "name": "my-jupyter-box"})]

        c = C()
        assert _run(sup.reap_orphan_pods(c)) == []
        assert c.terminated == []

    def test_does_not_reap_a_pod_it_is_currently_tracking(self):
        class C(FakeClient):
            async def list_pods(self):
                from backend.core.runpod_api import parse_pod
                return [parse_pod({"id": "live", "desiredStatus": "RUNNING",
                                   "name": "nadoc-6hb-abc"})]

        sup._PODS["j3"] = "live"  # noqa: SLF001
        try:
            c = C()
            assert _run(sup.reap_orphan_pods(c)) == []
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
            tmp_path, monkeypatch,
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
            j.user_stopped = True          # as if Stop was pressed mid-run
            return MdStatus.paused

        monkeypatch.setattr(sup, "run_job_on_pod", fake_run)
        monkeypatch.setattr(sup, "RESUME_BACKOFF_S", 0)

        async def go():
            sup.start_job(job, tmp_path, client=FakeClient(), network_volume_id="v")
            await sup._RUNNING[job.job_id]  # noqa: SLF001

        asyncio.run(go())
        assert calls["n"] == 1, "a user stop must not be auto-resumed"
