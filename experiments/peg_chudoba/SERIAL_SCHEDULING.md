# Serial benchmark scheduling

**2026-09-11 status:** the bounded diagnostic driver and N135 recovery have
finished; the lease was restored to the historical controller. No next-stage
brush or atomistic pilot is running. Consult HANDOFF.md for current results.

**2026-09-10 historical update:** the user authorized matched serial/parallel experiments
and production using the best measured strategy. The new
[narrow validation runner](NARROW_VALIDATION.md) temporarily owns scheduling
through `workspace/peg_chudoba/scheduling_294_20260910/lease.json`. If its owner
is live and the lease is parked, leave the historical controller suspended.
The serial-only policy below describes the previous allocation set.

The user corrected the scheduling preference on September 9, 2026: serial
benchmarks run faster on this system. Previously 16 native PEG simulations ran
concurrently (nine CPU pivot, six CPU NPT and one GPU MD). Campaigns were
internally sequential but concurrent with one another. That scheduling was a
mistake; nice priority does not remove contention.

`serialize_existing.py` now controls the 20 existing campaign/launcher trees,
including four delayed launchers. It uses SIGSTOP/SIGCONT to preserve current
simulation state and admits one campaign at a time. Each campaign launches its
own replicas sequentially. The first admitted campaign is chain extension
round 8, N275 at 320 K. No new simulation allocation was made.

Initial authoritative verification showed one running native PEG process and
15 stopped native PEG processes, with the controller alive. No QM process was
signaled. PID start times and pidfds protect against signaling reused PIDs.
The queue and timestamped suspension/resumption events are persisted in
`serial_schedule.json`. The earlier progress checkpoint remains historical.

Suspension retains RAM and GPU VRAM; it does not create a durable restart
checkpoint. A reboot still requires the simulation's saved files and a separate
restart assessment. Existing `run.json` elapsed times include suspended wall
time and must not be used as isolated benchmark timings. Earlier concurrent
timings likewise must not be presented as serial performance measurements.

Inspect live `/proc` state before intervening. Do not launch additional benchmark
drivers: this controller manages the frozen allocation set, not arbitrary future
launches. Do not manually resume another tree while it is active.

If the controller exits, its active campaign can continue and the others remain
suspended. After checking its PID/start identity in `serial_schedule.json`, it
can be recovered with:

```sh
/usr/bin/python3 -m experiments.peg_chudoba.serialize_existing --apply
```

The file lock rejects a second controller. Recovery freezes the saved surviving
trees before resuming the first surviving campaign. The system Python is
required because the default environment's Python lacks `os.pidfd_open`.
An initial attempt with that interpreter failed before sending any signal.

The model and benchmark convergence requirements are unchanged. Full published
benchmark reproduction remains incomplete.
