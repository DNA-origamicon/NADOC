#!/usr/bin/env python3
"""Self-contained tests for runpod_confirm — run with plain `python` (no pytest, no test
guard: this is experiments-only and touches no backend code).

    python experiments/exp43_runpod_bench/test_runpod_confirm.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.exp43_runpod_bench.runpod_confirm import (  # noqa: E402
    ConfirmationLog, NoConfirmation, Receipt, confirm_job_launched,
    confirm_pod_terminated, confirm_pod_up, guarded_step,
)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


async def _noslip(*a, **k):
    return None


# ── fakes ────────────────────────────────────────────────────────────────────────────────
def pod(pid, status="RUNNING", ip="1.2.3.4", ssh=12345, cost=2.5, destroyed=False):
    raw = {"publicIp": ip, "portMappings": ({"22": ssh} if ssh else {})}
    return SimpleNamespace(
        id=pid, desired_status=status, cost_per_hr=cost, raw=raw,
        is_terminated=(status in {"TERMINATED", "EXITED"}),
        is_destroyed=destroyed or status in {"TERMINATED", "EXITED"})


class FakeClient:
    def __init__(self, get_seq=None, list_seq=None):
        self._get = list(get_seq or [])
        self._list = list(list_seq or [])

    async def get_pod(self, pid):
        return self._get.pop(0) if len(self._get) > 1 else self._get[0]

    async def list_pods(self):
        return self._list.pop(0) if len(self._list) > 1 else (self._list[0] if self._list else [])


class FakeConn:
    """Answers shell probes from a dict of substring -> output."""
    def __init__(self, table, size_seq=None):
        self.table = table
        self.size_seq = list(size_seq or [])

    async def run(self, cmd, timeout=None):
        out = ""
        if "stat -c %s" in cmd and self.size_seq:
            out = self.size_seq.pop(0)
        else:
            for key, val in self.table.items():
                if key in cmd:
                    out = val
                    break
        return SimpleNamespace(stdout=out, stderr="", rc=0)


# ── tests ──────────────────────────────────────────────────────────────────────────────
def test_receipt_code_only_when_verified():
    r = Receipt("setup", "abc123", True, {"x": 1}, 100.0).mint()
    check("verified receipt mints a code", bool(r.code) and r.code.startswith("SETUP-"))
    u = Receipt("setup", "abc123", False, {"x": 1}, 100.0).mint()
    check("unverified receipt has NO code", u.code == "")


def test_log_flags_unverified():
    with tempfile.TemporaryDirectory() as d:
        log = ConfirmationLog(Path(d))
        log.record(Receipt("terminate", "p1", False, {}, 1.0))
        check("unverified receipt lands in review queue", len(log.open_reviews()) == 1)
        log.record(Receipt("setup", "p2", True, {"ok": 1}, 1.0))
        check("verified receipt does NOT add a review", len(log.open_reviews()) == 1)


async def test_guarded_step_requires_receipt():
    with tempfile.TemporaryDirectory() as d:
        log = ConfirmationLog(Path(d))
        raised = False
        try:
            async with guarded_step("terminate", "p9", log) as step:
                pass  # forgot to register a receipt
        except NoConfirmation:
            raised = True
        check("missing receipt -> NoConfirmation", raised)
        check("missing receipt -> review queue entry", len(log.open_reviews()) == 1)


async def test_guarded_step_happy_path():
    with tempfile.TemporaryDirectory() as d:
        log = ConfirmationLog(Path(d))
        async with guarded_step("setup", "p1", log) as step:
            step.receipt(Receipt("setup", "p1", True, {"ok": 1}, 1.0))
        check("confirmed step: no review", len(log.open_reviews()) == 0)
        check("confirmed step: one confirmation logged",
              len(log.confirmations.read_text().splitlines()) == 1)


async def test_guarded_step_reflags_exception():
    with tempfile.TemporaryDirectory() as d:
        log = ConfirmationLog(Path(d))
        try:
            async with guarded_step("launch", "p1", log):
                raise ValueError("boom")
        except ValueError:
            pass
        check("body exception -> review queue", len(log.open_reviews()) == 1)


async def test_require_clean():
    with tempfile.TemporaryDirectory() as d:
        log = ConfirmationLog(Path(d))
        log.require_clean()  # empty: fine
        log.flag("terminate", "p1", "unverified")
        raised = False
        try:
            log.require_clean()
        except NoConfirmation:
            raised = True
        check("require_clean refuses on non-empty queue", raised)


async def test_confirm_pod_up():
    r = await confirm_pod_up(FakeClient(get_seq=[pod("p1")]), "p1", sleep=_noslip)
    check("pod up (RUNNING + ip + ssh) verifies", r.verified and r.mint().code)
    r2 = await confirm_pod_up(
        FakeClient(get_seq=[pod("p2", ip=None, ssh=None)]), "p2", sleep=_noslip, retries=2)
    check("pod RUNNING but no endpoint -> unverified", not r2.verified)
    r3 = await confirm_pod_up(
        FakeClient(get_seq=[pod("p3", status="TERMINATED")]), "p3", sleep=_noslip, retries=3)
    check("pod terminated before ssh -> unverified", not r3.verified)


async def test_confirm_terminated():
    r = await confirm_pod_terminated(FakeClient(list_seq=[[]]), "gone", sleep=_noslip)
    check("absent from list -> terminated verified", r.verified)
    r2 = await confirm_pod_terminated(
        FakeClient(list_seq=[[pod("p1", status="TERMINATED", destroyed=True)]]),
        "p1", sleep=_noslip)
    check("present but destroyed -> verified", r2.verified)
    r3 = await confirm_pod_terminated(
        FakeClient(list_seq=[[pod("p1")]]), "p1", sleep=_noslip, retries=2)
    check("still RUNNING -> NOT terminated", not r3.verified)


async def test_confirm_job_launched():
    good = FakeConn({"pgrep": "8123 NAMD masterPe", "tail": "Benchmark time: 0.02 s/step"},
                    size_seq=["100", "5000"])
    r = await confirm_job_launched(good, "/w", "bench.log", sleep=_noslip)
    check("alive + growing + marker -> verified", r.verified)

    arch = FakeConn({"pgrep": "", "tail": "no kernel image is available for execution"},
                    size_seq=["100", "100"])
    r2 = await confirm_job_launched(arch, "/w", "bench.log", sleep=_noslip)
    check("wrong-arch death -> unverified", not r2.verified and r2.evidence["wrong_arch"])

    dead = FakeConn({"pgrep": "", "tail": "starting"}, size_seq=["100", "100"])
    r3 = await confirm_job_launched(dead, "/w", "bench.log", sleep=_noslip)
    check("no process + flat log -> unverified", not r3.verified)


async def main():
    test_receipt_code_only_when_verified()
    test_log_flags_unverified()
    await test_guarded_step_requires_receipt()
    await test_guarded_step_happy_path()
    await test_guarded_step_reflags_exception()
    await test_require_clean()
    await test_confirm_pod_up()
    await test_confirm_terminated()
    await test_confirm_job_launched()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
