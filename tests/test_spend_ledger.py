"""The cumulative pod-spend ledger.

The in-code kill-switch is per-POD and has no memory, so this file is the only thing that
knows what a SESSION has cost. A ledger that under-reports is worse than no ledger at all,
because it is trusted — and the budget guard reads it.
"""

from __future__ import annotations

import json
import time

import pytest

from experiments.exp43_runpod_bench.spend_ledger import HARD_CAP_USD, SpendLedger


@pytest.fixture
def root(tmp_path):
    (tmp_path / "nadoc_jobs" / "jobA").mkdir(parents=True)
    (tmp_path / "nadoc_jobs" / "jobB").mkdir(parents=True)
    return tmp_path / "nadoc_jobs"


def _write(root, job, rows):
    (root / job / "spend.json").write_text(json.dumps(rows))


class TestOnePodBillsOnceHoweverManyProcessesWatchedIt:
    """THE bug. A pod bills continuously from creation to destruction, no matter how many
    processes happened to be watching it.

    The launcher opened the pod, died on a DNS blip (its `finally` CLOSED the row), and a
    supervisor re-adopted it — writing a second, OPEN row. The ledger deduped by keeping
    the FIRST row seen, i.e. the CLOSED one, so the live row was discarded and spent()
    FROZE while a real GPU billed on. The budget guard could never have fired.
    """

    def test_a_reopened_pod_keeps_accruing(self, root):
        now = time.time()
        _write(
            root,
            "jobA",
            [
                # launcher: opened, then closed by its dying `finally` after 30 min
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 7200,
                    "ended": now - 5400,
                    "note": "launcher",
                },
                # supervisor: re-adopted the SAME pod, still open
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 5000,
                    "ended": None,
                    "note": "adopted",
                },
            ],
        )
        led = SpendLedger(root / "jobA" / "spend.json")

        # One pod, billing from its EARLIEST sighting until now: ~2 h at $1/hr.
        assert led.spent() == pytest.approx(2.0, abs=0.05)
        assert led.live_pods() == ["P1"]

    def test_the_frozen_total_would_have_hidden_a_live_pod(self, root):
        """Regression: the old dedupe-by-first would have reported only the closed row
        (0.5 h = $0.50) and stayed there forever."""
        now = time.time()
        _write(
            root,
            "jobA",
            [
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 7200,
                    "ended": now - 5400,
                    "note": "launcher",
                },
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 5000,
                    "ended": None,
                    "note": "adopted",
                },
            ],
        )
        led = SpendLedger(root / "jobA" / "spend.json")
        assert led.spent() > 0.5, "a live pod must not be invisible"

    def test_closing_a_pod_closes_it_in_every_jobs_file(self, root):
        """The pod is GONE; no observer's row for it can still be open. Closing only our
        own file would leave another file's row open forever, and spent() would grow
        without bound after the pod had already been destroyed."""
        now = time.time()
        _write(
            root,
            "jobA",
            [
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 3600,
                    "ended": None,
                    "note": "a",
                }
            ],
        )
        _write(
            root,
            "jobB",
            [
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 3600,
                    "ended": None,
                    "note": "b",
                }
            ],
        )

        led = SpendLedger(root / "jobB" / "spend.json")
        led.close_pod("P1")
        assert led.live_pods() == []

        after = led.spent()
        time.sleep(0.05)
        assert led.spent() == pytest.approx(after, abs=1e-6), (
            "a destroyed pod must stop accruing"
        )


class TestTheCapIsForTheWholeSession:
    def test_spend_sums_every_job_not_just_this_one(self, root):
        now = time.time()
        _write(
            root,
            "jobA",
            [
                {
                    "pod_id": "P1",
                    "usd_per_hour": 1.0,
                    "started": now - 3600,
                    "ended": now,
                    "note": "a",
                }
            ],
        )
        _write(
            root,
            "jobB",
            [
                {
                    "pod_id": "P2",
                    "usd_per_hour": 2.0,
                    "started": now - 3600,
                    "ended": now,
                    "note": "b",
                }
            ],
        )
        # A per-JOB ledger would hand a re-prepped job a fresh, full $15.
        led = SpendLedger(root / "jobB" / "spend.json")
        assert led.spent() == pytest.approx(3.0, abs=0.05)

    def test_remaining_reserves_headroom_for_teardown(self, root):
        _write(root, "jobA", [])
        led = SpendLedger(root / "jobA" / "spend.json")
        assert led.remaining() < HARD_CAP_USD, "must hold back a teardown reserve"

    def test_a_corrupt_file_never_authorises_spending(self, root):
        (root / "jobA" / "spend.json").write_text("{ not json")
        led = SpendLedger(root / "jobA" / "spend.json")
        assert led.spent() == 0.0  # and does not explode
