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

HARD_CAP_USD = 15.0

# Leave this much unspent. Reserve, not slack: it absorbs the minutes a pod bills while
# it is being provisioned, staged and torn down — time that does no science but is
# charged all the same.
HEADROOM_USD = 1.50


class SpendLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001 — a corrupt ledger must not authorise spending
            return []

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
        rows = self._load()
        for r in rows:
            if r["pod_id"] == pod_id and r["ended"] is None:
                r["ended"] = time.time()
        self.path.write_text(json.dumps(rows, indent=2))

    def spent(self) -> float:
        """Dollars burned so far, counting any pod still open as billing RIGHT NOW."""
        now = time.time()
        total = 0.0
        for r in self._load():
            end = r["ended"] if r["ended"] is not None else now
            total += (end - r["started"]) / 3600.0 * r["usd_per_hour"]
        return total

    def remaining(self) -> float:
        """What is still safely spendable, after the teardown reserve."""
        return max(0.0, HARD_CAP_USD - HEADROOM_USD - self.spent())

    def live_pods(self) -> list[str]:
        return [r["pod_id"] for r in self._load() if r["ended"] is None]

    def summary(self) -> str:
        rows = self._load()
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
