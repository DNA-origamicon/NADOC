"""Cumulative pod-spend ledger — the thing `lifetime_for_budget` cannot do.

The in-code kill-switch is a **per-POD** cap: it derives one pod's wall-clock from a
dollar budget and kills NAMD when it expires. It has no memory. Two pods (a relaxation
and a production child), or one pod plus a benchmark, each get the FULL budget — so a
"$15 cap" silently authorises $15 x N.

This file is that memory. Every pod this session creates is appended here with its live
rate, and `spent()` sums the whole session. Budget decisions read from it, never from a
single pod's clock.

It lives in the ARCHIVE dir beside the job, not the system disk, so it survives a
reboot and can be read tomorrow to answer "what did that night actually cost".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# Raised 15 -> 120 for the 24hb campaign (2026-07-14, user-approved).
#
# The $15 was sized for the 3x6x400 run. The 24hb 0xT run alone is ~$70 (a ~$5 Tier-A
# ladder + ~$65 for 50 ns of production on a $0.74/hr PRO 4500), on top of the $9.91 this
# ledger had already accumulated. At $15 the cap did not merely warn — it would have
# SILENTLY BROKEN the run in two places, both of which read the ledger and trust it:
#
#   * launch_production.py sizes production from ledger.remaining(), which was $3.59 —
#     it would have truncated 50 ns to a few percent of its length, and reported success.
#   * supervise.py destroys the pod when spent > HARD_CAP_USD — so once the ladder pushed
#     cumulative spend past $15, ANY healthy pod would have been reaped the moment a
#     supervisor attached to it.
#
# This is LESSONS L5 from the other side: a ledger that is *trusted* is dangerous when it
# is *stale*, not only when it under-reports. $120 covers the approved run end to end and
# still stops a runaway far short of the account balance. Re-check this number before
# adding the 1xT/2xT variants — do not let it drift into "effectively no cap".
HARD_CAP_USD = 120.0

# Leave this much unspent. Reserve, not slack: it absorbs the minutes a pod bills while
# it is being provisioned, staged and torn down — time that does no science but is
# charged all the same.
HEADROOM_USD = 1.50


class SpendLedger:
    """One job's pods — but ``spent()`` sums EVERY job's, which is the point.

    The $15 is a cap on the SESSION, not on a job. The first attempt at the 3x6x400
    ladder burned $0.27 across two pods before being killed and re-prepped under a new
    job_id; a per-job ledger would have handed the replacement a fresh, full $15. So each
    job writes its own file (no cross-process coordination, no lock), and the total is a
    sum over all of them.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]")

    def _load(self) -> list[dict]:
        return self._load_file(self.path)

    @staticmethod
    def _load_file(p: Path) -> list[dict]:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001 — a corrupt ledger must not authorise spending
            return []

    def _all_rows(self) -> list[dict]:
        """Every pod of every job, ONE row per pod, collapsed over its whole life.

        A pod bills continuously from creation to destruction, no matter how many
        processes happened to be watching it. So the same pod_id can legitimately appear
        several times — the launcher opened it, died, and a supervisor re-adopted it (and
        was itself restarted). Those are not separate pods; they are separate *observers*
        of one pod.

        Collapsing is not cosmetic. The previous version deduped by keeping the FIRST row
        seen — which was the CLOSED one written by the dying launcher's `finally`. The
        pod's live, still-accruing row was therefore discarded and `spent()` FROZE while
        a real GPU billed on. The budget guard would never have fired. A ledger that
        under-reports is worse than no ledger, because it is trusted.

        started = earliest sighting; ended = None if ANY observer still has it open.
        """
        root = self.path.parent.parent            # <archive>/nadoc_jobs/
        merged: dict[str, dict] = {}
        for f in sorted(root.glob("*/spend.json")):
            for r in self._load_file(f):
                pid = r["pod_id"]
                cur = merged.get(pid)
                if cur is None:
                    merged[pid] = dict(r)
                    continue
                cur["started"] = min(cur["started"], r["started"])
                if cur["ended"] is None or r["ended"] is None:
                    cur["ended"] = None           # still billing somewhere
                else:
                    cur["ended"] = max(cur["ended"], r["ended"])
                cur["usd_per_hour"] = max(cur["usd_per_hour"], r["usd_per_hour"])
        return list(merged.values())

    def open_pod(self, pod_id: str, usd_per_hour: float, note: str = "") -> None:
        rows = self._load()
        rows.append({
            "pod_id": pod_id,
            "usd_per_hour": float(usd_per_hour),
            "started": time.time(),
            "ended": None,
            "note": note,
        })
        self.path.write_text(json.dumps(rows, indent=2))

    def close_pod(self, pod_id: str) -> None:
        """Close this pod in EVERY job's file — the pod is gone, so no observer's row for
        it can still be open. Closing only our own file would leave another file's row
        open forever and `spent()` would grow without bound after the pod was destroyed.
        """
        root = self.path.parent.parent
        now = time.time()
        for f in list(root.glob("*/spend.json")) + [self.path]:
            rows = self._load_file(f)
            dirty = False
            for r in rows:
                if r["pod_id"] == pod_id and r["ended"] is None:
                    r["ended"] = now
                    dirty = True
            if dirty:
                f.write_text(json.dumps(rows, indent=2))

    def spent(self) -> float:
        """Dollars burned this SESSION — every pod of every job — counting any still-open
        pod as billing RIGHT NOW."""
        now = time.time()
        total = 0.0
        for r in self._all_rows():
            end = r["ended"] if r["ended"] is not None else now
            total += (end - r["started"]) / 3600.0 * r["usd_per_hour"]
        return total

    def remaining(self) -> float:
        """What is still safely spendable, after the teardown reserve."""
        return max(0.0, HARD_CAP_USD - HEADROOM_USD - self.spent())

    def live_pods(self) -> list[str]:
        return [r["pod_id"] for r in self._all_rows() if r["ended"] is None]

    def summary(self) -> str:
        rows = self._all_rows()
        out = [f"{'pod':22s} {'$/hr':>6s} {'hours':>7s} {'cost':>7s}  note"]
        for r in rows:
            end = r["ended"] if r["ended"] is not None else time.time()
            h = (end - r["started"]) / 3600.0
            live = "" if r["ended"] is not None else "  << LIVE"
            out.append(f"{r['pod_id']:22s} {r['usd_per_hour']:6.2f} {h:7.2f} "
                       f"{h * r['usd_per_hour']:7.2f}  {r['note']}{live}")
        out.append(f"{'':22s} {'':6s} {'':7s} {self.spent():7.2f}  TOTAL "
                   f"(cap ${HARD_CAP_USD:.2f}, remaining ${self.remaining():.2f})")
        return "\n".join(out)
