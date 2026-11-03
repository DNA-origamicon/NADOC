# The 3x6x400 production run (2026-07-14) — what it proved, and what it cost — supporting detail

[Topic head](../../project_runpod_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## The 3x6x400 production run (2026-07-14) — what it proved, and what it cost

**1.94M atoms, full ladder + 5.5 ns production, ~$13 of a $15 cap.**

| | |
|---|---|
| relaxation | **4/4 stages bridged at p10** — 4.32M of 4.8M steps SKIPPED (a **10x** acceleration; exp36's 4.9x was pessimistic) |
| | 4.6 h, **$3.99**. Un-accelerated: ~35 h, ~$26 |
| measured 4 fs GPU-resident | **26.4 ms/step** = 13.1 ns/day on an RTX PRO 4500 Blackwell |
| ⚠️ | the 4090 per-Matom fit predicted **20.9** — it does **NOT transfer across architectures** |
| bugs found | **11 — and NINE produced no error of any kind** |

The 6hb e2e (225k atoms, 5 min, $0.03) was green and documented as "PROVEN on a live pod".
**It reached none of the eleven.** Scale, duration and money each expose a disjoint class of
failure.

> **READ BEFORE RENTING ANYTHING:**
> * **[REFERENCE_RUNPOD_RUNBOOK](../../REFERENCE_RUNPOD_RUNBOOK.md)** — the hardened protocol:
>   pre-flight gates, the measured cost model, monitoring, teardown, the failure catalogue.
> * **`python experiments/exp43_runpod_bench/preflight.py <job_id>`** — the MECHANICAL gate.
>   It refuses a package that would silently cost 4x, run on the wrong disk, or rent a card
>   the binary cannot execute. Verified: it rejects the exact broken package this run
>   started from, and passes the one that worked.
> * **[LESSONS](../../LESSONS.md) category L (L1–L6)** — indexed by symptom.

**The two lessons worth carrying to any rented-compute work:**

1. **"Fails safe" can mean "fails expensive."** The early-stop evaluator's fail-safe is HOLD
   (run everything) — right for the science, ruinous for the wallet. Always ask: *safe for
   whom?*
2. **A safety net can have the same hole as the thing it protects.** The spend ledger existed
   *because* the kill-switch had no memory — and then it under-reported, freezing at $0.95
   while a real GPU billed to $1.35. **A ledger that under-reports is worse than no ledger,
   because it is trusted.**

**Scripts** (`experiments/exp43_runpod_bench/`): `prep_3x6x400.py` (free, ends in the
degeneracy gate) · `preflight.py` (refuses a bad run) · `launch_relax.py` ·
`launch_production.py` (self-sizing from the parent's logs) · `supervise.py` (re-attach to an
orphaned pod) · `watch.py --oneline` · `reap.py --kill` (**the panic button**) ·
`spend_ledger.py` (cumulative across ALL pods — the $15 is a SESSION cap).
