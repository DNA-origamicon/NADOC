"""Proc parsing, bounded allocation and observer output contracts (no GPU access)."""
import json
import os

import pytest

from tools.vr_capture import scheduling_probe as probe


def stat_line():
    # Fields 3..52; comm deliberately contains parentheses and spaces.
    fields = [str(number) for number in range(3, 53)]
    fields[0] = "S"
    return "123 (worker (read) end) " + " ".join(fields)


def test_proc_stat_indexes_and_awkward_comm():
    got = probe.parse_stat(stat_line())
    assert got == {"id": 123, "comm": "worker (read) end", "state": "S",
                   "minor_faults": 10, "major_faults": 12, "user_ticks": 14,
                   "system_ticks": 15, "start_ticks": 22, "processor": 39}


def test_schedstat_units_and_missing_fields():
    assert probe.parse_schedstat(b"1234 5678 90\n") == (1234, 5678, 90)
    with pytest.raises(ValueError):
        probe.parse_schedstat(b"1234 5678")


def test_psi_totals_and_vm_scope():
    assert probe.parse_psi(b"some avg10=0.00 total=123\nfull avg10=0.00 total=45\n") == {"some": 123, "full": 45}
    assert probe.parse_psi(b"some total=123\n") == {"some": 123}
    with pytest.raises(ValueError):
        probe.parse_psi(b"some avg10=0.00")
    assert probe.parse_vmstat(b"pgmajfault 45\nnot_selected 76\nallocstall_normal 90\n") == {"pgmajfault": 45, "allocstall_normal": 90}


def test_maximum_preallocated_storage_is_below_cap():
    tasks, hosts, size = probe.storage_size(30, .01, .1, 16)
    assert tasks == 3002 * 16 and hosts == 302
    assert size < 6 * 1024 * 1024 < probe.MAX_STORAGE


@pytest.mark.parametrize("seconds,interval,targets", [(float("nan"), .01, 1), (31, .01, 1), (1, .001, 1), (1, .01, 17)])
def test_rejects_unbounded_sampling(seconds, interval, targets):
    with pytest.raises(ValueError):
        probe.storage_size(seconds, interval, .1, targets)


def test_process_and_thread_scope_are_explicit():
    assert probe.parse_target("123:process:viewer").tid is None
    assert probe.parse_target("123:456:reader").tid == 456


def test_self_sample_has_no_output_until_explicit_write(tmp_path):
    pid = os.getpid()
    result = probe.sample([probe.Target(pid, pid, "test observer")], seconds=.025)
    assert not list(tmp_path.iterdir())
    metadata = result[0]
    assert metadata["task_samples"] >= 1 and metadata["host_samples"] == 1
    assert metadata["targets"][0]["start_ticks"] > 0
    assert metadata["observer_process_cpu_ns"] > 0
    output = tmp_path / "observations"
    probe.write_results(output, result)
    rows = [json.loads(line) for line in (output / "tasks.jsonl").read_text().splitlines()]
    assert all(row["error"] == 0 and row["start_ticks"] > 0 for row in rows)
    assert all(row["runtime_ns"] > 0 and row["state"] for row in rows)
    with pytest.raises(FileExistsError):
        probe.write_results(output, result)
