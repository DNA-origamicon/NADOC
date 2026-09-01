"""Node-side live-metrics collector — staged onto the cluster and run there.

A remote NADOC job showed NOTHING while it ran: no speed, no temperature, no
pressure, and a progress bar pinned at zero.  The data existed the whole time, in
the NAMD log on the compute node, but ``poll_remote_progress`` deliberately
transfers no content (it runs ``ls`` only), and ``metrics.jsonl`` is written just
once a segment COMPLETES and is fetched back.  For the short-walltime + resume
workflow no segment ever completes inside a block, so the panel stayed blank for
the entire run.

Rather than pull multi-hundred-KB logs across the wire every poll, the parsing
happens HERE, on the node, and the result is a tiny JSON file NADOC can ``cat``.

**Runs on Alpine's bare node python3, which is 3.6** (see remote_cutoff_eval.py):
no ``from __future__ import annotations`` (hard SyntaxError), no ``dataclasses``,
no f-strings with ``=``, stdlib only.  Keep it that way.
"""

import glob
import json
import os
import re
import sys
import time

# NAMD prints this TWO ways depending on build/version:
#   `... 0.0112177 s/step 0.0324585 days/ns 0 MB memory`   (days per ns)
#   `... 0.000524329 s/step 659.129 ns/day 0 MB memory`    (ns per day)
# Matching only `days/ns` silently dropped the speed field on the Alpine build while
# every other metric populated — live-confirmed 2026-08-07.
_BENCH_SPS_RE = re.compile(r"Benchmark time:.*?([0-9.eE+-]+)\s+s/step")
_BENCH_NSDAY_RE = re.compile(r"([0-9.eE+-]+)\s+ns/day")
_BENCH_DPNS_RE = re.compile(r"([0-9.eE+-]+)\s+days/ns")
# `TIMING: 265000  CPU: 1234.5, 0.00456/step  Wall: 1240.1, 0.00458/step, ...`
# TIMING recurs all run long, unlike Benchmark, which only appears near the start.
_TIMING_SPS_RE = re.compile(r"Wall:\s*[0-9.eE+-]+,\s*([0-9.eE+-]+)/step")
# `Info: TIMESTEP               4`  — needed to turn s/step into ns/day.
_TIMESTEP_RE = re.compile(r"^Info: TIMESTEP\s+([0-9.eE+-]+)", re.M)
# `TIMING: 5000  CPU: ... , 0.0112 s/step ...`
# MULTILINE: without it `^` only matches at offset 0 and every TIMING line after
# the first is invisible — the step counter would freeze at the ENERGY value.
_TIMING_RE = re.compile(r"^TIMING:\s+(\d+)", re.M)
# NAMD ENERGY columns (v2.13+ / 3.x), 0-indexed after the leading "ENERGY:" token.
_E_TS, _E_TEMP, _E_TOTAL = 0, 11, 10
_E_PRESSURE, _E_VOLUME, _E_GPRESSAVG = 15, 17, 19


def _head(path, max_bytes=131072):
    """First ``max_bytes`` of a file — where NAMD writes its static run parameters.

    ``Info: TIMESTEP`` and the ``Benchmark time`` lines appear near the START of a
    run, so a tail-only reader loses them the moment the log grows past its window.
    """
    with open(path, "rb") as fh:
        return fh.read(max_bytes).decode("utf-8", "replace")


def _tail(path, max_bytes=262144):
    """Last ``max_bytes`` of a file as text — a NAMD log grows without bound."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
        raw = fh.read()
    return raw.decode("utf-8", "replace")


def _float(tokens, idx):
    try:
        return float(tokens[idx])
    except (IndexError, ValueError):
        return None


def parse_log_text(text):
    """Extract the scalars the MD panel renders, from a chunk of NAMD log.

    Returns a plain dict (JSON-ready).  Every field may be absent: a production
    stage with a large ``outputEnergies`` writes ENERGY lines rarely, so the
    caller must treat missing values as "not known yet", never as zero.
    """
    out = {}

    for line in text.splitlines():
        if "Benchmark time:" not in line:
            continue
        m = _BENCH_SPS_RE.search(line)
        if m:
            try:
                out["s_per_step"] = float(m.group(1))
            except ValueError:
                pass
        ns = _BENCH_NSDAY_RE.search(line)
        dp = _BENCH_DPNS_RE.search(line)
        try:
            if ns:
                out["ns_per_day"] = float(ns.group(1))
            elif dp and float(dp.group(1)) > 0:
                out["ns_per_day"] = 1.0 / float(dp.group(1))
        except ValueError:
            pass

    # TIMING is the LIVE speed: it recurs every outputTiming steps, while Benchmark
    # appears once near the start.  Prefer it when present.
    tm = _TIMING_SPS_RE.findall(text)
    if tm:
        try:
            out["s_per_step"] = float(tm[-1])
        except ValueError:
            pass

    energy = None
    for line in text.splitlines():
        if line.startswith("ENERGY:"):
            energy = line
    if energy is not None:
        tok = energy.split()[1:]
        out["step"] = int(_float(tok, _E_TS) or 0)
        for key, idx in (
            ("temperature_k", _E_TEMP),
            ("total_energy_kcal", _E_TOTAL),
            ("pressure_bar", _E_PRESSURE),
            ("volume_ang3", _E_VOLUME),
            ("gpressure_avg_bar", _E_GPRESSAVG),
        ):
            val = _float(tok, idx)
            if val is not None:
                out[key] = val

    # TIMING lines advance far more often than ENERGY on a production stage, so
    # they are the better step counter for a progress bar.
    steps = _TIMING_RE.findall(text)
    if steps:
        out["step"] = max(int(steps[-1]), out.get("step", 0))
    return out


def ns_per_day(s_per_step, timestep_fs):
    """ns/day from seconds-per-step and the integrator timestep.

    ns/step = timestep_fs * 1e-6, so ns/day = timestep_fs * 0.0864 / s_per_step.
    """
    try:
        if s_per_step and timestep_fs and float(s_per_step) > 0:
            return float(timestep_fs) * 0.0864 / float(s_per_step)
    except (TypeError, ValueError):
        pass
    return None


def step_from_xsc(path):
    """Current step from a NAMD ``.restart.xsc`` — its first data column.

    Written every ``restartfreq`` steps, so it advances even when the log is
    quiet, which is exactly the production-stage case.
    """
    try:
        with open(path) as fh:
            last = ""
            for line in fh:
                if line.strip() and not line.startswith("#"):
                    last = line
        if last:
            return int(float(last.split()[0]))
    except (IOError, OSError, ValueError, IndexError):
        pass
    return None


def file_sizes(work_dir):
    """Return live trajectory and total bytes for the remote job directory."""
    dcd_bytes = 0
    total_bytes = 0
    try:
        for root, _dirs, files in os.walk(work_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                total_bytes += size
                if name.lower().endswith(".dcd"):
                    dcd_bytes += size
    except OSError:
        pass
    return dcd_bytes, total_bytes


def collect(work_dir):
    """Scan a job's scratch dir → the live-metrics dict NADOC retrieves."""
    logs = sorted(
        glob.glob(os.path.join(work_dir, "*.log")), key=lambda p: os.path.getmtime(p)
    )
    dcd_bytes, total_bytes = file_sizes(work_dir)
    if not logs:
        return {
            "collected_at": time.time(),
            "segment": None,
            "dcd_size_bytes": dcd_bytes,
            "total_size_bytes": total_bytes,
        }
    active = logs[-1]
    data = parse_log_text(_tail(active))
    # The head carries TIMESTEP and the early Benchmark lines, both of which scroll
    # out of the tail window on a long run.
    head = parse_log_text(_head(active))
    for key in ("ns_per_day", "s_per_step"):
        if key not in data and key in head:
            data[key] = head[key]
    ts = _TIMESTEP_RE.search(_head(active))
    if ts:
        try:
            data["timestep_fs"] = float(ts.group(1))
        except ValueError:
            pass
    # Recompute from the LIVE s/step whenever we have both — that tracks the run,
    # whereas the Benchmark figure is frozen at start-up.
    live = ns_per_day(data.get("s_per_step"), data.get("timestep_fs"))
    if live is not None:
        data["ns_per_day"] = live
    data["segment"] = os.path.basename(active)[:-4]
    data["collected_at"] = time.time()
    data["dcd_size_bytes"] = dcd_bytes
    data["total_size_bytes"] = total_bytes

    xsc = os.path.join(work_dir, "output", data["segment"] + ".restart.xsc")
    step = step_from_xsc(xsc)
    if step is not None:
        data["step"] = max(step, data.get("step", 0))
    return data


def main(argv):
    work = argv[1] if len(argv) > 1 else "."
    out = os.path.join(work, "output", "live_metrics.json")
    interval = float(argv[2]) if len(argv) > 2 else 0.0
    while True:
        try:
            data = collect(work)
            tmp = out + ".tmp"
            d = os.path.dirname(out)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            # Atomic replace: NADOC may `cat` this at any moment and must never
            # read a half-written file.
            os.rename(tmp, out)
        except Exception as exc:  # never kill the run over metrics
            sys.stderr.write("live-metrics: %s\n" % exc)
        if interval <= 0:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
