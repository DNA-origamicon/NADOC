"""Tests for NAMD thread defaulting + CPU-affinity prefix in namd_runner.py.

- ``default_threads()`` → half the logical CPUs (== physical cores on 2-way SMT),
  floored at 1.  This is the autodetected NAMD ``+p`` count.
- ``_core_binding_prefix()`` → a ``taskset`` prefix ONLY when ``$NADOC_NAMD_CORES``
  is set; otherwise empty (NAMD's ``+setcpuaffinity`` handles placement).  The old
  auto ``0-{n-1}`` mask collapsed onto half the physical cores on SMT machines.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core import namd_runner


# ── default_threads ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cpu_count, expected",
    [
        (12, 6),  # Ryzen 5 3600: 6 physical / 12 logical → 6
        (8, 4),
        (1, 1),  # floor: never return 0
        (2, 1),
        (None, 1),  # os.cpu_count() can return None
    ],
)
def test_default_threads_is_half_logical_floored(cpu_count, expected, monkeypatch):
    monkeypatch.setattr(namd_runner.os, "cpu_count", lambda: cpu_count)
    assert namd_runner.default_threads() == expected


# ── _core_binding_prefix ──────────────────────────────────────────────────────


def test_no_taskset_prefix_without_env(monkeypatch):
    """Without NADOC_NAMD_CORES, no taskset wrapper — +setcpuaffinity does placement."""
    monkeypatch.delenv("NADOC_NAMD_CORES", raising=False)
    assert namd_runner._core_binding_prefix(6) == []


def test_taskset_prefix_honors_explicit_env(monkeypatch):
    """An explicit core spec is passed straight through to taskset -c."""
    monkeypatch.setenv("NADOC_NAMD_CORES", "0,2,4,6,8,10")
    monkeypatch.setattr(namd_runner.shutil, "which", lambda c: "/usr/bin/taskset")
    assert namd_runner._core_binding_prefix(6) == [
        "/usr/bin/taskset",
        "-c",
        "0,2,4,6,8,10",
    ]


def test_no_prefix_when_taskset_missing_even_with_env(monkeypatch):
    """If taskset isn't installed, fall back to no prefix rather than erroring."""
    monkeypatch.setenv("NADOC_NAMD_CORES", "0-5")
    monkeypatch.setattr(namd_runner.shutil, "which", lambda c: None)
    assert namd_runner._core_binding_prefix(6) == []


# ── _run_namd_async launch command ────────────────────────────────────────────


def test_run_namd_omits_devices_flag_for_cpu_only(tmp_path, monkeypatch):
    """CPU-only NAMD runs must omit +devices entirely; +devices "" confuses NAMD."""
    seen = {}

    class FakeProc:
        pid = 123

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(
        namd_runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    rc, pid = asyncio.run(
        namd_runner._run_namd_async(
            "/fake/namd3",
            "min",
            tmp_path,
            tmp_path / "min.log",
            4,
            "",
        )
    )

    assert (rc, pid) == (0, 123)
    assert "+devices" not in seen["cmd"]
    assert seen["cmd"][-1] == "min.conf"
