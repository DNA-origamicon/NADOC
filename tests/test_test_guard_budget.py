"""scripts/test_guard.sh — the fast-suite budget banners, and their sim suppression.

A production NAMD/oxDNA/mrDNA job takes every core, and pytest is niced to +10 below it,
so a healthy 2 s test can measure 6 s and trip the 5 s per-test budget.  Triaging on those
numbers relegates innocent tests to the slow suite permanently, so the guard must record
the violators but demand nothing while a sim is live.

The guard resolves every path (candidates report, lock, session marker) relative to CWD,
and the lock/session paths are env-overridable — so these run it in a tmp dir and never
touch the repo's real lock or report.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_GUARD = Path(__file__).resolve().parent.parent / "scripts" / "test_guard.sh"


def _run_guard(tmp_path: Path, report: dict | None) -> str:
    """Run the guard around a trivial command; return its stderr (where banners go)."""
    if report is not None:
        (tmp_path / ".nadoc-slow-candidates.json").write_text(json.dumps(report))
    proc = subprocess.run(
        ["bash", str(_GUARD), "test-fast", "0", "0", "--", "true"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            # keep the guard's lock + session marker inside tmp_path
            "NADOC_TEST_LOCK": str(tmp_path / "lock"),
            "NADOC_TEST_SESSION_FILE": str(tmp_path / "no-session"),
            "NADOC_TEST_NICE": "0",
        },
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stderr


def _report(*, n_violators: int, **extra) -> dict:
    return {
        "per_test_budget_sec": 5,
        "violators": [
            {"nodeid": f"tests/test_x.py::test_{i}", "seconds": 6.5 + i}
            for i in range(n_violators)
        ],
        **extra,
    }


@pytest.mark.parametrize("sim_flag", [False, None])
def test_violators_trip_the_triage_banner_when_no_sim_is_running(tmp_path, sim_flag):
    """sim_running False — and ABSENT (a report written before this feature) — must both
    behave as 'idle', so the gate can never be silently lost."""
    extra = {} if sim_flag is None else {"sim_running": False}
    err = _run_guard(tmp_path, _report(n_violators=2, **extra))
    assert "HEAVY TEST IN THE FAST SUITE" in err
    assert "BUDGET CHECK SUPPRESSED" not in err


def test_sim_running_suppresses_the_triage_banner(tmp_path):
    err = _run_guard(
        tmp_path,
        _report(n_violators=3, sim_running=True, sim_reason="NAMD job 2hb_1xT"),
    )
    assert "HEAVY TEST IN THE FAST SUITE" not in err
    assert "BUDGET CHECK SUPPRESSED" in err
    assert "NAMD job 2hb_1xT" in err          # says WHICH job, not just "a sim"
    assert "3 over-budget test(s) recorded" in err   # the data is not thrown away


def test_sim_running_suppresses_the_total_wallclock_backstop(tmp_path):
    """The aggregate backstop is contention-sensitive too, so it is suppressed as well.

    No violators here, so on an idle machine a long run would print the FAST SUITE TOO
    SLOW banner; under a sim it must not.
    """
    err = _run_guard(
        tmp_path,
        _report(n_violators=0, sim_running=True, sim_reason="oxDNA job"),
    )
    assert "FAST SUITE TOO SLOW" not in err
    assert "HEAVY TEST IN THE FAST SUITE" not in err


def test_no_report_file_at_all_is_not_a_violation(tmp_path):
    """A run that never wrote the report (e.g. collection error) must not banner."""
    err = _run_guard(tmp_path, None)
    assert "HEAVY TEST IN THE FAST SUITE" not in err
    assert "BUDGET CHECK SUPPRESSED" not in err


def test_sim_reason_newlines_cannot_break_the_shell_read(tmp_path):
    """sim_reason is interpolated into a shell `read`; a multi-line reason must not
    truncate the parse and silently drop sim_running."""
    err = _run_guard(
        tmp_path,
        _report(n_violators=1, sim_running=True, sim_reason="NAMD\nrunning\nhere"),
    )
    assert "BUDGET CHECK SUPPRESSED" in err
    assert "HEAVY TEST IN THE FAST SUITE" not in err
