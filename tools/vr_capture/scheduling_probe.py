#!/usr/bin/env python3
"""Read-only /proc scheduling sampler; sample storage is fixed, RAM-only until done.

No ptrace, signals, privileges, GPU calls, affinity/scheduler/config changes.
A sample is an observation, not proof of which lock a blocked task holds. State
and counters are read sequentially, not atomically. Scheduler wait excludes IO
sleep; PSI/VM counters are system-wide and cannot attribute stalls by themselves.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import errno
import json
import math
import os
from pathlib import Path
import resource
import struct
import time

MAX_STORAGE = 32 * 1024 * 1024
THREAD_FIELDS = ("monotonic_ns", "read_duration_ns", "target", "state_ascii", "start_ticks",
                 "minor_faults", "major_faults", "user_ticks", "system_ticks", "runtime_ns",
                 "runqueue_wait_ns", "timeslices", "processor", "error")
VM_FIELDS = ("pgmajfault", "allocstall_dma", "allocstall_dma32", "allocstall_normal",
             "allocstall_movable", "pgscan_direct", "pgsteal_direct", "compact_stall",
             "compact_fail", "compact_success", "pswpin", "pswpout", "nr_dirty", "nr_writeback")
PSI_FIELDS = tuple(f"{source}_{kind}_total_us" for source in ("cpu", "io", "memory")
                   for kind in ("some", "full"))
HOST_FIELDS = ("monotonic_ns", "read_duration_ns", "error_mask") + PSI_FIELDS + VM_FIELDS
THREAD_RECORD = struct.Struct("<" + "Q" * len(THREAD_FIELDS))
HOST_RECORD = struct.Struct("<" + "Q" * len(HOST_FIELDS))
IDENTITY_CHANGED = 10000


def parse_stat(data):
    text = data.decode("ascii", errors="replace") if isinstance(data, bytes) else data
    left, right = text.index("("), text.rindex(")")
    fields = text[right + 2:].split()
    if len(fields) < 37 or len(fields[0]) != 1:
        raise ValueError("Truncated /proc stat")
    return {"id": int(text[:left].strip()), "comm": text[left + 1:right], "state": fields[0],
            "minor_faults": int(fields[7]), "major_faults": int(fields[9]),
            "user_ticks": int(fields[11]), "system_ticks": int(fields[12]),
            "start_ticks": int(fields[19]), "processor": max(0, int(fields[36]))}


def parse_schedstat(data):
    fields = data.split()
    if len(fields) != 3:
        raise ValueError("Expected runtime, wait and timeslices")
    return tuple(int(value) for value in fields)


def parse_psi(data):
    values = {}
    for row in data.splitlines():
        fields = row.split()
        if fields and fields[0] in (b"some", b"full"):
            totals = [int(field[6:]) for field in fields[1:] if field.startswith(b"total=")]
            if len(totals) != 1:
                raise ValueError("Missing PSI total")
            values[fields[0].decode()] = totals[0]
    if "some" not in values:
        raise ValueError("Missing PSI some")
    # Old kernels may omit CPU full; preserve an explicit availability flag below.
    return values


def parse_vmstat(data):
    values = {}
    for row in data.splitlines():
        fields = row.split()
        if len(fields) == 2:
            key = fields[0].decode("ascii")
            if key in VM_FIELDS:
                values[key] = int(fields[1])
    return values


@dataclass
class Target:
    pid: int
    tid: int | None
    label: str

    @property
    def directory(self):
        return Path(f"/proc/{self.pid}" + (f"/task/{self.tid}" if self.tid else ""))

    def identity(self):
        owner = parse_stat(Path(f"/proc/{self.pid}/stat").read_bytes())
        own = parse_stat((self.directory / "stat").read_bytes())
        if own["id"] != (self.tid or self.pid):
            raise ValueError("Unexpected task identity")
        return {"pid": self.pid, "tid": self.tid, "label": self.label,
                "scope": "thread" if self.tid else "process_aggregate",
                "comm": own["comm"], "process_comm": owner["comm"],
                "start_ticks": own["start_ticks"], "process_start_ticks": owner["start_ticks"],
                "schedstat_scope": "thread" if self.tid else "not_sampled"}


def parse_target(value):
    fields = value.split(":", 2)
    if len(fields) < 2:
        raise argparse.ArgumentTypeError("Use PID:TID:label or PID:process:label")
    try:
        pid = int(fields[0])
        tid = None if fields[1] == "process" else int(fields[1])
        if pid <= 0 or (tid is not None and tid <= 0):
            raise ValueError()
    except ValueError as error:
        raise argparse.ArgumentTypeError("PID/TID must be positive integers") from error
    return Target(pid, tid, fields[2] if len(fields) > 2 else value)


def storage_size(seconds, interval, host_interval, targets):
    if not math.isfinite(seconds) or not 0 < seconds <= 30:
        raise ValueError("Duration must be in (0, 30] seconds")
    if not math.isfinite(interval) or not .01 <= interval <= 1:
        raise ValueError("Task interval must be between 10 ms and 1 second")
    if not math.isfinite(host_interval) or not .1 <= host_interval <= 1:
        raise ValueError("Host interval must be between 100 ms and 1 second")
    if not 1 <= targets <= 16:
        raise ValueError("Use 1 to 16 targets")
    tasks = (math.ceil(seconds / interval) + 2) * targets
    hosts = math.ceil(seconds / host_interval) + 2
    size = tasks * THREAD_RECORD.size + hosts * HOST_RECORD.size
    if size > MAX_STORAGE:
        raise ValueError("Sample buffer exceeds 32 MiB limit")
    return tasks, hosts, size


def sample(targets, *, seconds=7, interval=.01, host_interval=.1, on_ready=None):
    """Return buffers after measurement. on_ready must not perform slow work.

    on_ready is called after identity preflight, FD opens and preallocation, just
    before the monotonic measurement clock starts (suitable for setting an Event).
    No output writes occur here. Exceptions during preflight abort measurement.
    """
    task_capacity, host_capacity, allocation = storage_size(seconds, interval, host_interval, len(targets))
    identities = [target.identity() for target in targets]
    task_buffer = bytearray(task_capacity * THREAD_RECORD.size)
    host_buffer = bytearray(host_capacity * HOST_RECORD.size)
    descriptors = []
    task_fds = []
    psi_fds = []
    initial_psi_fields = {}
    initial_vm_fields = []
    count = host_count = missed = 0
    max_lateness = 0
    try:
        def open_read(path):
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            descriptors.append(fd)
            return fd

        for target in targets:
            stat_fd = open_read(target.directory / "stat")
            sched_fd = open_read(target.directory / "schedstat") if target.tid else None
            if sched_fd is not None:
                parse_schedstat(os.pread(sched_fd, 4096, 0))
            task_fds.append((stat_fd, sched_fd))
        for source in ("cpu", "io", "memory"):
            fd = open_read(f"/proc/pressure/{source}")
            initial_psi_fields[source] = sorted(parse_psi(os.pread(fd, 4096, 0)))
            psi_fds.append(fd)
        vm_fd = open_read("/proc/vmstat")
        initial_vm_fields = sorted(parse_vmstat(os.pread(vm_fd, 65536, 0)))
        # Reject PID/TID reuse across preflight before reporting ready.
        for target, identity in zip(targets, identities):
            if target.identity() != identity:
                raise RuntimeError("Target identity changed during preflight")
        if on_ready:
            on_ready()
        started_wall = time.time_ns()
        cpu_before = time.process_time_ns()
        started = time.monotonic_ns()
        deadline = started + round(seconds * 1e9)
        period = round(interval * 1e9)
        host_period = round(host_interval * 1e9)
        next_task = next_host = started
        while (now := time.monotonic_ns()) < deadline:
            if now < next_task:
                time.sleep((next_task - now) / 1e9)
                continue
            max_lateness = max(max_lateness, now - next_task)
            skipped = (now - next_task) // period
            missed += skipped
            next_task += (skipped + 1) * period
            for index, ((stat_fd, sched_fd), identity) in enumerate(zip(task_fds, identities)):
                begin = time.monotonic_ns()
                error = 0
                state = start_ticks = minor = major = user = system = runtime = waiting = slices = processor = 0
                try:
                    stat = parse_stat(os.pread(stat_fd, 4096, 0))
                    if stat["start_ticks"] != identity["start_ticks"] or stat["id"] != (identity["tid"] or identity["pid"]):
                        error = IDENTITY_CHANGED
                    else:
                        state, start_ticks = ord(stat["state"]), stat["start_ticks"]
                        minor, major = stat["minor_faults"], stat["major_faults"]
                        user, system, processor = stat["user_ticks"], stat["system_ticks"], stat["processor"]
                        if sched_fd is not None:
                            runtime, waiting, slices = parse_schedstat(os.pread(sched_fd, 4096, 0))
                except OSError as exc:
                    error = exc.errno or errno.EIO
                except (ValueError, IndexError):
                    error = errno.EBADMSG
                THREAD_RECORD.pack_into(task_buffer, count * THREAD_RECORD.size, begin,
                                        time.monotonic_ns() - begin, index, state, start_ticks, minor,
                                        major, user, system, runtime, waiting, slices, processor, error)
                count += 1
            if time.monotonic_ns() >= next_host:
                begin = time.monotonic_ns()
                next_host += ((begin - next_host) // host_period + 1) * host_period
                pressure, error_mask = [], 0
                for index, fd in enumerate(psi_fds):
                    try:
                        values = parse_psi(os.pread(fd, 4096, 0))
                        pressure.extend((values["some"], values.get("full", 0)))
                    except (OSError, ValueError):
                        pressure.extend((0, 0))
                        error_mask |= 1 << index
                try:
                    vm = parse_vmstat(os.pread(vm_fd, 65536, 0))
                except (OSError, ValueError):
                    vm = {}
                    error_mask |= 8
                HOST_RECORD.pack_into(host_buffer, host_count * HOST_RECORD.size, begin,
                                      time.monotonic_ns() - begin, error_mask, *pressure,
                                      *(vm.get(key, 0) for key in VM_FIELDS))
                host_count += 1
        ended = time.monotonic_ns()
        cpu_after = time.process_time_ns()
    finally:
        for fd in descriptors:
            os.close(fd)
    metadata = {"schema": 1, "read_only": True, "clock": "CLOCK_MONOTONIC",
                "start_ns": started, "end_ns": ended, "start_wall_ns": started_wall,
                "requested_seconds": seconds, "task_interval_ns": period, "host_interval_ns": host_period,
                "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"), "targets": identities,
                "task_samples": count, "host_samples": host_count, "missed_task_periods": missed,
                "maximum_sample_lateness_ns": max_lateness, "sample_buffer_bytes": allocation,
                "sample_buffer_limit_bytes": MAX_STORAGE,
                "observer_process_cpu_ns": cpu_after - cpu_before,
                "observer_cpu_fraction_of_one_core": (cpu_after - cpu_before) / (ended - started),
                "observer_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "psi_fields_available": initial_psi_fields, "vm_fields_available": initial_vm_fields,
                "limitations": ["Sequential observations are not atomic.",
                                "Process aggregate stat counters have no matching schedstat; thread targets do.",
                                "System PSI and VM counters cannot attribute an individual process stall.",
                                "A task state does not identify a lock owner or kernel wait channel.",
                                "Self CPU is measured; negligible observer effect is not established.",
                                "Reported RSS is process lifetime peak; fixed sample buffers alone are capped at 32 MiB."]}
    return metadata, task_buffer, host_buffer


def write_results(output, result):
    output = Path(output)
    # Called only after all measurement has finished, exclusive output directory.
    output.mkdir(parents=True, exist_ok=False)
    metadata, task_buffer, host_buffer = result
    for name, fields, record, data, count in (
            ("tasks", THREAD_FIELDS, THREAD_RECORD, task_buffer, metadata["task_samples"]),
            ("host", HOST_FIELDS, HOST_RECORD, host_buffer, metadata["host_samples"])):
        with (output / f"{name}.jsonl").open("x") as stream:
            for offset in range(count):
                row = dict(zip(fields, record.unpack_from(data, offset * record.size)))
                if name == "tasks":
                    row["state"] = chr(row.pop("state_ascii")) if row["state_ascii"] else None
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    (output / "summary.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", required=True, type=parse_target)
    parser.add_argument("--seconds", type=float, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.preflight_only:
        print(json.dumps([target.identity() for target in args.target], indent=2))
        return 0
    if args.output is None or args.output.exists():
        parser.error("A new --output directory is required")
    # Avoid writing on a missing Archive mount. Other locations require library use.
    archive = Path("/media/jojo/Archive")
    if not archive.is_mount() or not args.output.resolve().is_relative_to(archive.resolve()):
        parser.error("Output must be on mounted /media/jojo/Archive")
    result = sample(args.target, seconds=args.seconds)
    print(json.dumps(write_results(args.output, result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
