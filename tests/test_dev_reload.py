"""Is this process a reloader child? (backend/core/dev_reload)

The only caller is the shutdown hook that destroys RunPod pods, so a wrong answer is a
money answer in one direction and a lost multi-day run in the other. These pin which way
each failure falls.
"""

from __future__ import annotations

from backend.core import dev_reload


class _Proc:
    """A fake /proc: {pid: (cmdline, ppid)}."""

    def __init__(self, table):
        self.table = table

    def cmdline(self, pid):
        return self.table.get(pid, ("", 0))[0]

    def ppid(self, pid):
        return self.table.get(pid, ("", 0))[1]


def _patch(monkeypatch, table):
    proc = _Proc(table)
    monkeypatch.setattr(dev_reload, "_cmdline", proc.cmdline)
    monkeypatch.setattr(dev_reload, "_ppid", proc.ppid)


def test_finds_the_reloader_through_a_spawn_child(monkeypatch):
    """The real shape measured on this machine: the app runs as a multiprocessing spawn
    child of the `uvicorn --reload` supervisor, and inherits none of its argv."""
    _patch(
        monkeypatch,
        {
            100: ("python -c from multiprocessing.spawn import spawn_main; ...", 50),
            50: ("python /venv/bin/uvicorn backend.api.main:app --reload --reload-dir backend", 20),
            20: ("uv run uvicorn backend.api.main:app --reload", 1),
        },
    )
    assert dev_reload.under_reloader(100) is True


def test_a_production_server_is_not_a_reload(monkeypatch):
    """No --reload anywhere => a real shutdown => the pods MUST be destroyed."""
    _patch(
        monkeypatch,
        {
            100: ("python /venv/bin/uvicorn backend.api.main:app --host 0.0.0.0", 1),
        },
    )
    assert dev_reload.under_reloader(100) is False


def test_unreadable_proc_falls_back_to_terminating(monkeypatch):
    """Fail toward the expensive-but-safe answer: a leaked pod bills forever, a killed dev
    run costs minutes and resumes from the volume."""
    _patch(monkeypatch, {})
    assert dev_reload.under_reloader(100) is False


def test_gives_up_rather_than_walking_to_init(monkeypatch):
    _patch(monkeypatch, {i: (f"proc{i}", i + 1) for i in range(1, 60)})
    assert dev_reload.under_reloader(1, max_depth=4) is False


def test_survives_a_parent_loop(monkeypatch):
    """A pid whose parent is itself must not hang the shutdown path."""
    _patch(monkeypatch, {7: ("some-proc", 7)})
    assert dev_reload.under_reloader(7) is False


def test_reads_the_real_process_tree_without_raising():
    """Whatever this test runner's ancestry is, the answer is a bool and nothing throws."""
    assert isinstance(dev_reload.under_reloader(), bool)


def test_ppid_parse_survives_a_comm_with_spaces_and_parens():
    """`raw.split()[3]` is wrong: field 2 is the executable name in parentheses and may
    contain both spaces and ')'. NAMD renames itself "NAMD masterPe" — exactly this shape."""
    assert dev_reload.parse_ppid("4242 (NAMD (masterPe) x) S 999 4242 0 -1 0") == 999
    assert dev_reload.parse_ppid("7 (python3) S 3888561 7 7 0 -1 0") == 3888561


def test_ppid_parse_never_raises_on_garbage():
    for junk in ("", "not a stat line", "1 (x)", "1 (x) S"):
        assert dev_reload.parse_ppid(junk) == 0
