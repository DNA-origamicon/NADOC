# CPU scaling revision, 2026-09-10

The user requested a 12-worker benchmark first and authorized adopting 12 as
standard if throughput follows the approximately linear trend. This revision
changes scheduling only; BOUNDED_VALIDATION.md and its scientific limits remain
unchanged, and its original hash remains valid.

## Measurement fixed before results

Two N135/294 K workloads: 108 chains at 10 and 1000 kPa. Each batch runs the
same twelve frozen-source tasks (seeds 95001–95012), 200 sweeps each. Twelve
workers run first, followed by four; a second round reverses workload and
concurrency order. Eight batches, 96 native timing tasks. Timing output is
excluded from equilibrium validation. Sources, engine hashes, seeds, output
cadence and work are matched. Existing PEG production is paused during timing;
unrelated workstation processes remain untouched.

Adopt twelve NPT workers only if each of the four matched throughput ratios
is at least 2.4 relative to four workers (80% of ideal linear scaling), all
allocations complete, and every matched CPU endpoint hash is identical.
Otherwise retain four. This does not establish a twelve-worker standard for
unbenchmarked samplers or imply any benefit from SMT beyond physical cores.

## Safe transition and production

The previous bounded driver is retired only after lease ownership transfers
under the existing lock and the new owner is recorded. All native replicas
remain paused in RAM and are subsequently adopted without restarting their
allocations. PID/start identities and the existing watchdog protect recovery.
The scale_cpu driver owns this lease until bounded production finishes.

Remaining reserved replicas share the selected worker pool. Afterwards, up to
four independent pressure cohorts, with three origins each, run concurrently
when twelve workers are selected. No extra replicas or simulation lengths are
added to fill idle slots. GPU validation remains one job at a time in its
separate phase.

`workspace/peg_chudoba/scheduling_294_20260910/cpu12/` holds the frozen plan,
results, selection and code snapshot. `active_selection.json` records the
adopted standard without overwriting the original 1/2/4-worker benchmark.
The ordinary benchmark/validation entry point honors this measured override
on future invocations in the same campaign directory. Inspect `lease.json`,
`bounded_driver.json`, and `cpu12_driver.log` before any recovery or restart;
do not run another driver while the current owner is live.

## Result

All four ratios passed: 2.736, 2.726, 2.695, 2.683. Geometric mean 2.710x
versus four workers (90.3% of ideal linear scaling). All 96 runs completed;
all 48 matched endpoints were identical. Twelve NPT workers are now the
standard for this campaign. Ten available reserved replicas resumed/started
immediately; later pressure cohorts can use all twelve slots.
