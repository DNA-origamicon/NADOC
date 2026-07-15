#!/usr/bin/env python3
"""Verified-state confirmation receipts for the three money-moving RunPod steps.

The whole point of this module is the rule the user set: **every step that spends or stops
money — pod SETUP, job LAUNCH, pod TERMINATION — must emit a confirmation code, and a step
that finishes WITHOUT one must automatically trigger a review** (i.e. land in a queue that
says "a safeguard is missing here").

A confirmation code is NOT an "the API call returned 200" ack. The runbook's failure
catalogue is full of calls that returned success while the thing they claimed did not happen
(a `terminate` that left a pod billing; a launch that died at step 0 on the wrong arch). So a
code here is a **verified-state receipt**: it is only minted *after this module independently
re-queries RunPod / the pod and proves the post-condition*. No proof -> no code -> the
`guarded_step` context manager writes a review-queue entry and raises `NoConfirmation`.

Structural invariant (this is the safeguard, not a convention):

    async with guarded_step("terminate", pod_id, log) as step:
        await client.terminate_pod(pod_id)
        step.receipt(await confirm_pod_terminated(client, pod_id))   # must register a receipt

If the body exits without calling `step.receipt(...)`, `guarded_step` treats the step as
UNVERIFIED: it appends to `review_queue.jsonl` and raises. You cannot "succeed" silently.

Design for testability: the `confirm_*` verifiers take a duck-typed client/conn, so the
tests drive them with fakes and never touch the network.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


class NoConfirmation(RuntimeError):
    """A money-moving step finished without a verified-state receipt.

    Catching this is the trigger to STOP and either fix the verification or add a
    safeguard — never to retry the spend blindly.
    """


@dataclass
class Receipt:
    op: str                       # "setup" | "launch" | "terminate" (or a staging op)
    target: str                   # pod id, or region/volume for staging steps
    verified: bool                # did the independent re-query prove the post-condition?
    evidence: dict[str, Any]      # the raw facts the verdict was read from
    ts: float
    code: str = ""

    def mint(self) -> "Receipt":
        """Derive the short confirmation code from the evidence. Only verified receipts
        get a code — an unverified receipt keeps code="" so its absence is the signal."""
        if self.verified:
            blob = json.dumps(
                {"op": self.op, "target": self.target, "ev": self.evidence,
                 "ts": round(self.ts, 3)},
                sort_keys=True,
            )
            digest = hashlib.sha256(blob.encode()).hexdigest()[:8]
            self.code = f"{self.op.upper()[:5]}-{self.target[:6]}-{digest}"
        return self


class ConfirmationLog:
    """Append-only receipt + review-queue store.

    Two files sit next to each other under `dir_`:
      confirmations.jsonl  — every minted (verified) receipt, in order.
      review_queue.jsonl   — every step that could NOT be confirmed. A non-empty queue is a
                              standing "a safeguard is owed here" list; the campaign refuses
                              to keep spending while it is non-empty (see require_clean()).
    """

    def __init__(self, dir_: Path):
        self.dir = Path(dir_)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.confirmations = self.dir / "confirmations.jsonl"
        self.review_queue = self.dir / "review_queue.jsonl"

    def record(self, receipt: Receipt) -> Receipt:
        receipt.mint()
        with self.confirmations.open("a") as fh:
            fh.write(json.dumps(asdict(receipt)) + "\n")
        if not receipt.verified or not receipt.code:
            self.flag(receipt.op, receipt.target,
                      reason="receipt registered but NOT verified",
                      evidence=receipt.evidence)
        return receipt

    def flag(self, op: str, target: str, reason: str,
             evidence: Optional[dict] = None) -> None:
        entry = {"op": op, "target": target, "reason": reason,
                 "evidence": evidence or {}, "ts": time.time()}
        with self.review_queue.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def open_reviews(self) -> list[dict]:
        if not self.review_queue.exists():
            return []
        return [json.loads(ln) for ln in self.review_queue.read_text().splitlines() if ln.strip()]

    def require_clean(self) -> None:
        """Refuse to proceed while any step is owed a safeguard."""
        pending = self.open_reviews()
        if pending:
            raise NoConfirmation(
                f"{len(pending)} step(s) in the review queue await a safeguard: "
                + "; ".join(f"{p['op']}:{p['target']} ({p['reason']})" for p in pending[-5:])
            )


class _Step:
    def __init__(self, op: str, target: str, log: ConfirmationLog):
        self.op, self.target, self.log = op, target, log
        self._receipt: Optional[Receipt] = None

    def receipt(self, receipt: Receipt) -> Receipt:
        self._receipt = self.log.record(receipt)
        return self._receipt

    @property
    def confirmed(self) -> bool:
        return self._receipt is not None and self._receipt.verified and bool(self._receipt.code)


class guarded_step:
    """Async context manager enforcing 'no confirmation -> review + raise'."""

    def __init__(self, op: str, target: str, log: ConfirmationLog):
        self.step = _Step(op, target, log)

    async def __aenter__(self) -> _Step:
        return self.step

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.step.log.flag(self.step.op, self.step.target,
                               reason=f"step raised: {exc_type.__name__}: {str(exc)[:160]}")
            return False  # re-raise
        if not self.step.confirmed:
            self.step.log.flag(self.step.op, self.step.target,
                               reason="step completed WITHOUT a verified confirmation code")
            raise NoConfirmation(
                f"{self.step.op} on {self.step.target} finished without a confirmation "
                f"code — SAFEGUARD REQUIRED before spending further")
        return False


# ── the three verifiers ─────────────────────────────────────────────────────────────────
# Each independently re-queries state AFTER the action and reads the verdict from raw facts.

async def confirm_pod_up(client, pod_id: str, *, sleep=asyncio.sleep,
                         retries: int = 3, delay: float = 4.0) -> Receipt:
    """Prove the pod is RUNNING and reachable (has a public IP + SSH port) — not merely
    that create_pod returned an id. A pod reports RUNNING before its endpoint exists, and a
    host too old for the image bills while never exposing SSH."""
    last: dict[str, Any] = {}
    for attempt in range(retries):
        pod = await client.get_pod(pod_id)
        ip = pod.raw.get("publicIp") or pod.raw.get("ip")
        ports = pod.raw.get("portMappings") or {}
        ssh_port = ports.get("22") if isinstance(ports, dict) else None
        last = {"desired_status": pod.desired_status, "public_ip": ip,
                "ssh_port": ssh_port, "cost_per_hr": pod.cost_per_hr, "attempt": attempt}
        ok = pod.desired_status == "RUNNING" and bool(ip) and bool(ssh_port)
        if ok:
            return Receipt("setup", pod_id, True, last, time.time())
        if pod.is_terminated:
            break
        await sleep(delay)
    return Receipt("setup", pod_id, False, last, time.time())


async def confirm_job_launched(conn, workdir: str, log_name: str, *,
                               sleep=asyncio.sleep, settle: float = 8.0) -> Receipt:
    """Prove NAMD is actually RUNNING and producing output — not that a launch command
    returned. Reads two facts: a live process, and a log that is GROWING (or already carries
    a NAMD progress marker). Also positively catches the silent wrong-arch death."""
    async def sh(cmd: str) -> str:
        r = await conn.run(cmd)
        return (r.stdout or "").strip()

    pids = await sh("pgrep -il namd || true")               # NAMD renames to "NAMD masterPe"
    size0 = await sh(f"stat -c %s {workdir}/{log_name} 2>/dev/null || echo 0")
    await sleep(settle)
    size1 = await sh(f"stat -c %s {workdir}/{log_name} 2>/dev/null || echo 0")
    tail = await sh(f"tail -c 4000 {workdir}/{log_name} 2>/dev/null || true")

    wrong_arch = "no kernel image is available" in tail
    fatal = "FATAL ERROR" in tail
    has_marker = ("Benchmark time:" in tail) or ("ENERGY:" in tail) or ("TIMING:" in tail)
    growing = size1.isdigit() and size0.isdigit() and int(size1) > int(size0)
    alive = bool(pids)
    verified = alive and (growing or has_marker) and not wrong_arch and not fatal
    # Safeguard: when a launch can't be verified, capture the offending lines INTO the receipt
    # so the review queue is self-diagnosing — the pod is torn down seconds later and the log
    # goes with it, so "why did it fail" must be preserved here or it is lost. (Added after an
    # H100 launch fatalled on a duplicate periodic-cell definition and left no trace but a
    # boolean.)
    err_excerpt = ""
    if not verified:
        hits = [ln for ln in tail.splitlines()
                if any(k in ln for k in ("FATAL", "ERROR", "kernel image", "Abort", "terminate"))]
        err_excerpt = " | ".join(hits)[-400:]
    ev = {"pids": pids[:120], "log_bytes_t0": size0, "log_bytes_t1": size1,
          "growing": growing, "has_marker": has_marker,
          "wrong_arch": wrong_arch, "fatal": fatal, "error": err_excerpt}
    return Receipt("launch", workdir, verified, ev, time.time())


async def confirm_pod_terminated(client, pod_id: str, *, sleep=asyncio.sleep,
                                 retries: int = 5, delay: float = 4.0) -> Receipt:
    """Prove the pod is GONE from the account — not that terminate_pod returned. Termination
    is async, so poll: destroyed status, or absent from list_pods entirely."""
    last: dict[str, Any] = {}
    for attempt in range(retries):
        pods = await client.list_pods()
        match = next((p for p in pods if p.id == pod_id), None)
        if match is None:
            return Receipt("terminate", pod_id, True,
                           {"found_in_list": False, "attempt": attempt}, time.time())
        last = {"found_in_list": True, "desired_status": match.desired_status,
                "is_destroyed": match.is_destroyed, "attempt": attempt}
        if match.is_destroyed:
            return Receipt("terminate", pod_id, True, last, time.time())
        await sleep(delay)
    return Receipt("terminate", pod_id, False, last, time.time())
